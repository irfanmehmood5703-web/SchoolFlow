"""Attended school-SIM outbox. No HTTP request sends an SMS itself."""
import hashlib,hmac,re,secrets,time
from flask import Blueprint,abort,flash,g,jsonify,redirect,render_template,request,session,url_for
from sqlalchemy import select

API_ENDPOINTS={'sms_gateway.heartbeat','sms_gateway.claim','sms_gateway.start','sms_gateway.result'}

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
            elif action=='cancel':
                job=db.get_or_404(Job,request.form.get('job_id'))
                if job.state not in ('queued','claimed'):raise ValueError('A dispatch already started. Do not retry it automatically; review on the phone.')
                job.state='cancelled';job.updated=time.time();audit('Cancel queued SMS',job_id=job.id)
            else:raise ValueError('Choose an SMS action.')
            db.session.commit()
            if key:return render_template('sms_key.html',title='Connect SMS App',device=device,key=key)
            return redirect(url_for('sms_gateway.index'))
        jobs=Job.query.order_by(Job.created.desc()).limit(100).all()
        return render_template('sms_gateway.html',title='School SIM SMS',devices=Device.query.order_by(Device.id).all(),jobs=jobs,campuses=[(c,c) for c in app.extensions['staff_access_helpers']['campuses']()])
    def candidates(row,device):
        data=row.data;preferences=data.get('preferences',{})
        if data.get('audience')!='parent' or not preferences.get('app_sms'):raise ValueError('Only student-parent App SMS requests can be released to the SIM outbox.')
        result={}
        snapshots=data.get('messages',[])
        if not snapshots:raise ValueError('This request has no saved message snapshots.')
        for message in snapshots:
            if message.get('unresolved'):raise ValueError('Resolve missing template values before releasing this request.')
            person=db.session.get(Student,message.get('person_id'));details=rm['student'].query.filter_by(student_id=person.id).first() if person else None
            if not person or not details or details.data.get('campus')!=device.campus:raise ValueError('All recipients must belong to the selected device campus.')
            family=db.session.get(rm['family'],details.family_id) if details.family_id else None
            family_data=family.data if family else {};body=message.get('text','').strip()
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
            flash('Queued for phone review. Nothing has been sent yet.','success');return redirect(url_for('sms_gateway.index'))
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
        device.last_seen=time.time();return device,expected
    def data():
        value=request.get_json(silent=True)
        if not isinstance(value,dict):raise ValueError('Use a JSON object.')
        return value
    def serialize(job):return dict(id=job.id,phone=job.phone,text=job.text,state=job.state,token=job.token,expires=job.expires)
    @bp.post('/api/sms/devices/<int:did>/heartbeat')
    def heartbeat(did):
        device,expected=auth(did);data();db.session.commit();return jsonify(scope=expected,name=device.name,campus=device.campus)
    @bp.post('/api/sms/devices/<int:did>/claim')
    def claim(did):
        device,_=auth(did);data();stamp=time.time()
        # Never reclaim a started job: loss of a result is an ambiguous send.
        job=Job.query.filter_by(device_id=device.id,generation=device.generation,state='claimed').first()
        if job and job.expires<=stamp:job.state='queued';job.token='';db.session.flush();job=None
        if not job:
            job=Job.query.filter_by(device_id=device.id,generation=device.generation,state='queued').order_by(Job.created).first()
            if job:job.state='claimed';job.token=secrets.token_urlsafe(32);job.expires=stamp+300;job.updated=stamp
        db.session.commit();return jsonify(job=serialize(job) if job else None)
    def owned(device,payload):
        jid=payload.get('id','');token=payload.get('token','')
        if not isinstance(jid,str) or not re.fullmatch(r'[A-Za-z0-9_-]{43}',jid) or not isinstance(token,str) or not re.fullmatch(r'[A-Za-z0-9_-]{43}',token):abort(403)
        job=db.get_or_404(Job,jid)
        if job.device_id!=device.id or job.generation!=device.generation or not job.token or not hmac.compare_digest(token,job.token):abort(403)
        return job
    @bp.post('/api/sms/devices/<int:did>/start')
    def start(did):
        device,_=auth(did);job=owned(device,data())
        if job.state!='claimed' or job.expires<=time.time():abort(409)
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
        audit('SMS phone submission result',job_id=job.id,state=state,device_id=device.id);db.session.commit();return jsonify(state=state,replayed=False)
    app.register_blueprint(bp)
