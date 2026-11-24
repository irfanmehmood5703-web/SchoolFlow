"""Attended school-SIM outbox. No HTTP request sends an SMS itself."""
import hashlib,hmac,re,secrets,time
from flask import Blueprint,abort,flash,g,jsonify,redirect,render_template,request,session,url_for
from sqlalchemy import select

API_ENDPOINTS={'sms_gateway.heartbeat','sms_gateway.claim','sms_gateway.start','sms_gateway.result','sms_gateway.batch','sms_gateway.batch_status','sms_gateway.batch_stop'}

def configure_sms_gateway(app,db,Student):
    bp=Blueprint('sms_gateway',__name__)
    rm=app.extensions['record_models'];Workflow=app.extensions['ops_models']['workflow'];Audit=app.extensions['ops_models']['audit']
    class Device(db.Model):
        __tablename__='sms_device'
        id=db.Column(db.Integer,primary_key=True)
        name=db.Column(db.String(100),nullable=False)
        campus=db.Column(db.String(160),nullable=False)
        active=db.Column(db.Boolean,nullable=False,default=True)
        digest=db.Column(db.String(64),nullable=False)
        generation=db.Column(db.Integer,nullable=False,default=1)
        last_seen=db.Column(db.Float,nullable=False,default=0)
    class Job(db.Model):
        __tablename__='sms_outbox'
        id=db.Column(db.String(43),primary_key=True,default=lambda:secrets.token_urlsafe(32))
        source=db.Column(db.String(200),unique=True,nullable=False)
        device_id=db.Column(db.Integer,db.ForeignKey('sms_device.id'),nullable=False,index=True)
        phone=db.Column(db.String(16),nullable=False)
        text=db.Column(db.Text,nullable=False)
        state=db.Column(db.String(20),nullable=False,default='queued',index=True)
        token=db.Column(db.String(43),nullable=False,default='')
        expires=db.Column(db.Float,nullable=False,default=0)
        generation=db.Column(db.Integer,nullable=False)
        created=db.Column(db.Float,nullable=False,default=time.time)
        updated=db.Column(db.Float,nullable=False,default=time.time)
        detail=db.Column(db.String(160),nullable=False,default='')
    app.extensions['sms_models']=dict(device=Device,job=Job)
    def phone(raw):
        value=re.sub(r'[\s()\-]','',str(raw or ''))
        if re.fullmatch(r'03\d{9}',value):value='+92'+value[1:]
        elif re.fullmatch(r'0092\d{10}',value):value='+'+value[2:]
        if not re.fullmatch(r'\+[1-9]\d{7,14}',value):raise ValueError('Use a valid mobile number including country code.')
        return value
    def owner():
        if not session.get('owner_id') or session.get('demo') or getattr(g,'staff_principal',None):abort(403)
    def csrf():
        if not hmac.compare_digest(request.form.get('_csrf',''),session.get('record_csrf','')) or not session.get('record_csrf'):abort(400)
        app.extensions['admission_capacity']['lock']()
    def audit(action,**values):db.session.add(Audit(action=action,data={**values,'owner_id':session.get('owner_id')}))
    @bp.errorhandler(ValueError)
    def invalid(error):
        db.session.rollback()
        if request.path.startswith('/api/'):return jsonify(error=str(error)),422
        return render_template('operation_error.html',title='Check SMS outbox',error=str(error)),422
    @bp.route('/workspace/general/sms',methods=['GET','POST'])
    def index():
        owner();key=''
        if request.method=='POST':
            csrf();action=request.form.get('action')
            if action=='add':
                name=request.form.get('name','').strip();campus=request.form.get('campus','')
                if not 1<=len(name)<=100 or campus not in app.extensions['staff_access_helpers']['campuses']():raise ValueError('Choose a name and configured campus.')
                key=secrets.token_urlsafe(32);device=Device(name=name,campus=campus,digest=hashlib.sha256(key.encode()).hexdigest())
                db.session.add(device);db.session.flush();audit('Register SMS device',device_id=device.id)
            elif action in ('rotate','suspend','activate'):
                device=db.get_or_404(Device,request.form.get('device_id',type=int))
                if action=='rotate':
                    key=secrets.token_urlsafe(32);device.digest=hashlib.sha256(key.encode()).hexdigest();device.generation+=1
                else:device.active=action=='activate'
                audit('Change SMS device',device_id=device.id,operation=action)
            elif action=='auto_config':
                did=request.form.get('device_id',type=int)
                device=db.get_or_404(Device,did)
                if not device.active:raise ValueError('Select an active SMS device.')
                template=request.form.get('template','').strip()
                school=request.form.get('school_name','').strip()
                if not 1<=len(template)<=1000 or not 1<=len(school)<=120:raise ValueError('Enter a school name and SMS template (maximum 1,000 characters).')
                for old in Workflow.query.filter_by(kind='sms-auto-config',status='Active').all():
                    if old.data.get('owner_id')==session.get('owner_id'):old.status='Replaced'
                db.session.add(Workflow(kind='sms-auto-config',status='Active',data=dict(owner_id=session.get('owner_id'),enabled=request.form.get('enabled')=='on',device_id=device.id,template=template,school_name=school)))
                audit('Update automatic admission SMS configuration',device_id=device.id)
            elif action=='cancel':
                job=db.get_or_404(Job,request.form.get('job_id'))
                if job.state not in ('queued','claimed'):raise ValueError('A dispatch already started. Do not retry it automatically; review on the phone.')
                job.state='cancelled';job.updated=time.time();audit('Cancel queued SMS',job_id=job.id)
            else:raise ValueError('Choose an SMS action.')
            db.session.commit()
            if key:return render_template('sms_key.html',title='Connect SMS App',device=device,key=key)
            return redirect(url_for('sms_gateway.index'))
        jobs=Job.query.order_by(Job.created.desc()).limit(100).all()
        auto=next((x for x in Workflow.query.filter_by(kind='sms-auto-config',status='Active').order_by(Workflow.id.desc()).all() if x.data.get('owner_id')==session.get('owner_id')),None)
        return render_template('sms_gateway.html',title='School SIM SMS',auto_config=auto.data if auto else {},devices=Device.query.order_by(Device.id).all(),jobs=jobs,campuses=[(c,c) for c in app.extensions['staff_access_helpers']['campuses']()])
    @bp.route('/workspace/fee-reminder-send',methods=['POST'])
    def fee_reminder_send():
        """Queue only explicitly confirmed, currently outstanding, school-scoped fee SMS."""
        owner();csrf()
        token=request.form.get('sms_token','')
        if not re.fullmatch(r'[A-Za-z0-9_-]{20,100}',token):raise ValueError('Reload the reminders page before sending.')
        try:ids=list(dict.fromkeys(int(x) for x in request.form.getlist('reminder_student_ids')))
        except ValueError:raise ValueError('Invalid student selection.')
        if not ids or len(ids)>100:raise ValueError('Select 1 to 100 students.')
        template=request.form.get('reminder_message','').strip()
        if not 1<=len(template)<=1000:raise ValueError('Enter a reminder message up to 1,000 characters.')
        device=db.get_or_404(Device,request.form.get('device_id',type=int))
        if not device.active:raise ValueError('Choose an active school SMS device.')
        Bill=app.extensions['ops_models']['bill']
        StudentDetail=rm['student']
        profile_model=app.extensions.get('institute_setup_models',{}).get('profile')
        profile=db.session.get(profile_model,1) if profile_model else None
        identity=getattr(g,'school_identity',None) or {}
        school_name=str((profile.data or {}).get('name') if profile else '' or '').strip() or identity.get('name') or 'School'
        students=Student.query.filter(Student.id.in_(ids)).all()
        if len(students)!=len(ids):raise ValueError('A selected student is unavailable.')
        student_map={x.id:x for x in students}
        balances={x:0 for x in ids};months={}
        for bill in Bill.query.filter(Bill.student_id.in_(ids)).all():
            if bill.remaining>0:
                balances[bill.student_id]+=bill.remaining
                if bill.student_id not in months or bill.month<months[bill.student_id]:months[bill.student_id]=bill.month
        details={x.student_id:(x.data or {}) for x in StudentDetail.query.filter(StudentDetail.student_id.in_(ids)).all()}
        items=[]
        for sid in ids:
            student=student_map[sid]
            if student.status!='Active' or balances[sid]<=0:raise ValueError('A selected student no longer has outstanding fees.')
            data=details.get(sid,{})
            campus=str(data.get('campus') or '').strip()
            if campus and campus!=device.campus:raise ValueError('Select a school SMS device for '+student.name+' campus.')
            raw=next((str(data.get(k) or '').strip() for k in ('father_phone','guardian_phone','parent_phone','phone','mobile','contact','father_mobile') if data.get(k)), '')
            recipient=phone(raw)
            body=template
            for key,value in {'student_name':student.name,'father_name':data.get('father_name') or data.get('father') or '', 'remaining_fee':f"{balances[sid]/100:,.2f}".rstrip('0').rstrip('.'),'fee_month':months.get(sid,''),'school_name':school_name}.items():
                body=body.replace('{'+key+'}',str(value))
            if not 1<=len(body)<=1000:raise ValueError('Personalized message exceeds 1,000 characters.')
            items.append((sid,recipient,body))
        count=0
        for sid,recipient,body in items:
            source='fee-reminder:'+token+':'+str(sid)
            if Job.query.filter_by(source=source).first():continue
            db.session.add(Job(source=source,device_id=device.id,phone=recipient,text=body,generation=device.generation,detail='Fee reminder student #'+str(sid)))
            count+=1
        audit('Queue selected fee reminder SMS',student_ids=ids,device_id=device.id,count=count)
        db.session.commit()
        flash(str(count)+' fee reminder SMS queued for the school SMS App. Delivery is not yet confirmed.','success')
        return redirect(url_for('ops.register',kind='auto-reminders'))

    @bp.route('/workspace/admission-query-sms',methods=['POST'])
    def admission_query_sms():
        owner();csrf()
        row=Workflow.query.filter_by(id=request.form.get('query_id',type=int),kind='queries').first_or_404()
        if row.status in ('Voided','Closed'):raise ValueError('This inquiry is closed.')
        device=db.get_or_404(Device,request.form.get('device_id',type=int))
        if not device.active:raise ValueError('Choose an active school SMS device.')
        recipient=phone(row.data.get('phone',''))
        body=request.form.get('message','').strip()
        if not 1<=len(body)<=1000:raise ValueError('SMS must be between 1 and 1,000 characters.')
        # One explicit submission token prevents accidental double queueing.
        token=request.form.get('sms_token','')
        if not re.fullmatch(r'[A-Za-z0-9_-]{20,100}',token):raise ValueError('Reload the inquiry page before sending.')
        source='admission-query:'+str(row.id)+':'+token
        if Job.query.filter_by(source=source).first():
            flash('This SMS request is already queued.','success')
            return redirect(url_for('ops.register',kind='queries'))
        job=Job(source=source,device_id=device.id,phone=recipient,text=body,generation=device.generation,detail='Admission inquiry #'+str(row.id))
        db.session.add(job);audit('Queue admission inquiry SMS',query_id=row.id,job_id=job.id,device_id=device.id)
        db.session.commit()
        flash('SMS queued for the school SMS App. Delivery is not yet confirmed.','success')
        return redirect(url_for('ops.register',kind='queries'))

    @bp.route('/workspace/admission-query-bulk-sms',methods=['POST'])
    def admission_query_bulk_sms():
        owner();csrf()
        try:ids=list(dict.fromkeys(int(x) for x in request.form.getlist('ids')))
        except ValueError:raise ValueError('Invalid inquiry selection.')
        if not ids or len(ids)>100:raise ValueError('Select 1 to 100 admission inquiries.')
        device=db.get_or_404(Device,request.form.get('device_id',type=int))
        if not device.active:raise ValueError('Select an active school SMS device.')
        template=request.form.get('bulk_message','').strip()
        if not 1<=len(template)<=1000:raise ValueError('Enter a message of 1 to 1,000 characters.')
        token=request.form.get('sms_token','')
        if not re.fullmatch(r'[A-Za-z0-9_-]{20,100}',token):raise ValueError('Reload the page before queueing SMS.')
        rows=Workflow.query.filter(Workflow.kind=='queries',Workflow.id.in_(ids),Workflow.status.notin_(['Voided','Closed'])).all()
        if len(rows)!=len(ids):raise ValueError('A selected inquiry is unavailable or closed.')
        items=[]
        for row in rows:
            if not row.data.get('sms_consent'):raise ValueError('SMS consent is missing for inquiry #'+str(row.id))
            if row.data.get('campus') and row.data['campus']!=device.campus:raise ValueError('Select a device in the inquiry campus.')
            recipient=phone(row.data.get('phone',''))
            body=template.replace('{student_name}',str(row.data.get('name',''))).replace('{class_name}',str(row.data.get('class_name',''))).replace('{school_name}',str(request.form.get('school_name','SchoolFlow'))[:120])
            if not 1<=len(body)<=1000:raise ValueError('Personalized SMS exceeds 1,000 characters.')
            source='admission-bulk:'+token+':'+str(row.id)
            items.append((row,recipient,body,source))
        count=0
        for row,recipient,body,source in items:
            if Job.query.filter_by(source=source).first():continue
            db.session.add(Job(source=source,device_id=device.id,phone=recipient,text=body,generation=device.generation,detail='Bulk admission inquiry #'+str(row.id)))
            count+=1
        audit('Queue manual bulk admission SMS',query_ids=ids,device_id=device.id,count=count)
        db.session.commit()
        flash(str(count)+' personalized SMS queued. Phone submission and delivery are not confirmed.','success')
        return redirect(url_for('ops.register',kind='queries'))

    def auto_admission_query(row):
        """Opt-in auto-queue only; the connected phone controls actual dispatch."""
        if not row.data.get('sms_consent'):return
        config=next((x for x in Workflow.query.filter_by(kind='sms-auto-config',status='Active').order_by(Workflow.id.desc()).all() if x.data.get('owner_id')==session.get('owner_id')),None)
        if not config or not config.data.get('enabled'):return
        device=db.session.get(Device,config.data.get('device_id'))
        if not device or not device.active:return
        campus=row.data.get('campus','')
        if campus and device.campus!=campus:return
        try:recipient=phone(row.data.get('phone',''))
        except ValueError:return
        name=(row.data.get('name') or 'Student').strip()
        school=(config.data.get('school_name') or 'Our School').strip()
        template=config.data.get('template') or 'Dear Parent, thank you for your interest in {student_name} at {school_name}. We received your admission inquiry.'
        body=template.replace('{student_name}',name).replace('{school_name}',school).replace('{class_name}',row.data.get('class_name') or 'your selected class')
        if not 1<=len(body)<=1000:return
        source='admission-auto:'+str(row.id)
        if Job.query.filter_by(source=source).first():return
        job=Job(source=source,device_id=device.id,phone=recipient,text=body,generation=device.generation,detail='Auto admission inquiry #'+str(row.id))
        db.session.add(job);audit('Auto queue admission SMS',query_id=row.id,job_id=job.id,device_id=device.id)

    app.extensions['auto_admission_query_sms']=auto_admission_query

    def resolve_school_template(body):
        """Resolve school branding before preview or SIM queueing."""
        school=(getattr(g,'sms_school',None) or {}).get('name') or (getattr(g,'school_identity',None) or {}).get('name')
        school=str(school or '').strip()
        if not school:raise ValueError('School name is missing from Institute Setup. Configure it before sending SMS.')
        body=re.sub(r'\\{\\s*school_name\\s*\\}',lambda match:school,str(body),flags=re.IGNORECASE)
        remaining=re.findall(r'\\{[a-zA-Z_][a-zA-Z_0-9]*\\}',body)
        if remaining:raise ValueError('Unresolved SMS template variables: '+', '.join(sorted(set(remaining)))+'. Update the request before sending.')
        return body

    def candidates(row,device):
        data=row.data;preferences=data.get('preferences',{})
        if data.get('audience')!='parent' or not preferences.get('app_sms'):raise ValueError('Only student-parent App SMS requests can be released to the SIM outbox.')
        result={}
        snapshots=data.get('messages',[])
        if not snapshots:raise ValueError('This request has no saved message snapshots.')
        for message in snapshots:
            if message.get('unresolved') and any(str(tag).strip('{} ').lower()!='school_name' for tag in message['unresolved']):raise ValueError('Resolve missing template values before releasing this request.')
            person=db.session.get(Student,message.get('person_id'));details=rm['student'].query.filter_by(student_id=person.id).first() if person else None
            if not person or not details or details.data.get('campus')!=device.campus:raise ValueError('All recipients must belong to the selected device campus.')
            if data.get('attendance_day'):
                from datetime import date
                current=app.extensions['ops_models']['daily'].query.filter_by(kind='student',person_id=person.id,day=date.fromisoformat(data['attendance_day'])).first()
                expected=data.get('attendance_statuses',{}).get(str(person.id))
                if not current or current.status!=expected:raise ValueError('Attendance changed after this SMS request. Review the latest attendance and prepare a new request.')
            family=db.session.get(rm['family'],details.family_id) if details.family_id else None
            family_data=family.data if family else {};body=resolve_school_template(message.get('text','').strip())
            if not 1<=len(body)<=1000:raise ValueError('SMS text must contain 1–1,000 characters.')
            contacts=[]
            if preferences.get('father_contact'):contacts.append(family_data.get('phone') or person.phone)
            if preferences.get('mother_contact'):contacts.append(family_data.get('mother_phone') or details.data.get('mother_phone'))
            if preferences.get('student_contact'):contacts.append(details.data.get('student_phone'))
            if not contacts:raise ValueError('Choose a recipient contact in the communication request.')
            for raw in contacts:
                recipient=phone(raw);source=f'workflow:{row.id}:{person.id}:{recipient}:{message.get("source_salary_id") or ""}'
                result[source]=dict(source=source,phone=recipient,text=body,name=person.name)
        if len(result)>200:raise ValueError('Release no more than 200 SMS at a time.')
        return list(result.values())
    @bp.route('/workspace/general/sms/release/<int:wid>',methods=['GET','POST'])
    def release(wid):
        owner();row=Workflow.query.filter_by(id=wid,kind='message').first_or_404();items=[]
        devices=Device.query.filter_by(active=True).all();did=request.values.get('device_id',type=int)
        device=db.get_or_404(Device,did) if did else None
        if device:
            if not device.active:raise ValueError('Choose an active SMS device.')
            items=candidates(row,device)
        if request.method=='POST':
            csrf()
            if not device or not items or request.form.get('confirm')!='yes':raise ValueError('Preview the recipients and confirm the school SIM cost.')
            db.session.refresh(device)
            if not device.active:raise ValueError('This SMS phone was suspended. Reload before releasing messages.')
            # Re-evaluate only under the tenant write gate. Source is unique, so
            # a repeated release does not send the same request a second time.
            for item in candidates(row,device):
                if not Job.query.filter_by(source=item['source']).first():db.session.add(Job(device_id=device.id,generation=device.generation,**{k:item[k] for k in ('source','phone','text')}))
            audit('Release school SIM SMS',request_id=wid,device_id=device.id,count=len(items));db.session.commit()
            flash('Queued for the SMS App. Start sending on the registered phone; nothing has been sent yet.','success');return redirect(url_for('sms_gateway.index'))
        return render_template('sms_release.html',title='Review school SIM SMS',row=row,devices=devices,device=device,items=items)
    def scope(device,school):return hashlib.sha256(f'{school.storage_key}:{device.id}:{device.generation}:sms-v1'.encode()).hexdigest()
    def auth(did):
        if request.content_length and request.content_length>4096:abort(413)
        if len(request.get_data(cache=True))>4096:abort(413)
        code=request.headers.get('X-Institute-Code','');authorization=request.headers.get('Authorization','')
        if not re.fullmatch(r'[A-Z0-9][A-Z0-9-]{2,39}',code) or not re.fullmatch(r'Bearer [A-Za-z0-9_-]{43}',authorization):abort(401)
        School=app.extensions['identity_models']['institute'];school=School.query.filter_by(code=code,active=True).first()
        if not school:abort(401)
        g.institute_engine=app.extensions['identity_helpers']['engine'](school.id);db.session.remove();app.extensions['admission_capacity']['lock']()
        device=db.session.get(Device,did)
        if not device or not hmac.compare_digest(device.digest,hashlib.sha256(authorization[7:].encode()).hexdigest()):abort(401)
        if not device.active:abort(403)
        expected=scope(device,school)
        if request.endpoint!='sms_gateway.heartbeat' and not hmac.compare_digest(request.headers.get('X-Device-Scope',''),expected):abort(409)
        g.sms_school=dict(scope=school.storage_key,name=school.name)
        device.last_seen=time.time();return device,expected
    def data():
        value=request.get_json(silent=True)
        if not isinstance(value,dict):raise ValueError('Use a JSON object.')
        return value
    def serialize(job):return dict(id=job.id,phone=job.phone,text=job.text,state=job.state,token=job.token,expires=job.expires)
    @bp.post('/api/sms/devices/<int:did>/heartbeat')
    def heartbeat(did):
        device,expected=auth(did);data();queued=Job.query.filter_by(device_id=device.id,generation=device.generation,state='queued').count();active=batches['active'](device);db.session.commit();return jsonify(scope=expected,name=device.name,campus=device.campus,school_scope=g.sms_school['scope'],school_name=g.sms_school['name'],queued=queued,active_batch=active)
    @bp.post('/api/sms/devices/<int:did>/claim')
    def claim(did):
        device,_=auth(did);payload=data();stamp=time.time();batch,response=batches['for_claim'](device,payload)
        if response is not None:db.session.commit();return jsonify(**response)
        # Never reclaim a started job: loss of a result is an ambiguous send.
        q=Job.query.filter_by(device_id=device.id,generation=device.generation,state='claimed')
        if batch:q=q.filter(Job.id.in_(batch.jobs))
        job=q.first()
        if job and job.expires<=stamp:job.state='queued';job.token='';db.session.flush();job=None
        if not job:
            q=Job.query.filter_by(device_id=device.id,generation=device.generation,state='queued')
            if batch:q=q.filter(Job.id.in_(batch.jobs))
            job=q.order_by(Job.created,Job.id).first()
            if job:job.state='claimed';job.token=secrets.token_urlsafe(32);job.expires=stamp+300;job.updated=stamp
        response=dict(job=serialize(job) if job else None)
        if batch:response['batch']=batches['summary'](batch)
        db.session.commit();return jsonify(**response)
    def owned(device,payload):
        jid=payload.get('id','');token=payload.get('token','')
        if not isinstance(jid,str) or not re.fullmatch(r'[A-Za-z0-9_-]{43}',jid) or not isinstance(token,str) or not re.fullmatch(r'[A-Za-z0-9_-]{43}',token):abort(403)
        job=db.get_or_404(Job,jid)
        if job.device_id!=device.id or job.generation!=device.generation or not job.token or not hmac.compare_digest(token,job.token):abort(403)
        return job
    @bp.post('/api/sms/devices/<int:did>/start')
    def start(did):
        device,_=auth(did);payload=data();job=owned(device,payload)
        if job.state!='claimed' or job.expires<=time.time():abort(409)
        batches['before_start'](device,job,payload)
        job.state='started';job.updated=time.time();db.session.commit();return jsonify(state='started')
    @bp.post('/api/sms/devices/<int:did>/result')
    def result(did):
        device,_=auth(did);payload=data();job=owned(device,payload);state=payload.get('state')
        if state not in ('sent','failed','unknown'):raise ValueError('Choose a valid phone submission result.')
        if job.state in ('sent','failed','unknown'):
            if job.state!=state:abort(409)
            db.session.commit();return jsonify(state=job.state,replayed=True)
        if job.state!='started':abort(409)
        job.state=state;job.detail=str(payload.get('detail',''))[:160];job.updated=time.time()
        batches['after_result'](device)
        audit('SMS phone submission result',job_id=job.id,state=state,device_id=device.id);db.session.commit();return jsonify(state=state,replayed=False)
    from sms_batches import configure_sms_batches
    batches=configure_sms_batches(app,db,bp,Device,Job,auth,data)
    app.register_blueprint(bp)
