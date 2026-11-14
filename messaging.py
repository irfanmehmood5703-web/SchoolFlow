"""Tenant-bound internal conversations; no SMS, push or external delivery."""
import hashlib,hmac,io,json,re,secrets,time
from datetime import datetime,timezone
from flask import Blueprint,abort,flash,g,jsonify,redirect,render_template,request,send_file,session,url_for
from sqlalchemy import or_,update,func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import StaleDataError
from messaging_files import uploads

DEFAULTS=dict(enabled=True,parents_start=True,students_start=False,pairs=['Teacher:Parent','Teacher:Student','Admin:Parent','Admin:Teacher','Owner:Parent','Owner:Teacher','Owner:Student'],disabled=[],files=True,photos=True,pdf=True,audio=True,max_mb=10,voice=True,voice_seconds=120,retention_days=0,contact_mode='warn',unresolved_hours=24,escalate_severity=4,notify_admin=True)
PAIRS=[('Teacher','Parent'),('Teacher','Student'),('Admin','Parent'),('Admin','Teacher'),('Owner','Parent'),('Owner','Teacher'),('Owner','Student')]
CONTACT=re.compile(r'[\w.+-]+\s*@\s*[\w.-]+\.[a-z]{2,}|(?:https?://|www\.)\S+|(?<!\w)@[\w.]{2,}|(?<!\w)\+?\d[\d\s().-]{6,}\d(?!\w)|(?:whats?app|facebook|instagram|telegram|tiktok)\s*[:=]\s*\S+',re.I)
DIGITS=str.maketrans('۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩','01234567890123456789')

def contact_spans(text):return [(m.start(),m.end()) for m in CONTACT.finditer(text.translate(DIGITS))]
def redact(text):
    for start,end in reversed(contact_spans(text)):text=text[:start]+'[contact details hidden]'+text[end:]
    return text

