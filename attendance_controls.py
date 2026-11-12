"""Owner alerts, campus geofences and enabled attendance choices."""
import hashlib,hmac,json,math,re,secrets,os,html
from urllib.parse import urlsplit
from collections import defaultdict
from datetime import datetime,time,timedelta,timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo
import click
from flask import Blueprint,abort,flash,g,jsonify,redirect,render_template,request,session,url_for,has_request_context
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import StaleDataError
from module_catalog import STATUSES
TZ=ZoneInfo('Asia/Karachi')
ALERT_DEFAULTS=dict(student_enabled=True,staff_enabled=True,student_delay=15,staff_delay=15)

def utc_now():return datetime.now(timezone.utc)
def coordinate(value,low,high):
    try:n=float(value)
    except (TypeError,ValueError):raise ValueError('Enter valid numeric coordinates.')
    if not math.isfinite(n) or not low<=n<=high:raise ValueError('Coordinate is outside its valid range.')
    return n

def distance_m(lat1,lon1,lat2,lon2):
    a,b=map(math.radians,(lat1,lat2));da=b-a;dl=math.radians(lon2-lon1)
    h=math.sin(da/2)**2+math.cos(a)*math.cos(b)*math.sin(dl/2)**2
    return 6371008.8*2*math.asin(math.sqrt(min(1,max(0,h))))

