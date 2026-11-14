"""Built-in SchoolFlow guides and permission-scoped read-only actions."""
import hashlib,json,re,secrets,time
from datetime import datetime
from zoneinfo import ZoneInfo
from flask import Blueprint,abort,g,jsonify,render_template,request,session,url_for
from sqlalchemy import func
from workspace_actor import actor,scopes,stamp,csrf

STOP={'the','a','to','how','i','my','ka','ki','ke','hai','hain','ko','main','mein','kar','kya','is','ye','se','do','ban','kaise','bana','please','can','you','and','for','of'}
SYNONYMS={'فیس':'fee fees challans','فيس':'fee fees','چالان':'challans','بچے':'students','طالب':'students','حاضری':'attendance','تنخواہ':'salary payroll','salary':'payroll salary','salaries':'payroll salary','marks':'awards examination results','result':'awards results','fee':'fees plans challans','fees':'fee challans plans','students':'student admissions','student':'students admissions','admission':'admissions students','roll':'roll slips','award':'awards marks','promote':'students class transfer','promotion':'students class transfer','discount':'fee plans discounts','attendance':'attendance absentees','whatsapp':'whatsapp communication','diary':'student diary classwork homework','message':'internal messages','support':'support tickets','notification':'notifications','logo':'institute branding','school':'institute setup'}

def words(text):
    tokens=re.findall(r'[\w]+',text.casefold());expanded=[]
    for token in tokens:
        if token not in STOP:expanded.extend((token+' '+SYNONYMS.get(token,'')).split())
    return set(expanded)

def permission_for(a):
    key=a['slug'];cat=a['category']
    if cat=='Dashboard':return 'dashboard.view'
    if cat=='Admissions':return ('admissions' if key in ('queries','students','admission-approvals') else 'certificates' if key=='certificates' else 'fees')+'.view'
    if cat=='Exam & Attendance':return ('communication' if key in ('sms-blaster','sms-report','family-sms','notifications') else 'attendance' if 'attendance' in key or key in ('absentees','attendance-sheet') else 'exam')+'.view'
    if cat=='HRM':return ('attendance' if key.startswith('staff-attendance') else 'hrm' if key in ('employees','shifts','teacher-classes','notices','leave-approvals','leave-allotments','salary-report','staff-sms') else 'payroll')+'.view'
    if cat=='Finance':return 'requisitions.view' if key.startswith('req-') else 'finance.view'
    if cat=='General':return {'app-links':'apps.view','widgets':'widgets.view','parents-app':'parents.view','ptm-events':'ptm.view'}.get(key,'student_extras.view')
    if cat=='Configuration':return {'setup-users':'access.view','setup-logs':'logs.view','setup-certificates':'certificates.view'}.get(key,'core.view')
    if key=='support-help':return 'support.view'
    if key.startswith('message-') or key=='internal-messages':return 'messages.manage' if key=='message-settings' else 'messages.report' if key=='message-reports' else 'messages.view'
    return 'assistant.view'

