"""Scoped device administration and authenticated attendance event ingestion.

Recognition happens on a compatible client; no face images or biometric
identifiers are collected here. Device credentials never authorize roster reads.
"""
import hashlib,hmac,json,re
from datetime import datetime,date,time,timedelta,timezone
from collections import defaultdict
from zoneinfo import ZoneInfo
import secrets
import click
from flask import Blueprint,abort,flash,g,jsonify,redirect,render_template,request,session,url_for
from sqlalchemy.exc import IntegrityError,OperationalError
from sqlalchemy.orm.exc import StaleDataError

TZ=ZoneInfo('Asia/Karachi')
CHANNELS=('android','branded','whatsapp','none')
DEFAULTS=dict(student_channel='android',student_only_absent=True,student_absent=60,student_late=30,staff_channel='android',staff_only_absent=False,staff_absent=0,staff_late=0,teacher_notification=False,auto_staff_absent=False,auto_staff_short=False,early_short=False,early_minutes=0,classes=[])
API_ENDPOINTS=('attendance_devices.heartbeat','attendance_devices.ingest','attendance_devices.identity_card')

def utc_now():return datetime.now(timezone.utc)

def configure_attendance_devices(app,db,Student,Employee):
    bp=Blueprint('attendance_devices',__name__)
    rm=app.extensions['record_models'];ops=app.extensions['ops_models'];Setting=app.extensions['school_settings_models']['setting'];Audit=ops['audit'];Daily=ops['daily'];W=ops['workflow']
    class Device(db.Model):
        __tablename__='attendance_device'
        id=db.Column(db.Integer,primary_key=True)
        kind=db.Column(db.String(20),nullable=False)
        serial=db.Column(db.String(120),nullable=False)
        name=db.Column(db.String(120),nullable=False)
        campus=db.Column(db.String(160),nullable=False)
        marks=db.Column(db.String(10),nullable=False,default='both')
        status=db.Column(db.String(20),nullable=False,default='Pending')
        token_digest=db.Column(db.String(64),nullable=False,default='')
        model=db.Column(db.String(80),nullable=False,default='')
        client_version=db.Column(db.String(40),nullable=False,default='')
        first_seen=db.Column(db.DateTime)
        last_seen=db.Column(db.DateTime)
        last_marked=db.Column(db.DateTime)
        created=db.Column(db.DateTime,nullable=False,default=lambda:datetime.now(timezone.utc))
        revision=db.Column(db.Integer,nullable=False,default=1)
        __table_args__=(db.UniqueConstraint('kind','serial'),)
    class Scan(db.Model):
        __tablename__='attendance_device_scan'
        id=db.Column(db.Integer,primary_key=True)
        device_id=db.Column(db.Integer,db.ForeignKey('attendance_device.id'),nullable=False,index=True)
        campus=db.Column(db.String(160),nullable=False)
        event_id=db.Column(db.String(100),nullable=False)
        fingerprint=db.Column(db.String(64),nullable=False)
        person_kind=db.Column(db.String(10),nullable=False)
        person_id=db.Column(db.Integer)
        person_name=db.Column(db.String(120),nullable=False,default='')
        direction=db.Column(db.String(3),nullable=False)
        occurred=db.Column(db.DateTime,nullable=False,index=True)
        received=db.Column(db.DateTime,nullable=False)
        outcome=db.Column(db.String(20),nullable=False)
        reason=db.Column(db.String(200),nullable=False)
        __table_args__=(db.UniqueConstraint('device_id','event_id'),)
    class Mark(db.Model):
        __tablename__='attendance_device_mark'
        id=db.Column(db.Integer,primary_key=True)
        daily_id=db.Column(db.Integer,db.ForeignKey('daily.id'),nullable=False,unique=True)
        campus=db.Column(db.String(160),nullable=False)
        origin=db.Column(db.String(20),nullable=False)
        base_status=db.Column(db.String(30),nullable=False,default='')
        first_in=db.Column(db.DateTime)
        first_out=db.Column(db.DateTime)
    class IdentityBinding(db.Model):
        __tablename__='attendance_identity_binding'
        id=db.Column(db.Integer,primary_key=True)
        student_id=db.Column(db.Integer,db.ForeignKey('student.id',ondelete='CASCADE'),unique=True)
        employee_id=db.Column(db.Integer,db.ForeignKey('employee.id',ondelete='CASCADE'),unique=True)
        nonce=db.Column(db.String(43),nullable=False,unique=True,default=lambda:secrets.token_urlsafe(32))
        __table_args__=(db.CheckConstraint('(student_id IS NOT NULL AND employee_id IS NULL) OR (student_id IS NULL AND employee_id IS NOT NULL)'),)
    app.extensions['attendance_device_models']=dict(device=Device,scan=Scan,mark=Mark,binding=IdentityBinding)
    def device_scope(device):
        return hashlib.sha256(('schoolflow:gate-scope:'+g.attendance_namespace+':'+str(device.id)+':'+device.campus).encode()).hexdigest()
    def now():return utc_now()
    def aware(value):return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
    def local(value):return aware(value).astimezone(TZ)
    app.jinja_env.filters['device_time']=lambda v:local(v).strftime('%d-%b-%Y %I:%M:%S %p') if v else 'Not yet recorded'
    def campuses():return sorted({r.value for r in rm['settings'].query.filter_by(category='campus').all()}-{''})
    def class_options():
        maps=app.extensions['institute_setup_helpers']['payload']()['maps'];all_classes=sorted({r.value for r in rm['settings'].query.filter_by(category='class_name').all()})
        return {c:sorted({m['class_name'] for m in maps[c]}) if c in maps else all_classes for c in campuses()}
    def cfg():
        row=db.session.get(Setting,'attendance-devices');return row,{**DEFAULTS,**(row.data if row else {})}
    def version(row):
        current=row.revision if isinstance(row,Device) else row.version if row else 0
        if request.form.get('version')!=str(current):raise ValueError('These settings changed. Reload before saving.')
    def commit():
        try:db.session.commit()
        except (IntegrityError,StaleDataError):db.session.rollback();raise ValueError('Another request changed these records. Reload and try again.')
    def audit(action,**data):db.session.add(Audit(action=action,data=data))
    @bp.before_request
    def protect():
        if request.endpoint in API_ENDPOINTS:return
        if request.method=='POST':
            token=request.form.get('_csrf','')
            if not token or not hmac.compare_digest(token,session.get('record_csrf','')):abort(400,'Reload this form.')
            app.extensions['admission_capacity']['lock']()
    @bp.errorhandler(ValueError)
    def invalid(error):
        db.session.rollback()
        if request.endpoint in API_ENDPOINTS:return jsonify(error=str(error)),422
        return render_template('operation_error.html',title='Check attendance settings',error=str(error)),422
    @bp.errorhandler(IntegrityError)
    @bp.errorhandler(StaleDataError)
    def conflict(error):
        db.session.rollback()
        if request.endpoint in API_ENDPOINTS:return jsonify(error='Concurrent event conflict; retry the same event ID.'),409
        return render_template('operation_error.html',title='Reload attendance settings',error='This device ID already exists or the record changed. Reload before saving.'),422
    @bp.errorhandler(OperationalError)
    def unavailable(error):
        db.session.rollback()
        if request.endpoint in API_ENDPOINTS:return jsonify(error='Attendance devices are unavailable for this institute.'),503
        return render_template('operation_error.html',title='Attendance devices unavailable',error='The institute database needs the operator schema upgrade before this option can be used.'),503
    def form_config():
        result={}
        for prefix in ('student','staff'):
            channel=request.form.get(prefix+'_channel','')
            if channel not in CHANNELS:raise ValueError('Choose a valid SMS channel.')
            result[prefix+'_channel']=channel;result[prefix+'_only_absent']=request.form.get(prefix+'_only_absent')=='1'
            for key in ('absent','late'):
                value=request.form.get(prefix+'_'+key,'')
                if not value.isdigit() or int(value)>1440:raise ValueError('Timing limits must be between 0 and 1,440 minutes.')
                result[prefix+'_'+key]=int(value)
            if result[prefix+'_late']>result[prefix+'_absent']:raise ValueError('Mark Late After cannot exceed Mark Absent After.')
        for key in ('teacher_notification','auto_staff_absent','auto_staff_short','early_short'):result[key]=request.form.get(key)=='1'
        raw=request.form.get('early_minutes','0')
        if not raw.isdigit() or int(raw)>1440:raise ValueError('Early leaving allowance must be 0–1,440 minutes.')
        result['early_minutes']=int(raw);selected=[];options=class_options()
        for value in request.form.getlist('classes'):
            try:
                pair=json.loads(value)
                if not isinstance(pair,list) or len(pair)!=2 or any(not isinstance(v,str) for v in pair):raise ValueError()
                campus,cls=pair
            except (ValueError,TypeError):raise ValueError('Choose configured auto-absent classes.')
            if campus not in options or cls not in options[campus]:raise ValueError('Choose configured auto-absent classes.')
            if [campus,cls] not in selected:selected.append([campus,cls])
        result['classes']=selected
        return result
    @bp.route('/workspace/core/qr-attendance',methods=['GET','POST'])
    def settings():
        row,data=cfg()
        if request.method=='POST':
            action=request.form.get('action')
            if action=='save':
                version(row);updated=form_config()
                if row:row.data=updated
                else:row=Setting(key='attendance-devices',data=updated);db.session.add(row)
                audit('Update QR attendance settings',before=data,after=updated);commit();flash('Attendance rules saved. Notifications are queued only; providers are not connected.','success')
            elif action=='serials':
                serials=[v.strip() for v in request.form.get('serials','').split(',') if v.strip()];campus=request.form.get('campus','')
                if campus not in campuses() or len(serials)>100 or len(set(serials))!=len(serials) or any(not re.fullmatch(r'[A-Za-z0-9_.:-]{1,120}',v) for v in serials):raise ValueError('Choose a campus and up to 100 distinct comma-separated device IDs.')
                # This form adds registered IDs only. Removing text never revokes
                # an existing device silently; suspension is explicit below.
                for serial in serials:
                    existing=Device.query.filter_by(kind='biometric',serial=serial).first()
                    if existing and existing.campus!=campus:raise ValueError('A device ID is already registered to another campus.')
                    if not existing:db.session.add(Device(kind='biometric',serial=serial,name=serial,campus=campus,status='Approved'))
                audit('Register biometric attendance devices',campus=campus,serials=serials);commit();flash('Device IDs registered. Use Connect to issue each device its own connection key.','success')
            elif action=='tick':
                count=tick(now(),force=True);flash(str(count)+' attendance records updated from enabled rules.','success')
            else:raise ValueError('Choose a supported attendance action.')
            return redirect(url_for('attendance_devices.settings'))
        devices=Device.query.filter_by(kind='biometric').order_by(Device.id).all();stamp=now()
        return render_template('qr_attendance.html',title='QR Biometric Attendance',row=row,config=data,campuses=campuses(),classes=class_options(),devices=devices,live_count=sum(bool(d.last_seen and stamp-aware(d.last_seen)<timedelta(minutes=2) and d.status!='Removed') for d in devices),live=lambda d:bool(d.status!='Removed' and d.last_seen and stamp-aware(d.last_seen)<timedelta(minutes=2)),channels=[('android','SchoolFlow Android SMS App'),('branded','Branded SMS'),('whatsapp','WhatsApp SMS'),('none','Do not request SMS')])
    @bp.route('/workspace/core/face-gates',methods=['GET','POST'])
    def gates():
        if request.method=='POST':
            name=request.form.get('name','').strip();serial=request.form.get('serial','').strip();campus=request.form.get('campus','');marks=request.form.get('marks','both')
            if not name or len(name)>120 or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,120}',serial) or campus not in campuses() or marks not in ('both','in','out'):raise ValueError('Enter a gate name, unique device ID, configured campus and marking direction.')
            device=Device(kind='face',name=name,serial=serial,campus=campus,marks=marks,status='Pending');db.session.add(device);db.session.flush();audit('Register face attendance gate',device_id=device.id,campus=campus,name=name);commit();return redirect(url_for('attendance_devices.gates'))
        return render_template('face_gates.html',title='Face Attendance Gates',devices=Device.query.filter_by(kind='face').order_by(Device.id).all(),campuses=campuses())
    @bp.post('/workspace/core/attendance-devices/<int:did>')
    def edit_device(did):
        device=db.get_or_404(Device,did);version(device);action=request.form.get('action');key=None
        if action=='rename':
            name=request.form.get('name','').strip()
            if not name or len(name)>120:raise ValueError('Use a gate name up to 120 characters.')
            before=device.name;device.name=name;audit('Rename attendance gate',device_id=device.id,campus=device.campus,before={'name':before},after={'name':name})
        elif action=='status':
            status=request.form.get('status','')
            if status not in ('Pending','Approved','Suspended') or device.status=='Removed':raise ValueError('Choose Pending, Approved or Suspended for an available device.')
            before=device.status;device.status=status;audit('Change attendance gate status',device_id=device.id,campus=device.campus,before={'status':before},after={'status':status})
        elif action=='connect':
            if device.status=='Removed' or request.form.get('confirm')!='yes':raise ValueError('Confirm issuing a new connection key. Any previous key stops working.')
            key=secrets.token_urlsafe(32);device.token_digest=hashlib.sha256(key.encode()).hexdigest();audit('Rotate attendance device credential',device_id=device.id,campus=device.campus)
        elif action=='remove':
            if request.form.get('confirm')!='yes':raise ValueError('Confirm removing this device. Its history will remain.')
            device.status='Removed';device.token_digest='';audit('Remove attendance gate',device_id=device.id,campus=device.campus)
        else:raise ValueError('Choose a supported gate action.')
        device.revision+=1;commit()
        if key:return render_template('attendance_device_key.html',title='Connect Attendance Device',device=device,key=key)
        return redirect(url_for('attendance_devices.gates' if device.kind=='face' else 'attendance_devices.settings'))
    @bp.get('/workspace/core/qr-attendance/scanner')
    def scanner():
        return render_template('attendance_scanner.html',title='QR Attendance Scanner')
    @bp.get('/workspace/core/face-gates/scans')
    def scans():
        try:
            start=date.fromisoformat(request.args.get('from',now().astimezone(TZ).date().isoformat()));end=date.fromisoformat(request.args.get('to',start.isoformat()));limit=int(request.args.get('rows','200'));gate=int(request.args.get('gate','0'));person=int(request.args.get('person') or '0')
        except ValueError:raise ValueError('Choose valid dates, gate and row limit.')
        if start.year<1900 or end.year>9998 or start>end or (end-start).days>366 or limit not in (50,200,500,1000) or gate<0 or person<0:raise ValueError('Choose a date range up to 366 days and 50, 200, 500 or 1,000 rows.')
        lower=datetime.combine(start,time.min,TZ).astimezone(timezone.utc);upper=datetime.combine(end+timedelta(days=1),time.min,TZ).astimezone(timezone.utc)
        query=Scan.query.filter(Scan.occurred>=lower,Scan.occurred<upper)
        if gate:query=query.filter_by(device_id=gate)
        kind=request.args.get('kind','');q=request.args.get('q','').strip()
        if len(q)>120 or kind not in ('','student','staff') or (person and not kind):raise ValueError('Choose a valid person or search.')
        if person:query=query.filter_by(person_id=person,person_kind=kind)
        elif kind:query=query.filter_by(person_kind=kind)
        rows=query.order_by(Scan.occurred.desc(),Scan.id.desc()).limit(limit).all()
        # Name search intentionally searches loaded rows, like the reference;
        # Only this person performs a fresh bounded server query across dates.
        if q:rows=[s for s in rows if q.casefold() in s.person_name.casefold()]
        return render_template('face_scans.html',title='Which gate marked whom',rows=rows,devices={d.id:d for d in Device.query.all()},start=start,end=end,limit=limit,gate=gate,person=person,kind=kind)
    def authenticate_device(did):
        code=request.headers.get('X-Institute-Code','');authorization=request.headers.get('Authorization','')
        if not re.fullmatch(r'[A-Z0-9][A-Z0-9-]{2,39}',code) or not re.fullmatch(r'Bearer [A-Za-z0-9_-]{40,60}',authorization):abort(401)
        School=app.extensions['identity_models']['institute'];school=School.query.filter_by(code=code,active=True).first()
        if not school:abort(401)
        g.attendance_namespace=school.storage_key;g.institute_engine=app.extensions['identity_helpers']['engine'](school.id);db.session.remove()
        device=db.session.get(Device,did)
        digest=hashlib.sha256(authorization[7:].encode()).hexdigest()
        if not device or device.status=='Removed' or not device.token_digest or not hmac.compare_digest(device.token_digest,digest):abort(401)
        app.extensions['admission_capacity']['lock']();db.session.refresh(device)
        if device.status=='Removed' or not device.token_digest or not hmac.compare_digest(device.token_digest,digest):abort(401)
        claimed=request.headers.get('X-Device-Scope','')
        if claimed and (not re.fullmatch(r'[a-f0-9]{64}',claimed) or not hmac.compare_digest(claimed,device_scope(device))):abort(409,'Device scope changed. Reconnect and verify enrollment.')
        g.attendance_device_actor=dict(kind='Device',id=device.id,label=device.name)
        return device
    def payload(allowed):
        if (request.content_length is not None and request.content_length>8192) or len(request.get_data(cache=True))>8192:abort(413)
        data=request.get_json(silent=True)
        if not isinstance(data,dict) or set(data)-set(allowed):raise ValueError('Use the documented device event fields; biometric images are not accepted.')
        return data
    def seen(device,stamp):
        device.first_seen=device.first_seen or stamp;device.last_seen=stamp
    @bp.post('/api/attendance/devices/<int:did>/heartbeat')
    def heartbeat(did):
        data=payload(('model','client_version'));device=authenticate_device(did)
        for key,size in (('model',80),('client_version',40)):
            value=data.get(key,'')
            if not isinstance(value,str) or len(value)>size:raise ValueError('Check device information length.')
            if value:setattr(device,key,value)
        seen(device,now());result=dict(status=device.status,marks=device.marks,scope_id=device_scope(device),server_time=now().isoformat());commit();return jsonify(**result)
    def notify_many(kind,person_ids,status,day,data):
        prefix='student' if kind=='student' else 'staff';channel=data[prefix+'_channel'];sms=channel!='none' and (not data[prefix+'_only_absent'] or status=='Absent');teacher=kind=='staff' and data['teacher_notification']
        if not sms and not teacher:return
        prefs=dict(father_contact=kind=='student',app_sms=sms and channel=='android',branded_sms=sms and channel=='branded',whatsapp_sms=sms and channel=='whatsapp',teacher_notification=teacher)
        audience='parent' if kind=='student' else 'teacher';db.session.flush()
        messages=app.extensions['school_settings_helpers']['message_snapshots']('Attendance',person_ids,audience,event='attendance',context={'day':day.isoformat()})
        db.session.add(W(kind='message',status='Provider not configured',data=dict(subject='Attendance',ids=person_ids,audience=audience,preferences=prefs,messages=messages,source='attendance-device')))
    def holiday(campus,day):
        return any((r.data['date'][5:]==day.strftime('%m-%d') if r.data.get('repeats') else r.data['date']==day.isoformat()) for r in app.extensions['holiday_calendar_helpers']['rows'](campus))
    def shift(kind,person,data,day,prepared=None):
        schedule=app.extensions['school_settings_helpers']['shift'](kind,person,data,day,prepared)
        closed=any(r.scope in ('',data.get('campus','')) and (r.data['date'][5:]==day.strftime('%m-%d') if r.data.get('repeats') else r.data['date']==day.isoformat()) for r in prepared['holidays']) if prepared is not None else holiday(data.get('campus',''),day)
        if schedule.get('off') or closed:return None
        start=schedule.get('in','');end=schedule.get('out','')
        if not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d',start):return None
        begin=datetime.combine(day,time.fromisoformat(start),TZ)
        finish=datetime.combine(day,time.fromisoformat(end),TZ) if re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d',end) else None
        if finish and finish<=begin:return None
        return begin,finish
    def write_event(device,data,stamp):
        kind=data['person_kind'];person_id=data['person_id'];direction=data['direction'];when=local(stamp);day=when.date()
        Model=Student if kind=='student' else Employee;person=db.session.get(Model,person_id);details=rm['student' if kind=='student' else 'employee'].query.filter_by(**{('student_id' if kind=='student' else 'employee_id'):person_id}).first() if person else None
        info=details.data if details else {};valid=person and person.status=='Active' and info.get('campus')==device.campus
        if not valid:return 'Not marked','Person is unavailable for this gate.',None,''
        result=lambda outcome,reason:(outcome,reason,person.id,person.name)
        if device.status=='Suspended':return result('Not marked','Gate is suspended.')
        if device.marks not in ('both',direction):return result('Not marked','This gate does not mark this direction.')
        if (now()-aware(stamp)).total_seconds()>900 or (aware(stamp)-now()).total_seconds()>60 or day!=now().astimezone(TZ).date():return result('Not marked','Event must be from today, within 15 minutes and no more than one minute ahead.')
        schedule=shift(kind,person,info,day)
        if not schedule:return result('Not marked','No supported working shift, or this is an off/holiday day.')
        try:app.extensions['school_settings_helpers']['attendance_guard'](kind,day)
        except ValueError:return result('Not marked','Attendance period is locked.')
        row=Daily.query.filter_by(kind=kind,person_id=person.id,day=day).first();state=Mark.query.filter_by(daily_id=row.id).first() if row else None
        if row and (not state or state.origin=='manual' or row.status in ('Leave','Off Day','Death Leave','Paper Leave')):return result('Not marked','Existing manual attendance is preserved.')
        before=dict(status=row.status,time_in=row.time_in,time_out=row.time_out) if row else {}
        _,config=cfg();prefix='student' if kind=='student' else 'staff';begin,end=schedule
        if direction=='in':
            if state and state.first_in:return result('Already marked','An IN mark is already recorded for today.')
            if row and row.status!='Absent':return result('Not marked','Existing attendance needs manual review.')
            status='Late' if when>begin+timedelta(minutes=config[prefix+'_late']) else 'Present'
            if not app.extensions['attendance_control_helpers']['allowed'](kind,status):return result('Not marked','This attendance status is inactive.')
            if not row:row=Daily(kind=kind,person_id=person.id,day=day,status=status,lectures=0,time_in='',time_out='');db.session.add(row);db.session.flush()
            if not state:state=Mark(daily_id=row.id,campus=device.campus,origin='device');db.session.add(state)
            row.status=status;row.time_in=when.strftime('%H:%M');state.origin='device';state.first_in=stamp;state.base_status=status
        else:
            if not state or not state.first_in:return result('Not marked','An IN mark is required before OUT.')
            if state.first_out:return result('Already marked','An OUT mark is already recorded for today.')
            if aware(stamp)<aware(state.first_in):return result('Not marked','OUT cannot precede IN.')
            if not end:return result('Not marked','Configure an OUT shift before recording departure.')
            status='Short Leave' if kind=='staff' and config['early_short'] and when<end-timedelta(minutes=config['early_minutes']) else state.base_status
            if not app.extensions['attendance_control_helpers']['allowed'](kind,status,row.status):return result('Not marked','This attendance status is inactive.')
            row.time_out=when.strftime('%H:%M');state.first_out=stamp;row.status=status
        notify_many(kind,[person.id],row.status,day,config);device.last_marked=now();audit('Device attendance marked',campus=device.campus,device_id=device.id,record_kind='student' if kind=='student' else 'employee',record_id=person.id,record_name=person.name,before=before,after=dict(status=row.status,time_in=row.time_in,time_out=row.time_out),direction=direction)
        return result('Marked','Attendance saved.')
    def resolve_qr(value,device):
        typ=value.split(':')[1];student=typ=='student';Model=Student if student else Employee;Detail=rm['student' if student else 'employee'];fk=Detail.student_id if student else Detail.employee_id;number=Student.admission_no if student else Employee.employee_no
        candidates=db.session.query(Model.id,number).join(Detail,fk==Model.id).filter(Model.status=='Active',Detail.data['campus'].as_string()==device.campus).all()
        for pid,code in candidates:
            expected=hmac.new(str(app.config['SECRET_KEY']).encode(),f'schoolflow:{typ}-qr:{g.attendance_namespace}:{pid}:{code}'.encode(),hashlib.sha256).hexdigest()
            if hmac.compare_digest(value.rsplit(':',1)[1],expected):return ('student' if student else 'staff'),pid
        return ('student' if student else 'staff'),0
    @bp.post('/api/attendance/devices/<int:did>/identity')
    def identity_card(did):
        data=payload(('qr_token',));device=authenticate_device(did)
        if device.status not in ('Pending','Approved'):abort(403)
        token=data.get('qr_token')
        if not isinstance(token,str) or not re.fullmatch(r'schoolflow:(student|employee):[a-f0-9]{64}',token):raise ValueError('Present a SchoolFlow identity QR.')
        kind,pid=resolve_qr(token,device)
        if not pid:abort(404,'Identity is unavailable for this gate.')
        person=db.session.get(Student if kind=='student' else Employee,pid)
        column=IdentityBinding.student_id if kind=='student' else IdentityBinding.employee_id
        binding=IdentityBinding.query.filter(column==pid).first()
        if not binding:
            binding=IdentityBinding(**{('student_id' if kind=='student' else 'employee_id'):pid});db.session.add(binding);db.session.flush()
        seen(device,now());audit('Verify attendance identity enrollment',device_id=device.id,campus=device.campus,record_kind='student' if kind=='student' else 'employee',record_id=pid)
        result=dict(person_kind=kind,person_id=pid,name=person.name,scope_id=device_scope(device),identity_binding=binding.nonce)
        commit()
        return jsonify(**result)
    @bp.post('/api/attendance/devices/<int:did>/events')
    def ingest(did):
        data=payload(('event_id','person_kind','person_id','direction','occurred_at','qr_token','identity_binding'));device=authenticate_device(did)
        if not isinstance(data.get('event_id'),str) or not re.fullmatch(r'[A-Za-z0-9_-]{8,100}',data['event_id']) or data.get('direction') not in ('in','out'):raise ValueError('Check event ID and IN/OUT direction.')
        if 'qr_token' in data:
            if 'person_kind' in data or 'person_id' in data or not isinstance(data['qr_token'],str) or not re.fullmatch(r'schoolflow:(student|employee):[a-f0-9]{64}',data['qr_token']):raise ValueError('Use a SchoolFlow QR token, or an identified student/staff ID, not both.')
        elif data.get('person_kind') not in ('student','staff') or type(data.get('person_id')) is not int or not 0<data['person_id']<2147483648:raise ValueError('Check student/staff ID.')
        if 'identity_binding' in data and ('qr_token' not in data or not isinstance(data['identity_binding'],str) or not re.fullmatch(r'[A-Za-z0-9_-]{43}',data['identity_binding'])):raise ValueError('Use a verified identity binding with its SchoolFlow QR.')
        try:
            stamp=datetime.fromisoformat(data.get('occurred_at','').replace('Z','+00:00'))
            if stamp.tzinfo is None:raise ValueError()
            stamp=stamp.astimezone(timezone.utc);stamp.astimezone(TZ)
        except (ValueError,TypeError,AttributeError,OverflowError):raise ValueError('Use a timestamp with a timezone.')
        digest=hashlib.sha256(json.dumps(data,sort_keys=True,separators=(',',':')).encode()).hexdigest();prior=Scan.query.filter_by(device_id=device.id,event_id=data['event_id']).first()
        if prior:
            if prior.fingerprint!=digest:return jsonify(error='An event ID cannot be reused for different data.'),409
            return jsonify(id=prior.id,outcome=prior.outcome,reason=prior.reason,replayed=True)
        if 'qr_token' in data:
            kind,pid=resolve_qr(data['qr_token'],device);data={**data,'person_kind':kind,'person_id':pid}
        received=now()
        if Scan.query.filter_by(device_id=device.id).filter(Scan.received>received-timedelta(minutes=1)).count()>=600:return jsonify(error='Device event limit exceeded.'),429
        binding_ok=True
        if 'identity_binding' in data:
            column=IdentityBinding.student_id if data['person_kind']=='student' else IdentityBinding.employee_id
            binding=IdentityBinding.query.filter(column==data['person_id']).first()
            binding_ok=bool(binding and hmac.compare_digest(binding.nonce,data['identity_binding']))
        if binding_ok:outcome,reason,pid,name=write_event(device,data,stamp)
        else:outcome,reason,pid,name='Not marked','Identity enrollment changed. Verify and re-enroll this person.',None,''
        seen(device,received)
        row=Scan(device_id=device.id,campus=device.campus,event_id=data['event_id'],fingerprint=digest,person_kind=data['person_kind'],person_id=pid,person_name=name,direction=data['direction'],occurred=stamp,received=received,outcome=outcome,reason=reason);db.session.add(row);db.session.flush();commit()
        return jsonify(id=row.id,outcome=outcome,reason=reason,replayed=False),201
    def manual_write(row):
        if not row.id:return
        state=Mark.query.filter_by(daily_id=row.id).first()
        if state:state.origin='manual'
    def tick(stamp,force=False):
        stamp=aware(stamp);current=stamp.astimezone(TZ);day=current.date();row,config=cfg()
        if not row or not (config['classes'] or config['auto_staff_absent'] or config['auto_staff_short']) or not 6<=current.hour<21:return 0
        app.extensions['admission_capacity']['lock']();db.session.expire_all();row,config=cfg()
        bucket=current.strftime('%Y-%m-%d %H:')+str(current.minute//15);tickrow=db.session.get(Setting,'attendance-device-tick')
        if not force and tickrow and tickrow.data==dict(bucket=bucket,revision=row.version):return 0
        daily={(r.kind,r.person_id):r for r in Daily.query.filter_by(day=day).all()};states={r.daily_id:r for r in Mark.query.join(Daily,Mark.daily_id==Daily.id).filter(Daily.day==day).all()};changes=[]
        known_campuses=set(campuses());notifications=defaultdict(list)
        Item=app.extensions['school_settings_models']['item'];prepared=dict(assignments=app.extensions['school_settings_helpers']['config']('hrm:shift-assignment'),templates={str(t.id):t for t in Item.query.filter_by(kind='shift-template').all()},students=defaultdict(list),holidays=app.extensions['holiday_calendar_helpers']['rows']())
        for entry in Item.query.filter_by(kind='student-shift').order_by(Item.name,Item.id).all():prepared['students'][entry.scope].append(entry)
        for kind,Model in [('student',Student),('staff',Employee)]:
            if kind=='student' and not config['classes']:continue
            if kind=='staff' and not (config['auto_staff_absent'] or config['auto_staff_short']):continue
            try:app.extensions['school_settings_helpers']['attendance_guard'](kind,day)
            except ValueError:continue
            people=Model.query.filter_by(status='Active').order_by(Model.id).all();details=app.extensions['record_helpers']['raw_many']('student' if kind=='student' else 'employee',people)
            for person in people:
                info=details.get(person.id,{});campus=info.get('campus','')
                if campus not in known_campuses or (kind=='student' and [campus,person.class_name] not in config['classes']):continue
                schedule=shift(kind,person,info,day,prepared)
                if not schedule:continue
                start,end=schedule;existing=daily.get((kind,person.id));state=states.get(existing.id) if existing else None;status=None
                if not existing and (kind=='student' or config['auto_staff_absent']) and current>=start+timedelta(minutes=config[('student' if kind=='student' else 'staff')+'_absent']):status='Absent'
                elif kind=='staff' and config['auto_staff_short'] and existing and state and state.origin=='device' and state.first_in and not state.first_out and existing.status in ('Present','Late') and end and current>=end+timedelta(minutes=config['staff_absent']):status='Short Leave'
                if not status or not app.extensions['attendance_control_helpers']['allowed'](kind,status):continue
                before={'status':existing.status,'time_in':existing.time_in,'time_out':existing.time_out} if existing else {}
                if not existing:
                    existing=Daily(kind=kind,person_id=person.id,day=day,status=status,lectures=0,time_in='',time_out='');db.session.add(existing);db.session.flush();state=Mark(daily_id=existing.id,campus=campus,origin='auto');db.session.add(state)
                existing.status=status;notifications[(kind,status)].append(person.id);changes.append(dict(id=person.id,kind=kind,before=before,after={'status':status},campus=campus))
        for (kind,status),ids in notifications.items():
            for offset in range(0,len(ids),500):notify_many(kind,ids[offset:offset+500],status,day,config)
        if tickrow:tickrow.data=dict(bucket=bucket,revision=row.version)
        else:db.session.add(Setting(key='attendance-device-tick',data=dict(bucket=bucket,revision=row.version)))
        if changes:audit('Automatic attendance marked',changes=changes,day=day.isoformat())
        commit();return len(changes)
    def tick_all():
        with app.app_context():
            School=app.extensions['identity_models']['institute'];schools=[(s.id,app.extensions['identity_helpers']['engine'](s.id)) for s in School.query.filter_by(active=True).all()];db.session.remove()
            for sid,engine in schools:
                with app.test_request_context('/internal/attendance-worker'):
                    g.institute_engine=engine
                    try:tick(now())
                    except OperationalError:db.session.rollback();app.logger.warning('Attendance schema upgrade required for institute %s',sid)
                    except Exception:db.session.rollback();app.logger.exception('Attendance tick failed for institute %s',sid)
                    finally:db.session.remove();g.pop('institute_engine',None)
    @app.cli.command('attendance-tick')
    @click.option('--code',required=True)
    def tick_cli(code):
        School=app.extensions['identity_models']['institute'];school=School.query.filter_by(code=code.strip().upper(),active=True).first()
        if not school:raise click.ClickException('Active institute not found.')
        engine=app.extensions['identity_helpers']['engine'](school.id)
        with app.test_request_context('/operator/attendance-tick'):
            g.institute_engine=engine;db.session.remove()
            try:click.echo(str(tick(now(),force=True))+' attendance records updated.')
            finally:db.session.remove()
    app.extensions['attendance_device_helpers']=dict(tick=tick,tick_all=tick_all,manual_write=manual_write,write_event=write_event)
    app.register_blueprint(bp)