def configure_attendance_controls(app,db,Student,Employee):
    bp=Blueprint('attendance_controls',__name__)
    rm=app.extensions['record_models'];ops=app.extensions['ops_models'];Setting=app.extensions['school_settings_models']['setting'];Daily=ops['daily'];Audit=ops['audit']
    class Alert(db.Model):
        __tablename__='attendance_alert'
        id=db.Column(db.Integer,primary_key=True)
        day=db.Column(db.Date,nullable=False)
        kind=db.Column(db.String(10),nullable=False)
        data=db.Column(db.JSON,nullable=False,default=dict)
        unread=db.Column(db.Boolean,nullable=False,default=True)
        created=db.Column(db.DateTime,nullable=False,default=utc_now)
        __table_args__=(db.UniqueConstraint('day','kind'),)
    class Fence(db.Model):
        __tablename__='attendance_geofence'
        campus=db.Column(db.String(160),primary_key=True)
        latitude=db.Column(db.Float,nullable=False)
        longitude=db.Column(db.Float,nullable=False)
        radius=db.Column(db.Integer,nullable=False)
        enabled=db.Column(db.Boolean,nullable=False,default=False)
        within_only=db.Column(db.Boolean,nullable=False,default=True)
        version=db.Column(db.Integer,nullable=False,default=1)
        __mapper_args__={'version_id_col':version}
    class GeoDevice(db.Model):
        __tablename__='attendance_geo_device'
        id=db.Column(db.Integer,primary_key=True)
        employee_id=db.Column(db.Integer,db.ForeignKey('employee.id',ondelete='SET NULL'))
        campus=db.Column(db.String(160),nullable=False)
        name=db.Column(db.String(120),nullable=False)
        digest=db.Column(db.String(64),nullable=False,unique=True)
        active=db.Column(db.Boolean,nullable=False,default=True)
        created=db.Column(db.DateTime,nullable=False,default=utc_now)
        version=db.Column(db.Integer,nullable=False,default=1)
        __mapper_args__={'version_id_col':version}
    class GeoEvent(db.Model):
        __tablename__='attendance_geo_event'
        id=db.Column(db.Integer,primary_key=True)
        device_id=db.Column(db.Integer,db.ForeignKey('attendance_geo_device.id'),nullable=False)
        event_id=db.Column(db.String(64),nullable=False)
        fingerprint=db.Column(db.String(64),nullable=False)
        outcome=db.Column(db.String(30),nullable=False)
        reason=db.Column(db.String(200),nullable=False)
        distance=db.Column(db.Float,nullable=False)
        accuracy=db.Column(db.Float,nullable=False)
        created=db.Column(db.DateTime,nullable=False,default=utc_now)
        __table_args__=(db.UniqueConstraint('device_id','event_id'),)
    app.extensions['attendance_control_models']=dict(alert=Alert,fence=Fence,device=GeoDevice,event=GeoEvent)
    def campuses():return sorted({x.value for x in rm['settings'].query.filter_by(category='campus').all()})
    def config(key,default):
        row=db.session.get(Setting,key);return row,{**default,**(row.data if row else {})}
    def statuses(kind):
        data=getattr(request,'attendance_choices_cache',None) if has_request_context() else None
        if data is None:
            _,data=config('attendance-acronyms',{})
            if has_request_context():request.attendance_choices_cache=data
        return [s for s in STATUSES if s!='Sandwich Leave' and data.get(kind,{}).get(s,True)]
    def allowed(kind,status,previous=None):return status!='Sandwich Leave' and (status in statuses(kind) or status==previous)
    def version(row):
        if request.form.get('version')!=str(row.version if row else 0):raise ValueError('This setting changed. Reload before saving.')
    def save(key,data):
        row=db.session.get(Setting,key)
        if row:row.data=data
        else:db.session.add(Setting(key=key,data=data))
    def audit(action,**data):db.session.add(Audit(action=action,data=data))
    def commit():
        try:db.session.commit()
        except (IntegrityError,StaleDataError):db.session.rollback();raise ValueError('Another request changed this record. Reload and retry.')
    def owner_only():
        if getattr(g,'staff_principal',None) is not None:abort(403,'Owner attendance alerts are private to the institute owner.')
    @bp.before_request
    def guard():
        if request.method=='POST':
            token=request.form.get('_csrf','')
            if not token or not hmac.compare_digest(token,session.get('record_csrf','')):abort(400,'Reload this form.')
            app.extensions['admission_capacity']['lock']()
    @bp.errorhandler(ValueError)
    def invalid(error):
        db.session.rollback()
        if request.endpoint=='attendance_controls.self_attendance' and request.method=='POST':return jsonify(error=str(error)),422
        return render_template('operation_error.html',title='Check attendance settings',error=str(error)),422
    from werkzeug.exceptions import HTTPException
    @bp.errorhandler(HTTPException)
    def http_error(error):
        db.session.rollback()
        if request.endpoint=='attendance_controls.self_attendance' and request.method=='POST':return jsonify(error=error.description),error.code
        return error
    def check_alerts(stamp=None,force=False):
        stamp=(stamp or utc_now()).astimezone(TZ);day=stamp.date();row,settings=config('attendance-alerts',ALERT_DEFAULTS)
        if not row and not force:return 0
        app.extensions['admission_capacity']['lock']()
        marked={'student':set(),'staff':set()}
        for entry in Daily.query.filter_by(day=day).all():marked[entry.kind].add(entry.person_id)
        sh=app.extensions['school_settings_helpers'];Item=app.extensions['school_settings_models']['item']
        prepared=dict(assignments=sh['config']('hrm:shift-assignment'),templates={str(r.id):r for r in Item.query.filter_by(kind='shift-template').all()},students=defaultdict(list))
        for r in Item.query.filter_by(kind='student-shift').all():prepared['students'][r.scope].append(r)
        holidays=app.extensions['holiday_calendar_helpers']['rows']();known=set(campuses());groups=defaultdict(list);staff=[]
        for kind,Model in (('student',Student),('staff',Employee)):
            if not settings[kind+'_enabled']:continue
            people=Model.query.filter_by(status='Active').all();details=app.extensions['record_helpers']['raw_many']('student' if kind=='student' else 'employee',people)
            for person in people:
                info=details.get(person.id,{});campus=info.get('campus','')
                if campus not in known or any(h.scope in ('',campus) and (h.data['date'][5:]==day.strftime('%m-%d') if h.data.get('repeats') else h.data['date']==day.isoformat()) for h in holidays):continue
                schedule=sh['shift'](kind,person,info,day,prepared)
                if schedule.get('off') or not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d',schedule.get('in','')):continue
                start=datetime.combine(day,time.fromisoformat(schedule['in']),TZ)
                value=dict(id=person.id,start=start,campus=campus)
                if kind=='student':groups[(campus,person.class_name,info.get('section',''),info.get('academic_session',''))].append(value)
                else:staff.append(value)
        pending={}
        for key,people in groups.items():
            if not any(p['id'] in marked['student'] for p in people) and stamp>=min(p['start'] for p in people)+timedelta(minutes=settings['student_delay']):
                pending[json.dumps(key)]=dict(campus=key[0],class_name=key[1],section=key[2],session=key[3],count=len(people))
        candidates={'student':pending}
        if staff and not any(p['id'] in marked['staff'] for p in staff) and stamp>=min(p['start'] for p in staff)+timedelta(minutes=settings['staff_delay']):
            candidates['staff']={'all':dict(count=len(staff),start=min(p['start'] for p in staff).strftime('%H:%M'))}
        changes=0
        for kind,values in candidates.items():
            if not values:continue
            alert=Alert.query.filter_by(day=day,kind=kind).first();old=alert.data if alert else {}
            if set(values)<=set(old):continue
            if alert:alert.data={**old,**values};alert.unread=True
            else:db.session.add(Alert(day=day,kind=kind,data=values))
            changes+=1
        if changes:audit('Attendance alerts checked',day=day.isoformat(),new_or_updated=changes)
        commit();return changes
    @bp.route('/workspace/core/attendance-alerts',methods=['GET','POST'])
    def alerts():
        owner_only();row,data=config('attendance-alerts',ALERT_DEFAULTS)
        if request.method=='POST':
            action=request.form.get('action')
            if action=='save':
                version(row);updated={}
                for kind in ('student','staff'):
                    raw=request.form.get(kind+'_delay','')
                    if not raw.isdigit() or int(raw)>1440:raise ValueError('Use a delay of 0–1,440 minutes.')
                    updated[kind+'_delay']=int(raw);updated[kind+'_enabled']=request.form.get(kind+'_enabled')=='1'
                save('attendance-alerts',updated);audit('Update attendance alerts',before=data,after=updated);commit();flash('Attendance alert settings saved.','success')
            elif action=='check':check_alerts(force=True);flash('Attendance check completed.','success')
            elif action in ('read','read-all'):
                query=Alert.query.filter_by(unread=True)
                if action=='read':
                    raw=request.form.get('id','')
                    if not raw.isdigit():raise ValueError('Choose an alert.')
                    query=query.filter_by(id=int(raw))
                for item in query.all():item.unread=False
                commit()
            else:raise ValueError('Choose a supported alert action.')
            return redirect(url_for('attendance_controls.alerts'))
        rows=Alert.query.order_by(Alert.day.desc(),Alert.id.desc()).limit(200).all()
        return render_template('attendance_alerts.html',title='Attendance Alerts',row=row,settings=data,rows=rows,unread=Alert.query.filter_by(unread=True).count())
    @bp.route('/workspace/core/attendance-acronyms',methods=['GET','POST'])
    def acronyms():
        row,data=config('attendance-acronyms',{})
        if request.method=='POST':
            version(row);new={kind:{s:request.form.get(kind+'_'+s)=='1' and s!='Sandwich Leave' for s in STATUSES} for kind in ('staff','student')}
            for kind in new:
                if not any(new[kind].values()):raise ValueError('Keep at least one active status for each audience.')
            save('attendance-acronyms',new);audit('Update attendance acronyms',before=data,after=new);commit();return redirect(url_for('attendance_controls.acronyms'))
        return render_template('attendance_acronyms.html',title='Attendance Acronym Active/Inactive',row=row,choices=STATUSES,active={k:statuses(k) for k in ('student','staff')})
    def map_layers():
        try:
            raw=app.config.get('GEO_MAP_LAYERS') or json.loads(os.getenv('SCHOOLFLOW_GEO_MAP_LAYERS','{}'))
        except (ValueError,TypeError):return {}
        if not isinstance(raw,dict):return {}
        result={}
        for style in ('satellite','hybrid','topographic'):
            value=raw.get(style)
            if not isinstance(value,dict):continue
            def valid(url):
                if not isinstance(url,str) or len(url)>2000:return False
                try:parts=urlsplit(url)
                except ValueError:return False
                return parts.scheme=='https' and bool(parts.hostname) and parts.hostname not in ('localhost','127.0.0.1','::1') and not parts.username and not parts.password and all(x in url for x in ('{z}','{x}','{y}'))
            if not valid(value.get('url')) or not isinstance(value.get('attribution'),str) or not value['attribution'].strip():continue
            if value.get('overlay_url') and not valid(value['overlay_url']):continue
            result[style]=dict(url=value['url'],attribution=html.escape(value['attribution'][:500]),overlay_url=value.get('overlay_url'))
        return result
    @bp.route('/workspace/core/geo-attendance',methods=['GET','POST'])
    def geofences():
        names=campuses();campus=request.values.get('campus',names[0] if names else '')
        if campus and campus not in names:raise ValueError('Choose a configured campus.')
        row=db.session.get(Fence,campus) if campus else None
        if request.method=='POST':
            if not campus:raise ValueError('Configure a campus first.')
            version(row);lat=coordinate(request.form.get('latitude'),-90,90);lon=coordinate(request.form.get('longitude'),-180,180)
            raw=request.form.get('radius','')
            if not raw.isdigit() or not 15<=int(raw)<=10000:raise ValueError('Use a radius from 15 to 10,000 metres.')
            if row is None:row=Fence(campus=campus);db.session.add(row)
            row.latitude=lat;row.longitude=lon;row.radius=int(raw);row.enabled=request.form.get('enabled')=='1';row.within_only=request.form.get('within_only')=='1'
            audit('Save campus geofence',campus=campus,radius=row.radius,enabled=row.enabled);commit();flash('Campus geo location saved.','success');return redirect(url_for('attendance_controls.geofences',campus=campus))
        _,qr=config('attendance-devices',{})
        return render_template('geo_attendance.html',title='Geo Location Attendance',campuses=names,campus=campus,row=row,rows=Fence.query.order_by(Fence.campus).all(),early_out=bool(qr.get('early_short')),map_config=dict(latitude=row.latitude if row else None,longitude=row.longitude if row else None,radius=row.radius if row else 50,layers=map_layers()))
    @bp.route('/workspace/core/geo-attendance/devices',methods=['GET','POST'])
    def devices():
        if request.method=='POST':
            raw=request.form.get('id','')
            if not raw.isdigit():raise ValueError('Choose a registered device.')
            row=db.get_or_404(GeoDevice,int(raw));version(row);row.active=False;audit('Revoke geo attendance device',campus=row.campus,record_kind='employee',record_id=row.employee_id,device_id=row.id);commit();return redirect(url_for('attendance_controls.devices'))
        q=request.args.get('q','').strip();campus=request.args.get('campus','')
        if len(q)>120 or (campus and campus not in campuses()):raise ValueError('Choose valid device filters.')
        try:page=int(request.args.get('page',1))
        except ValueError:raise ValueError('Choose a valid page.')
        if page<1:raise ValueError('Choose a valid page.')
        query=db.session.query(GeoDevice,Employee).join(Employee,GeoDevice.employee_id==Employee.id).filter(GeoDevice.active==True)
        if q:query=query.filter(Employee.name.contains(q,autoescape=True))
        if campus:query=query.filter(GeoDevice.campus==campus)
        total=query.count();pages=max(1,(total+24)//25);page=min(page,pages)
        rows=query.order_by(Employee.name,GeoDevice.id).offset((page-1)*25).limit(25).all()
        return render_template('geo_devices.html',title='Geo Attendance — Employee Registered Devices',rows=rows,total=total,page=page,pages=pages,campuses=campuses(),campus=campus,q=q)
    @bp.route('/workspace/attendance/geo-self',methods=['GET','POST'])
    def self_attendance():
        principal=getattr(g,'staff_principal',None)
        if principal is None:abort(403,'Use an active employee-linked staff login with Self Geo Attendance permission.')
        employee=db.get_or_404(Employee,principal.employee_id);details=rm['employee'].query.filter_by(employee_id=employee.id).first();campus=details.data.get('campus','') if details else ''
        fence=db.session.get(Fence,campus)
        if request.method=='GET':return render_template('geo_self.html',title='My Geo Attendance',employee=employee,fence=fence,scope=(getattr(g,'school_identity',{}) or {}).get('scope','')+':'+str(principal.id))
        if employee.status!='Active' or not fence or not fence.enabled:abort(403,'Geo attendance is disabled for this employee/campus.')
        if request.form.get('action')=='register':
            name=request.form.get('name','').strip()
            if not name or len(name)>120:raise ValueError('Use a device label up to 120 characters.')
            if GeoDevice.query.filter_by(employee_id=employee.id,active=True).count()>=5:raise ValueError('Five active devices are already registered. Ask an administrator to revoke an old device.')
            key=secrets.token_urlsafe(32);device=GeoDevice(employee_id=employee.id,campus=campus,name=name,digest=hashlib.sha256(key.encode()).hexdigest());db.session.add(device);db.session.flush();audit('Register employee geo device',campus=campus,record_kind='employee',record_id=employee.id,device_id=device.id);commit();return jsonify(id=device.id,key=key)
        if request.form.get('action')!='mark':raise ValueError('Choose register or mark.')
        key=request.form.get('key','');raw=request.form.get('device','')
        if not raw.isdigit() or not re.fullmatch('[A-Za-z0-9_-]{43}',key):abort(401)
        device=db.session.get(GeoDevice,int(raw))
        if not device or not device.active or device.employee_id!=employee.id or device.campus!=campus or not hmac.compare_digest(device.digest,hashlib.sha256(key.encode()).hexdigest()):abort(401)
        values={k:request.form.get(k,'') for k in ('event_id','latitude','longitude','accuracy','captured_ms','direction')}
        if not re.fullmatch('[A-Za-z0-9_-]{8,64}',values['event_id']) or values['direction'] not in ('in','out'):raise ValueError('Use an event ID and explicit IN/OUT direction.')
        fingerprint=hashlib.sha256(json.dumps(values,sort_keys=True).encode()).hexdigest();previous=GeoEvent.query.filter_by(device_id=device.id,event_id=values['event_id']).first()
        if previous:
            if previous.fingerprint!=fingerprint:abort(409,'An event ID cannot be reused with changed data.')
            return jsonify(outcome=previous.outcome,reason=previous.reason,replayed=True)
        if GeoEvent.query.filter_by(device_id=device.id).filter(GeoEvent.created>utc_now()-timedelta(minutes=1)).count()>=60:abort(429,'Device event limit exceeded.')
        lat=coordinate(values['latitude'],-90,90);lon=coordinate(values['longitude'],-180,180);accuracy=coordinate(values['accuracy'],0,100)
        captured=coordinate(values['captured_ms'],0,1e15);stamp=utc_now()
        if not -5<=(stamp.timestamp()*1000-captured)/1000<=60:raise ValueError('Request a fresh device location before marking.')
        distance=distance_m(lat,lon,fence.latitude,fence.longitude)
        if fence.within_only and distance+accuracy>fence.radius:abort(403,'The location or its accuracy circle is outside the campus fence.')
        adapter=SimpleNamespace(id='geo:'+str(device.id),campus=campus,status='Pending',marks='both',last_marked=None)
        body=dict(person_kind='staff',person_id=employee.id,direction=values['direction'])
        outcome,reason,_,_=app.extensions['attendance_device_helpers']['write_event'](adapter,body,stamp)
        db.session.add(GeoEvent(device_id=device.id,event_id=values['event_id'],fingerprint=fingerprint,outcome=outcome,reason=reason,distance=distance,accuracy=accuracy));commit();return jsonify(outcome=outcome,reason=reason,replayed=False),201
    def tick_all():
        with app.app_context():
            School=app.extensions['identity_models']['institute'];schools=[(s.id,app.extensions['identity_helpers']['engine'](s.id)) for s in School.query.filter_by(active=True).all()];db.session.remove()
            for sid,engine in schools:
                with app.test_request_context('/internal/attendance-alerts'):
                    g.institute_engine=engine
                    try:
                        check_alerts()
                        app.extensions.get('whatsapp_helpers',{}).get('cleanup',lambda:0)()
                    except Exception:db.session.rollback();app.logger.exception('Attendance alert check failed for institute %s',sid)
                    finally:db.session.remove()
    @app.cli.command('attendance-alerts-check')
    @click.option('--code',required=True)
    def check_cli(code):
        School=app.extensions['identity_models']['institute'];school=School.query.filter_by(code=code.upper(),active=True).first()
        if not school:raise click.ClickException('Active institute not found.')
        engine=app.extensions['identity_helpers']['engine'](school.id)
        with app.test_request_context('/operator/attendance-alerts'):
            g.institute_engine=engine
            try:click.echo(str(check_alerts(force=True))+' alert groups created/updated.')
            finally:db.session.remove()
    @app.context_processor
    def self_link():
        p=getattr(g,'staff_principal',None)
        return dict(geo_self_enabled=bool(p and p.data.get('permissions',{}).get('attendance.self') and app.extensions['staff_access_helpers']['grant'](p,'attendance.self')))
    app.extensions['attendance_control_helpers']=dict(statuses=statuses,allowed=allowed,check_alerts=check_alerts,tick_all=tick_all)
    app.register_blueprint(bp)