def configure_assistant(app,db,Student,Employee):
    bp=Blueprint('assistant',__name__,url_prefix='/workspace/assistant')
    vendor=Blueprint('vendor_ai',__name__,url_prefix='/vendor/assistant')
    control={'info':{'identity_control':True}};bind=app.extensions.get('identity_bind_key')
    # Retain historical table mappings for additive upgrade compatibility only.
    # Neither table participates in Guide mode or enables external requests.
    class Policy(db.Model):
        __bind_key__=bind;__tablename__='assistant_provider_policy';__table_args__=control
        id=db.Column(db.Integer,primary_key=True)
        enabled=db.Column(db.Boolean,nullable=False,default=False)
        model=db.Column(db.String(120),nullable=False,default='gpt-5-mini')
        version=db.Column(db.Integer,nullable=False,default=1)
        __mapper_args__={'version_id_col':version}
    class Budget(db.Model):
        __bind_key__=bind;__tablename__='assistant_ai_budget';__table_args__=control
        key=db.Column(db.String(180),primary_key=True)
        count=db.Column(db.Integer,nullable=False,default=0)
    class Chat(db.Model):
        __tablename__='assistant_chat'
        id=db.Column(db.String(43),primary_key=True)
        actor=db.Column(db.String(100),nullable=False,index=True)
        access_stamp=db.Column(db.String(64),nullable=False)
        title=db.Column(db.String(180),nullable=False)
        created=db.Column(db.Float,nullable=False,default=time.time)
        updated=db.Column(db.Float,nullable=False,default=time.time,index=True)
    class Turn(db.Model):
        __tablename__='assistant_turn'
        id=db.Column(db.Integer,primary_key=True)
        chat_id=db.Column(db.String(43),db.ForeignKey(Chat.id),nullable=False,index=True)
        role=db.Column(db.String(20),nullable=False)
        body=db.Column(db.Text,nullable=False)
        mode=db.Column(db.String(20),nullable=False)
        links=db.Column(db.JSON,nullable=False,default=list)
        created=db.Column(db.Float,nullable=False,default=time.time)
    class Submission(db.Model):
        __tablename__='assistant_submission'
        token=db.Column(db.String(43),primary_key=True)
        actor=db.Column(db.String(100),nullable=False)
        fingerprint=db.Column(db.String(64),nullable=False)
        chat_id=db.Column(db.String(43),db.ForeignKey(Chat.id),nullable=False)
        answer_id=db.Column(db.Integer)
        created=db.Column(db.Float,nullable=False,default=time.time)
    app.extensions['assistant_models']=dict(policy=Policy,budget=Budget,chat=Chat,turn=Turn,submission=Submission)
    def protect():
        g.assistant_actor=actor(app);csrf()
        if request.content_length and request.content_length>12000:abort(413)
    bp.before_request(protect)
    @app.context_processor
    def tool_permissions():return dict(utility_allowed=lambda module:scopes(app,module+'.view') is None or bool(scopes(app,module+'.view')))
    def vendor_protect():
        if not app.extensions['vendor_helpers']['current']():return __import__('flask').redirect(url_for('vendor.login'))
        csrf()
    vendor.before_request(vendor_protect)
    def invalid(error):db.session.rollback();return jsonify(error=str(error)),422
    for b in (bp,vendor):
        b.register_error_handler(ValueError,invalid)
        @b.after_request
        def headers(response):response.headers['Cache-Control']='no-store';response.headers['Referrer-Policy']='no-referrer';return response
    def allowed_guides():
        return [a for a in app.extensions['how_to_catalogue']() if scopes(app,permission_for(a)) is None or bool(scopes(app,permission_for(a)))]
    def retrieve(question):
        query=words(question);ranked=[]
        for a in allowed_guides():
            title=words(a['title']+' '+a['slug']);body=words(a['summary']+' '+' '.join(a['steps']));score=5*len(query&title)+len(query&body)
            if score:ranked.append((score,a))
        ranked.sort(key=lambda x:x[0],reverse=True);return [a for _,a in ranked[:3]]
    def own_chat(cid):return Chat.query.filter_by(id=cid,actor=g.assistant_actor['key'],access_stamp=stamp(app)).first_or_404()
    def turn_data(t):return dict(id=t.id,role=t.role,body=t.body,mode=t.mode,links=t.links,created=t.created)
    @bp.get('')
    def page():return render_template('assistant_page.html',title='SchoolFlow Guide')
    @bp.get('/history')
    def history():
        chats=Chat.query.filter_by(actor=g.assistant_actor['key'],access_stamp=stamp(app)).order_by(Chat.updated.desc()).limit(30).all()
        return jsonify(chats=[dict(id=c.id,title=c.title) for c in chats],mode='Guide',provider_enabled=False)
    @bp.get('/chats/<cid>')
    def thread(cid):
        c=own_chat(cid);turns=list(reversed(Turn.query.filter_by(chat_id=c.id).order_by(Turn.id.desc()).limit(60).all()))
        return jsonify(chat_id=c.id,turns=[turn_data(t) for t in turns])
    def guide_answer(guides):
        if not guides:return 'Is maslay ka module ya option ka naam likhein. Main SchoolFlow ki mojooda guides mein madad kar sakta hoon. / Please name the SchoolFlow option you need help with, or open Support.'
        a=guides[0]
        return a['title']+'\n\n'+'\n'.join(str(i+1)+'. '+step for i,step in enumerate(a['steps']))+ ('\n\n'+a['note'] if a['note'] else '')
    def live(action):
        module={'students':'admissions.view','attendance':'attendance.view','fees':'fees.view','employees':'hrm.view'}.get(action)
        if not module:raise ValueError('Choose a supported read-only action.')
        allowed=scopes(app,module);assistant_scope=scopes(app,'assistant.view')
        if allowed is not None:
            allowed &= assistant_scope or set()
            if not allowed:abort(403,'This data permission is not granted.')
            g.access_campuses=allowed
        rm=app.extensions['record_models'];ops=app.extensions['ops_models'];today=datetime.now(ZoneInfo('Asia/Karachi')).date()
        if action=='students':
            rows=db.session.query(Student.status,func.count(Student.id)).group_by(Student.status).all()
            return 'Saved student counts in your permitted campuses:\n'+'\n'.join(str(status)+': '+str(count) for status,count in rows) if rows else 'No students are saved in your permitted campuses.'
        if action=='employees':
            rows=db.session.query(Employee.status,func.count(Employee.id)).group_by(Employee.status).all()
            return 'Saved employee counts in your permitted campuses:\n'+'\n'.join(str(status)+': '+str(count) for status,count in rows) if rows else 'No employees are saved in your permitted campuses.'
        if action=='attendance':
            D=ops['daily'];rows=db.session.query(D.status,func.count(D.id)).filter(D.kind=='student',D.day==today).group_by(D.status).all()
            return 'Student attendance on '+str(today)+':\n'+('\n'.join(str(status)+': '+str(count) for status,count in rows) if rows else 'No marks recorded. Unmarked students are not counted as present or absent.')
        bills=ops['bill'].query.filter_by(month=today.strftime('%Y-%m')).limit(2001).all()
        if len(bills)>2000:return 'This month has more than 2,000 challans. Open the Student Fee Status report for the complete filtered totals.'
        return 'Saved challans for '+today.strftime('%Y-%m')+' in your permitted scope:\nChallans: '+str(len(bills))+'\nGross billed PKR: '+format(sum(b.total for b in bills)/100,'.2f')+'\nDiscount PKR: '+format(sum(b.discount for b in bills)/100,'.2f')+'\nNet payable PKR: '+format(sum(b.total-b.discount for b in bills)/100,'.2f')+'\nPaid PKR: '+format(sum(b.paid for b in bills)/100,'.2f')+'\nRemaining PKR: '+format(sum(b.remaining for b in bills)/100,'.2f')+'\nThese are current balances against this bill month, not cash received during the month.'
    @bp.post('/ask')
    def ask():
        app.extensions['admission_capacity']['lock']()
        question=request.form.get('question','').strip();action=request.form.get('action','guide');cid=request.form.get('chat_id','');token=request.form.get('token','')
        if not 1<=len(question)<=2000 or not re.fullmatch(r'[A-Za-z0-9_-]{43}',token):raise ValueError('Write a question of up to 2,000 characters and reload the assistant if needed.')
        if action not in ('guide','students','fees','attendance','employees'):raise ValueError('Unsupported assistant action.')
        a=g.assistant_actor;fingerprint=hashlib.sha256(json.dumps([question,action,cid]).encode()).hexdigest();prior=db.session.get(Submission,token)
        if prior:
            if prior.actor!=a['key'] or prior.fingerprint!=fingerprint:raise ValueError('This request token was already used with different details.')
            c=own_chat(prior.chat_id)
            if prior.answer_id:return jsonify(chat_id=c.id,answer=turn_data(db.session.get(Turn,prior.answer_id)))
            if prior.created>time.time()-90:return jsonify(error='This reply is still being prepared. Retry the same request shortly.'),409
            recovered=Turn(chat_id=c.id,role='assistant',body='The previous request was interrupted. Start a new question to continue; no school records were changed.',mode='Guide',links=[]);db.session.add(recovered);db.session.flush();prior.answer_id=recovered.id;db.session.commit();return jsonify(chat_id=c.id,answer=turn_data(recovered))
        recent=Submission.query.filter(Submission.actor==a['key'],Submission.created>time.time()-3600).count()
        if recent>=40:abort(429,'Assistant hourly limit reached.')
        c=own_chat(cid) if cid else Chat(id=secrets.token_urlsafe(32),actor=a['key'],access_stamp=stamp(app),title=question[:180]);db.session.add(c);db.session.flush()
        guides=retrieve(question) if action=='guide' else []
        links=[dict(title=x['title'],url=url_for('how_to.article',slug=x['slug'])) for x in guides]
        answer=guide_answer(guides) if action=='guide' else live(action)
        mode='Guide' if action=='guide' else 'Live summary'
        # Guide-only: no provider request or external model activation path.
        user=Turn(chat_id=c.id,role='user',body=question,mode=mode,links=[]);db.session.add(user)
        submission=Submission(token=token,actor=a['key'],fingerprint=fingerprint,chat_id=c.id);db.session.add(submission)
        reply=Turn(chat_id=c.id,role='assistant',body=answer,mode=mode,links=links);db.session.add(reply);db.session.flush()
        submission.answer_id=reply.id;c.updated=time.time();db.session.commit()
        return jsonify(chat_id=c.id,answer=turn_data(reply))
    @vendor.route('',methods=['GET','POST'])
    def settings():
        if request.method=='POST':abort(403,'SchoolFlow uses built-in Guide mode only. External model activation is disabled.')
        return render_template('assistant_settings.html',title='SchoolFlow Guide')
    app.register_blueprint(bp);app.register_blueprint(vendor)
    app.extensions['assistant_helpers']=dict(guides=allowed_guides,retrieve=retrieve,live=live)