def configure_messaging(app,db,Student,Employee):
    bp=Blueprint('messages',__name__,url_prefix='/workspace/conversations')
    parents=Blueprint('parent_messages',__name__,url_prefix='/parents/<code>/messages')
    rm=app.extensions['record_models'];Staff=app.extensions['staff_account_model'];Workflow=app.extensions['ops_models']['workflow'];Audit=app.extensions['ops_models']['audit']
    class Policy(db.Model):
        __tablename__='conversation_policy'
        id=db.Column(db.Integer,primary_key=True)
        data=db.Column(db.JSON,nullable=False,default=dict)
        version=db.Column(db.Integer,nullable=False,default=1)
        __mapper_args__={'version_id_col':version}
    class Conversation(db.Model):
        __tablename__='conversation'
        id=db.Column(db.String(43),primary_key=True)
        campus=db.Column(db.String(160),nullable=False,index=True)
        subject=db.Column(db.String(180),nullable=False)
        people=db.Column(db.JSON,nullable=False)
        first_actor=db.Column(db.String(80),nullable=False,index=True)
        second_actor=db.Column(db.String(80),nullable=False,index=True)
        student_id=db.Column(db.Integer)
        status=db.Column(db.String(12),nullable=False,default='Open')
        created=db.Column(db.Float,nullable=False,default=time.time)
        updated=db.Column(db.Float,nullable=False,default=time.time,index=True)
        version=db.Column(db.Integer,nullable=False,default=1)
        __mapper_args__={'version_id_col':version}
    class Message(db.Model):
        __tablename__='conversation_message'
        id=db.Column(db.Integer,primary_key=True)
        conversation_id=db.Column(db.String(43),db.ForeignKey(Conversation.id),nullable=False,index=True)
        actor=db.Column(db.String(80),nullable=False)
        label=db.Column(db.String(180),nullable=False)
        role=db.Column(db.String(20),nullable=False)
        body=db.Column(db.Text,nullable=False)
        created=db.Column(db.Float,nullable=False,default=time.time,index=True)
        blocked=db.Column(db.Boolean,nullable=False,default=False)
        flagged=db.Column(db.Boolean,nullable=False,default=False)
        severity=db.Column(db.Integer,nullable=False,default=0)
        reason=db.Column(db.String(1000),nullable=False,default='')
    class File(db.Model):
        __tablename__='conversation_file'
        id=db.Column(db.Integer,primary_key=True)
        message_id=db.Column(db.Integer,db.ForeignKey(Message.id),nullable=False,index=True)
        name=db.Column(db.String(160),nullable=False)
        mime=db.Column(db.String(100),nullable=False)
        content=db.deferred(db.Column(db.LargeBinary,nullable=False))
        voice=db.Column(db.Boolean,nullable=False,default=False)
        seconds=db.Column(db.Float,nullable=False,default=0)
    class Seen(db.Model):
        __tablename__='conversation_seen'
        conversation_id=db.Column(db.String(43),db.ForeignKey(Conversation.id),primary_key=True)
        actor=db.Column(db.String(80),primary_key=True)
        last_id=db.Column(db.Integer,nullable=False,default=0)
    class Submission(db.Model):
        __tablename__='conversation_submission'
        token=db.Column(db.String(43),primary_key=True)
        actor=db.Column(db.String(80),nullable=False)
        fingerprint=db.Column(db.String(64),nullable=False)
        conversation_id=db.Column(db.String(43),nullable=False)
    class Rate(db.Model):
        __tablename__='conversation_rate'
        key=db.Column(db.String(120),primary_key=True)
        count=db.Column(db.Integer,nullable=False,default=0)
        expires=db.Column(db.Float,nullable=False)
    app.extensions['message_models']=dict(policy=Policy,conversation=Conversation,message=Message,file=File,seen=Seen,submission=Submission,rate=Rate)
    def config():
        row=db.session.get(Policy,1);return {**DEFAULTS,**(row.data if row else {})}
    def audit(action,**data):db.session.add(Audit(action=action,data={**data,'actor':g.message_actor['key']}))
    def stamp(raw):return datetime.fromtimestamp(raw,timezone.utc).astimezone(__import__('zoneinfo').ZoneInfo('Asia/Karachi')).strftime('%d %b %Y %I:%M %p')
    app.jinja_env.filters['message_time']=stamp
    def school_id():return g.parent_school.id if request.blueprint=='parent_messages' else session.get('institute_id')
    def allowed_campuses():
        if request.blueprint=='parent_messages':return {d.get('campus','') for s,d in family_children(g.message_actor['id'])}
        allowed=getattr(g,'access_campuses',None)
        return set(allowed) if allowed is not None else set(app.extensions['staff_access_helpers']['campuses']())
    def family_children(fid):
        rows=Student.query.join(rm['student'],rm['student'].student_id==Student.id).filter(rm['student'].family_id==fid,Student.status=='Active').order_by(Student.name).all()
        return app.extensions['record_helpers']['read_many']('student',rows)
    def school_actor():
        staff=getattr(g,'staff_principal',None)
        employee=db.session.get(Employee,staff.employee_id) if staff else None
        if staff:return dict(key='staff:'+str(staff.id),id=staff.id,role='Teacher' if staff.data.get('role')=='Teacher' else 'Admin',label=employee.name if employee else staff.username,staff=staff)
        if session.get('owner_id'):return dict(key='owner:'+str(session['owner_id']),id=session['owner_id'],role='Owner',label='School owner')
        if session.get('demo') or (app.testing and not app.config.get('IDENTITY_ENFORCE_IN_TESTS')):return dict(key='owner:demo',id='demo',role='Owner',label='Demo owner')
        abort(403)
    def active_actor(key):
        kind,_,rid=key.partition(':')
        if kind=='owner':
            if rid=='demo':return dict(key=key,id='demo',role='Owner',label='Demo owner') if not school_id() else None
            Owner=app.extensions['identity_models']['owner'];row=db.session.get(Owner,int(rid)) if rid.isdigit() else None
            if row and row.active and row.institute_id==school_id():return dict(key=key,id=row.id,role='Owner',label='School owner')
        if kind=='staff' and rid.isdigit():
            row=db.session.get(Staff,int(rid));employee=db.session.get(Employee,row.employee_id) if row else None
            if row and row.active and employee and employee.status=='Active' and key not in config()['disabled']:
                return dict(key=key,id=row.id,role='Teacher' if row.data.get('role')=='Teacher' else 'Admin',label=employee.name,staff=row)
        if kind=='parent' and rid.isdigit():
            family=db.session.get(rm['family'],int(rid))
            if family and family_children(family.id):return dict(key=key,id=family.id,role='Parent',label=family.data.get('father_name') or family.data.get('father') or 'Family '+family.number)
        return None
    def can_campus(actor,campus):
        if actor['role']=='Owner':return True
        if actor['role']=='Parent':return any(d.get('campus','')==campus for s,d in family_children(actor['id']))
        return campus in app.extensions['staff_access_helpers']['grant'](actor['staff'],'messages.view')
    def teacher_child(actor,student,details):
        if actor['role']!='Teacher':return True
        if not hasattr(g,'message_teacher_assignments'):g.message_teacher_assignments=Workflow.query.filter_by(kind='teacher-classes',status='Active').all()
        return any(str(r.data.get('employee_id'))==str(actor['staff'].employee_id) and r.data.get('campus')==details.get('campus') and r.data.get('class_name')==student.class_name and (not r.data.get('section') or r.data.get('section')==details.get('section')) for r in g.message_teacher_assignments)
    def can_manage():
        actor=g.message_actor
        if actor['role']=='Owner':return True
        p=getattr(g,'staff_principal',None)
        return p is not None and set(app.extensions['staff_access_helpers']['grant'](p,'messages.manage'))==set(app.extensions['staff_access_helpers']['campuses']()) and bool(app.extensions['staff_access_helpers']['campuses']())
    def can_create():
        if g.message_actor['role'] in ('Owner','Parent'):return True
        return bool(app.extensions['staff_access_helpers']['grant'](g.staff_principal,'messages.create'))
    def path(endpoint,**kw):
        parent=request.blueprint=='parent_messages'
        return url_for(('parent_messages.' if parent else 'messages.')+endpoint,**({'code':g.parent_school.code} if parent else {}),**kw)
    def protect():
        g.message_student_checks=set();g.pop('message_teacher_assignments',None)
        if request.blueprint=='parent_messages':
            helper=app.extensions['parent_portal_helpers'];helper['scope']();family=helper['principal']()
            if not family:return redirect(url_for('parent_portal.login',code=g.parent_school.code))
            actor=dict(key='parent:'+str(family.id),id=family.id,role='Parent',label=family.data.get('father_name') or family.data.get('father') or 'Family '+family.number)
        else:actor=school_actor()
        g.message_actor=actor
        if actor['key'] in config()['disabled']:abort(403,'Messaging is disabled for this account.')
        if request.method=='POST':
            if request.content_length and request.content_length>22*1024*1024:abort(413)
            token=request.form.get('_csrf','')
            if not token or not hmac.compare_digest(token,session.get('record_csrf','')):abort(400,'Reload the message form.')
            app.extensions['admission_capacity']['lock']()
            db.session.expire_all()
            if actor['key'] in config()['disabled']:abort(403,'Messaging is disabled for this account.')
        if request.blueprint=='parent_messages' and not family_children(actor['id']):abort(403,'No active children are linked to this account.')
    bp.before_request(protect);parents.before_request(protect)
    def invalid(error):
        db.session.rollback();return render_template('operation_error.html',title='Check Messages',error=str(error)),422
    def conflict(error):
        db.session.rollback();return render_template('operation_error.html',title='Reload Messages',error='This record changed. Reload before submitting again.'),409
    for blueprint in (bp,parents):
        blueprint.register_error_handler(ValueError,invalid);blueprint.register_error_handler(IntegrityError,conflict);blueprint.register_error_handler(StaleDataError,conflict)
        @blueprint.after_request
        def headers(response):
            response.headers['Cache-Control']='no-store';response.headers['Referrer-Policy']='no-referrer';return response
    def render(template,**kw):
        parent=request.blueprint=='parent_messages'
        p=getattr(g,'staff_principal',None)
        has=lambda code: g.message_actor['role']=='Owner' or (p is not None and bool(app.extensions['staff_access_helpers']['grant'](p,code)))
        accept=','.join((['image/jpeg','image/png','image/webp','image/gif'] if config()['photos'] else [])+(['application/pdf'] if config()['pdf'] else [])+(['audio/*'] if config()['audio'] else []))
        return render_template(template,title=kw.pop('title','Messages'),parent_mode=parent,school=getattr(g,'parent_school',None),actor=g.message_actor,cfg=config(),msg_url=path,manage=not parent and can_manage(),can_create=can_create(),report_access=not parent and has('messages.report'),export_access=not parent and has('messages.export'),can_update=parent or has('messages.update'),media_accept=accept,can_start=can_create() and (not parent or config()['parents_start']),**kw)
    def check_student(sid,campus,actor=None):
        if not sid:return
        key=(sid,campus,actor['key'] if actor else '')
        checked=getattr(g,'message_student_checks',set())
        if key in checked:return
        student=db.session.get(Student,sid);details=rm['student'].query.filter_by(student_id=sid).first()
        if not student or student.status!='Active' or not details or details.data.get('campus','')!=campus:abort(403,'The student scope has changed.')
        if actor and actor['role']=='Parent':
            if details.family_id!=actor['id']:abort(404)
            if app.extensions['parent_helpers']['access'](sid,campus,'messages')['effective']=='block':abort(403,'Parent message access is restricted. Contact the school office.')
        checked.add(key);g.message_student_checks=checked
    def conversation(cid):
        row=db.get_or_404(Conversation,cid);actor=g.message_actor
        if actor['key'] not in (row.first_actor,row.second_actor) or not can_campus(actor,row.campus):abort(404)
        if row.campus not in allowed_campuses() and not (actor['role']=='Owner' and not row.campus):abort(404)
        check_student(row.student_id,row.campus,actor)
        if not Message.query.filter(Message.conversation_id==row.id,or_(Message.blocked==False,Message.actor==actor['key'])).first():abort(404)
        return row
    def permitted_pair(a,b,audience=None):
        x=a['role'];y=audience or b['role']
        if x==y:return x in ('Owner','Admin','Teacher')
        if {x,y}<={'Owner','Admin'}:return True
        return any({x,y}==set(pair.split(':')) for pair in config()['pairs'])
    def send_allowed(row=None,target=None,audience=None):
        actor=g.message_actor;cfg=config()
        if not cfg['enabled']:raise ValueError('Messaging is off. Existing conversations remain readable.')
        if not can_create():abort(403)
        if row:
            other=row.second_actor if row.first_actor==actor['key'] else row.first_actor
            target=active_actor(other)
            audience=row.people.get(other,{}).get('audience') if actor['role']!='Parent' else None
            if row.status=='Resolved':raise ValueError('Reopen the conversation before replying.')
        if not target:raise ValueError('This recipient is inactive or no longer available.')
        effective_actor=actor
        if row and actor['role']=='Parent' and row.people.get(actor['key'],{}).get('audience')=='Student':effective_actor={**actor,'role':'Student'}
        if not permitted_pair(effective_actor,target,audience):raise ValueError('This school has disabled this messaging pair.')
        if actor['role']=='Parent' and row is None and not cfg['parents_start']:raise ValueError('Parents may reply, but cannot start new conversations.')
        if row and not can_campus(target,row.campus):raise ValueError('This recipient no longer has messaging access to this campus.')
    def directory(category,campus,sid,q):
        actor=g.message_actor;cfg=config();result=[]
        if campus not in allowed_campuses() and not (actor['role']=='Owner' and not campus and not allowed_campuses()):return []
        if not can_campus(actor,campus):return []
        if category not in ('Admin','Owner','Teacher','Parent','Student'):raise ValueError('Choose a recipient type.')
        if actor['role']=='Parent':
            if category not in ('Owner','Admin','Teacher'):return []
            check_student(sid,campus,actor)
            if not sid:return []
        if category=='Owner':
            Owner=app.extensions['identity_models']['owner']
            candidates=[dict(key='owner:'+str(r.id),id=r.id,role='Owner',label='School owner') for r in Owner.query.filter_by(institute_id=school_id(),active=True).all()] if school_id() else [dict(key='owner:demo',id='demo',role='Owner',label='Demo owner')]
        elif category in ('Teacher','Admin'):
            candidates=[]
            for staff in Staff.query.filter_by(active=True).order_by(Staff.id).all():
                a=active_actor('staff:'+str(staff.id))
                if a and a['role']==category and can_campus(a,campus):
                    if actor['role']=='Parent':
                        s=db.session.get(Student,sid);d=rm['student'].query.filter_by(student_id=sid).one()
                        if not teacher_child(a,s,d.data):continue
                    candidates.append(a)
        else:
            candidates=[]
            Details=rm['student'];Family=rm['family']
            rows=db.session.query(Student,Details,Family).join(Details,Details.student_id==Student.id).join(Family,Family.id==Details.family_id).filter(Student.status=='Active',Details.data['campus'].as_string()==campus)
            if q:rows=rows.filter(or_(Student.name.contains(q,autoescape=True),Family.number.contains(q,autoescape=True),Family.data['father'].as_string().contains(q,autoescape=True),Family.data['father_name'].as_string().contains(q,autoescape=True)))
            months=app.extensions['parent_helpers']['pending']()
            for s,d,family in rows.order_by(Student.name).limit(500).all():
                if not teacher_child(actor,s,d.data):continue
                if app.extensions['parent_helpers']['access'](s.id,campus,'messages',months.get(s.id,0))['effective']=='block':continue
                a=dict(key='parent:'+str(family.id),id=family.id,role='Parent',label=family.data.get('father_name') or family.data.get('father') or 'Family '+family.number)
                candidates.append({**a,'label':s.name+' · '+a['label'],'student_id':s.id,'audience':category,'value':a['key']+'|'+str(s.id)})
        for a in candidates:
            if a['key']==actor['key'] or not permitted_pair(actor,a,category):continue
            label=a['label']
            if q.casefold() not in label.casefold():continue
            result.append(dict(value=a.get('value',a['key']),label=label,role=category))
            if len(result)>=100:break
        return result
    def incoming_rows():
        actor=g.message_actor
        visible_ids=db.session.query(Message.conversation_id).filter(or_(Message.blocked==False,Message.actor==actor['key']))
        query=Conversation.query.filter(or_(Conversation.first_actor==actor['key'],Conversation.second_actor==actor['key']),Conversation.id.in_(visible_ids))
        scope=allowed_campuses()
        if actor['role']!='Owner' or scope:query=query.filter(Conversation.campus.in_(scope))
        q=request.args.get('q','').strip()[:160]
        if q:query=query.filter(Conversation.subject.contains(q,autoescape=True))
        rows=query.order_by(Conversation.updated.desc()).limit(100).all();visible=[]
        for r in rows:
            if actor['role']=='Parent':
                try:check_student(r.student_id,r.campus,actor)
                except Exception as error:
                    from werkzeug.exceptions import HTTPException
                    if isinstance(error,HTTPException):continue
                    raise
            visible.append(r)
        return visible
    def parent_mode():return request.blueprint=='parent_messages'
    def listing(cid=None,code=None):
        current=conversation(cid) if cid else None;rows=incoming_rows();items=[];last=0;files={};states={}
        if current:
            before=request.args.get('before','')
            if before and not before.isdigit():raise ValueError('Invalid message page.')
            query=Message.query.filter_by(conversation_id=current.id)
            query=query.filter(or_(Message.blocked==False,Message.actor==g.message_actor['key']))
            if before:query=query.filter(Message.id<int(before))
            items=list(reversed(query.order_by(Message.id.desc()).limit(100).all()))
            ids=[m.id for m in items];files={m.id:[] for m in items}
            if ids:
                for f in File.query.filter(File.message_id.in_(ids)).all():files[f.message_id].append(f)
            states={s.actor:s.last_id for s in Seen.query.filter_by(conversation_id=current.id).all()}
            last=max([m.id for m in items if not m.blocked]+[0])
        ids=[r.id for r in rows]
        seen_query=db.session.query(Seen.conversation_id.label('cid'),Seen.last_id.label('last')).filter(Seen.actor==g.message_actor['key']).subquery()
        unread_rows=db.session.query(Message.conversation_id,func.count(Message.id)).outerjoin(seen_query,Message.conversation_id==seen_query.c.cid).filter(Message.conversation_id.in_(ids),Message.actor!=g.message_actor['key'],Message.blocked==False,Message.id>func.coalesce(seen_query.c.last,0)).group_by(Message.conversation_id).all() if ids else []
        values=dict(unread_rows);counts={r.id:values.get(r.id,0) for r in rows}
        return render('internal_messages.html',rows=rows,current=current,items=items,files=files,states=states,unread=counts,last=last,token=secrets.token_urlsafe(32),q=request.args.get('q','')[:160],expired=lambda m:bool(config()['retention_days'] and time.time()>m.created+config()['retention_days']*86400),campuses=sorted(allowed_campuses()),children=family_children(g.message_actor['id']) if g.message_actor['role']=='Parent' else [],flagged_alert=bool(not parent_mode() and config()['notify_admin'] and can_manage() and Message.query.filter_by(flagged=True).first()))
    bp.add_url_rule('',view_func=listing,endpoint='inbox');parents.add_url_rule('',view_func=listing,endpoint='inbox')
    bp.add_url_rule('/<cid>',view_func=listing,endpoint='thread');parents.add_url_rule('/<cid>',view_func=listing,endpoint='thread')
    def recipients(code=None):
        q=request.args.get('q','').strip();campus=request.args.get('campus','');raw=request.args.get('student_id','')
        if len(q)>160:raise ValueError('Use a shorter search.')
        if raw and not raw.isdigit():raise ValueError('Choose a student.')
        return jsonify(people=directory(request.args.get('category','Admin'),campus,int(raw) if raw else None,q))
    for b in (bp,parents):b.add_url_rule('/recipients',view_func=recipients,endpoint='recipients')
    def post(cid=None,code=None):
        actor=g.message_actor;row=conversation(cid) if cid else None;cfg=config()
        subject=request.form.get('subject','').strip();body=request.form.get('body','').strip()
        if len(body)>10000 or len(subject)>180 or (not row and not subject):raise ValueError('Enter a subject up to 180 characters and message up to 10,000 characters.')
        if not re.fullmatch(r'[A-Za-z0-9_-]{43}',request.form.get('token','')):raise ValueError('Reload the conversation form.')
        target=None;audience=None;sid=None;campus=request.form.get('campus','')
        if not row:
            audience=request.form.get('category','Admin');raw=request.form.get('student_id','');sid=int(raw) if raw.isdigit() else None
            selected=request.form.get('recipient','')
            available=directory(audience,campus,sid,'');chosen=next((a for a in available if a['value']==selected),None)
            if not chosen:raise ValueError('Choose an available recipient in the selected campus. Search again if their access changed.')
            key,_,student_key=selected.partition('|');sid=int(student_key) if student_key else sid
            target=active_actor(key)
            check_student(sid,campus,actor if actor['role']=='Parent' else target if target and target['role']=='Parent' else None)
        send_allowed(row,target,audience)
        media=uploads(cfg)
        if not body and not media:raise ValueError('Enter a message or attach a file.')
        token=request.form.get('token','')
        if not re.fullmatch(r'[A-Za-z0-9_-]{43}',token):raise ValueError('Reload the conversation form.')
        payload=dict(thread=cid,subject=subject,body=body,recipient=request.form.get('recipient',''),category=audience,student=sid,campus=campus,files=[{k:(hashlib.sha256(v).hexdigest() if k=='content' else v) for k,v in f.items()} for f in media])
        fingerprint=hashlib.sha256(json.dumps(payload,sort_keys=True).encode()).hexdigest();prior=db.session.get(Submission,token)
        if prior:
            if prior.actor!=actor['key'] or prior.fingerprint!=fingerprint:raise ValueError('This submission was already used with different details.')
            return redirect(path('thread',cid=prior.conversation_id))
        for seconds,limit in ((60,30),(86400,500)):
            now=time.time();key=actor['key']+':'+str(seconds)+':'+str(int(now//seconds));rate=db.session.get(Rate,key)
            if not rate:rate=Rate(key=key,count=0,expires=(int(now//seconds)+1)*seconds);db.session.add(rate)
            if rate.count>=limit:abort(429,'Too many messages. Try later.')
            rate.count+=1
        detected=bool(contact_spans(body) or contact_spans(subject));blocked=detected and cfg['contact_mode']=='block'
        if not row:
            title=redact(subject) if detected and cfg['contact_mode'] in ('hide','block') else subject
            people={actor['key']:{k:actor[k] for k in ('label','role')},target['key']:{'label':target['label'],'role':target['role'],'audience':audience}}
            row=Conversation(id=secrets.token_urlsafe(32),campus=campus,subject=title,people=people,first_actor=actor['key'],second_actor=target['key'],student_id=sid);db.session.add(row);db.session.flush()
            for key in (row.first_actor,row.second_actor):db.session.add(Seen(conversation_id=row.id,actor=key,last_id=0))
        text=redact(body) if detected and cfg['contact_mode']=='hide' else body
        message=Message(conversation_id=row.id,actor=actor['key'],label=actor['label'],role=actor['role'],body=text,blocked=blocked,flagged=detected,severity=3 if detected else 0,reason='Contact details detected ('+cfg['contact_mode']+')' if detected else '')
        db.session.add(message);db.session.flush()
        for f in media:db.session.add(File(message_id=message.id,**f))
        row.updated=time.time();db.session.add(Submission(token=token,actor=actor['key'],fingerprint=fingerprint,conversation_id=row.id))
        audit('Save internal message',conversation_id=row.id,message_id=message.id,campus=row.campus,blocked=blocked,flagged=detected)
        db.session.commit();flash('Message blocked by school contact policy.' if blocked else 'Message saved inside SchoolFlow.','info' if blocked else 'success')
        return redirect(path('thread',cid=row.id))
    for b in (bp,parents):
        b.add_url_rule('/new',view_func=post,methods=['POST'],endpoint='new')
        b.add_url_rule('/<cid>/reply',view_func=post,methods=['POST'],endpoint='reply')
    def read(cid,code=None):
        row=conversation(cid);raw=request.form.get('last','')
        if not raw.isdigit():raise ValueError('Invalid read position.')
        message=Message.query.filter(Message.conversation_id==cid,Message.blocked==False,Message.id<=int(raw)).order_by(Message.id.desc()).first()
        if message:
            db.session.execute(update(Seen).where(Seen.conversation_id==cid,Seen.actor==g.message_actor['key'],Seen.last_id<message.id).values(last_id=message.id));db.session.commit()
        return '',204
    def status(cid,code=None):
        row=conversation(cid)
        if request.form.get('version')!=str(row.version):raise ValueError('Conversation changed. Reload first.')
        value=request.form.get('status')
        if value not in ('Open','Resolved'):raise ValueError('Choose Open or Resolved.')
        row.status=value;audit('Change conversation status',conversation_id=cid,campus=row.campus,status=value);db.session.commit();return redirect(path('thread',cid=cid))
    def flag(cid,mid,code=None):
        row=conversation(cid);m=Message.query.filter_by(conversation_id=cid,id=mid).first_or_404()
        if m.blocked and m.actor!=g.message_actor['key']:abort(404)
        severity=request.form.get('severity','');reason=request.form.get('reason','').strip()
        if severity not in ('1','2','3','4','5') or not 1<=len(reason)<=1000:raise ValueError('Choose severity 1–5 and enter a short reason.')
        m.flagged=True;m.severity=max(m.severity,int(severity));m.reason=(m.reason+'; ' if m.reason else '')+reason;m.reason=m.reason[-1000:]
        audit('Flag internal message',conversation_id=cid,message_id=mid,campus=row.campus,severity=int(severity))
        if int(severity)>=config()['escalate_severity']:
            db.session.add(Workflow(kind='message-support-escalation',status='Support not connected',data=dict(conversation_id=cid,message_id=mid,campus=row.campus,severity=int(severity),notify_admin=config()['notify_admin'])))
        db.session.commit();return redirect(path('thread',cid=cid))
    def attachment(cid,fid,code=None):
        row=conversation(cid);f=db.get_or_404(File,fid);m=db.get_or_404(Message,f.message_id)
        if m.conversation_id!=cid or (m.blocked and m.actor!=g.message_actor['key']):abort(404)
        if config()['retention_days'] and time.time()>m.created+config()['retention_days']*86400:abort(410,'Attachment availability has expired.')
        response=send_file(io.BytesIO(f.content),mimetype=f.mime,download_name=f.name,as_attachment=bool(request.args.get('download') or f.mime=='application/pdf'),conditional=True)
        response.headers['Content-Security-Policy']="default-src 'none'; sandbox";response.headers['X-Content-Type-Options']='nosniff';return response
    for b in (bp,parents):
        b.add_url_rule('/<cid>/read',view_func=read,methods=['POST'],endpoint='read')
        b.add_url_rule('/<cid>/status',view_func=status,methods=['POST'],endpoint='status')
        b.add_url_rule('/<cid>/flag/<int:mid>',view_func=flag,methods=['POST'],endpoint='flag')
        b.add_url_rule('/<cid>/files/<int:fid>',view_func=attachment,endpoint='file')
    @bp.route('/settings',methods=['GET','POST'])
    def settings():
        if not can_manage():abort(403)
        row=db.session.get(Policy,1)
        if request.method=='POST':
            if request.form.get('version')!=str(row.version if row else 0):raise ValueError('Settings changed. Reload before saving.')
            data={key:request.form.get(key)=='1' for key in ('enabled','parents_start','students_start','files','photos','pdf','audio','voice','notify_admin')}
            if data['students_start']:raise ValueError('Independent student sign-in is not available. Use the verified family account.')
            pairs=request.form.getlist('pairs');disabled=request.form.getlist('disabled')
            if any(pair not in [a+':'+b for a,b in PAIRS] for pair in pairs):raise ValueError('Choose supported messaging pairs.')
            staffkeys={'staff:'+str(s.id) for s in Staff.query.all()}
            if not set(disabled)<=staffkeys:raise ValueError('Choose existing staff accounts.')
            data.update(pairs=pairs,disabled=disabled,contact_mode=request.form.get('contact_mode'))
            if data['contact_mode'] not in ('warn','block','hide'):raise ValueError('Choose a contact handling policy.')
            for key,minimum,maximum in [('max_mb',1,20),('voice_seconds',10,600),('retention_days',0,3650),('unresolved_hours',1,720),('escalate_severity',1,5)]:
                raw=request.form.get(key,'')
                if not raw.isdigit() or not minimum<=int(raw)<=maximum or (key=='retention_days' and 0<int(raw)<30):raise ValueError('Choose a valid '+key.replace('_',' ')+'.')
                data[key]=int(raw)
            if not row:row=Policy(id=1,data=data);db.session.add(row)
            else:row.data=data
            audit('Update message settings');db.session.commit();flash('Communication settings saved.','success');return redirect(url_for('messages.settings'))
        users=[]
        for s in Staff.query.order_by(Staff.username).all():
            e=db.session.get(Employee,s.employee_id);users.append(dict(key='staff:'+str(s.id),label=e.name if e else s.username,role=s.data.get('role','User'),active=s.active))
        return render('message_settings.html',title='Communication Settings',version=row.version if row else 0,users=users,pairs=PAIRS)
    def report_data():
        query=Conversation.query.filter(Conversation.campus.in_(allowed_campuses())) if allowed_campuses() else Conversation.query.filter(Conversation.campus=='')
        if request.values.get('campus'):
            if request.values['campus'] not in allowed_campuses():abort(403)
            query=query.filter_by(campus=request.values['campus'])
        for key,column,offset in [('from',Conversation.created,0),('to',Conversation.created,86400)]:
            raw=request.values.get(key,'')
            if raw:
                try:moment=datetime.strptime(raw,'%Y-%m-%d').replace(tzinfo=__import__('zoneinfo').ZoneInfo('Asia/Karachi')).timestamp()+offset
                except ValueError:raise ValueError('Use valid report dates.')
                query=query.filter(column>=moment) if key=='from' else query.filter(column<moment)
        rows=query.order_by(Conversation.updated.desc()).limit(501).all()
        if len(rows)>500:raise ValueError('Narrow the report to at most 500 conversations.')
        if request.values.get('from') and request.values.get('to') and request.values['from']>request.values['to']:raise ValueError('From date must not be after To date.')
        grouped={r.id:[] for r in rows};states={r.id:{} for r in rows}
        messages=Message.query.filter(Message.conversation_id.in_(list(grouped))).order_by(Message.id).limit(20001).all() if rows else []
        if len(messages)>20000:raise ValueError('Narrow the report to 20,000 messages.')
        for message in messages:grouped[message.conversation_id].append(message)
        for seen in Seen.query.filter(Seen.conversation_id.in_(list(grouped))).all() if rows else []:states[seen.conversation_id][seen.actor]=seen.last_id
        data=[];q=request.values.get('q','').strip()[:160].casefold();state=request.values.get('status','')
        if state not in ('','Open','Resolved'):raise ValueError('Choose a valid conversation status.')
        for row in rows:
            if state and row.status!=state:continue
            messages=grouped[row.id]
            if q and q not in (row.subject+' '+' '.join(m.body for m in messages)).casefold():continue
            delivered=[m for m in messages if not m.blocked];family_messages=[m for m in delivered if m.role=='Parent'];school_replies=[m for m in delivered if m.role!='Parent' and family_messages and m.created>=family_messages[0].created]
            first=(school_replies[0].created-family_messages[0].created) if school_replies else None
            never=bool(family_messages and not school_replies)
            waiting=bool(family_messages and (not school_replies or family_messages[-1].created>school_replies[-1].created))
            pending=[m for m in family_messages if not school_replies or m.created>school_replies[-1].created]
            last_parent=pending[0].created if pending else None
            unresolved=bool(row.status=='Open' and waiting and last_parent and time.time()-last_parent>=config()['unresolved_hours']*3600)
            seen=states[row.id]
            unread_family=sum(m.role!='Parent' and row.people.get(k,{}).get('role')=='Parent' and m.id>seen.get(k,0) for m in delivered for k in (row.first_actor,row.second_actor) if k!=m.actor)
            unread_school=sum(m.role=='Parent' and row.people.get(k,{}).get('role')!='Parent' and m.id>seen.get(k,0) for m in delivered for k in (row.first_actor,row.second_actor) if k!=m.actor)
            data.append(dict(row=row,messages=messages,first=first,first_actor=school_replies[0].label if school_replies else '',first_role=school_replies[0].role if school_replies else '',first_key=school_replies[0].actor if school_replies else '',never=never,unresolved=unresolved,unread_family=unread_family,unread_school=unread_school,flagged=any(m.flagged for m in messages)))
        return data
    @bp.route('/report',methods=['GET','POST'])
    def report():
        data=report_data();tab=request.values.get('tab','overview')
        if tab not in ('overview','conversations','flagged','response'):raise ValueError('Choose a report tab.')
        if request.method=='POST':
            if tab=='flagged':data=[item for item in data if item['flagged']]
            kind=request.form.get('export')
            if kind not in ('summary','transcripts') or (kind=='transcripts' and request.form.get('confirm')!='yes'):raise ValueError('Confirm the full transcript export before downloading.')
            from report_exports import report_xlsx
            headers=['Conversation','Campus','Subject','Status','Created','Messages','Flagged','First reply seconds'] if kind=='summary' else ['Conversation','Campus','Subject','Message ID','Sender','Role','Time','Message','Blocked','Flagged','Severity']
            values=[]
            for item in data:
                r=item['row'];audit('Export conversation '+kind,conversation_id=r.id,campus=r.campus)
                if kind=='summary':values.append([r.id,r.campus,r.subject,r.status,stamp(r.created),len(item['messages']),item['flagged'],round(item['first'],2) if item['first'] is not None else ''])
                else:
                    for m in item['messages']:values.append([r.id,r.campus,r.subject,m.id,m.label,m.role,stamp(m.created),m.body,m.blocked,m.flagged,m.severity])
            if len(values)>20000:raise ValueError('Narrow the transcript export to 20,000 messages.')
            db.session.commit();return report_xlsx(headers,values,'conversation-'+kind)
        all_messages=[m for item in data for m in item['messages']];responses=[i['first'] for i in data if i['first'] is not None];media=File.query.filter(File.message_id.in_([m.id for m in all_messages])).all() if all_messages else []
        metrics=dict(conversations=len(data),active=sum(i['row'].updated>=time.time()-7*86400 for i in data),unresolved=sum(i['unresolved'] for i in data),never=sum(i['never'] for i in data),flagged=sum(i['flagged'] for i in data),unread_family=sum(i['unread_family'] for i in data),unread_school=sum(i['unread_school'] for i in data),messages=len(all_messages),blocked=sum(m.blocked for m in all_messages),median=__import__('statistics').median(responses) if responses else None,attachments=len(media))
        campus_stats=[];actor_stats=[]
        for campus in sorted({i['row'].campus for i in data}):
            group=[i for i in data if i['row'].campus==campus];seconds=[i['first'] for i in group if i['first'] is not None]
            campus_stats.append(dict(campus=campus,count=len(group),average=sum(seconds)/len(seconds) if seconds else None,slowest=max(seconds) if seconds else None))
        for key in sorted({i['first_key'] for i in data if i['first_key']}):
            matches=[i for i in data if i['first_key']==key];actor_stats.append(dict(label=matches[0]['first_actor'],role=matches[0]['first_role'],count=len(matches)))
        return render('message_report.html',title='Communication Report',data=data,tab=tab,metrics=metrics,campus_stats=campus_stats,actor_stats=actor_stats,campuses=sorted(allowed_campuses()))
    app.extensions['message_helpers']=dict(config=config,directory=directory,contact_spans=contact_spans)
    app.register_blueprint(bp);app.register_blueprint(parents)
