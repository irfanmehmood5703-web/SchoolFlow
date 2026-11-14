"""Authenticated client-to-software-owner tickets in the control database."""
import hashlib,io,json,re,secrets,time
from flask import Blueprint,abort,flash,g,redirect,render_template,request,send_file,session,url_for
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import StaleDataError
from messaging_files import uploads
from workspace_actor import actor,scopes,csrf

STATUSES=('Open','In Progress','Waiting for School','Resolved')
CATEGORIES=('Technical','Account & Access','Fees & Reports','Feature Request','Other')

def configure_support(app,db):
    bp=Blueprint('support',__name__,url_prefix='/workspace/support')
    vendor=Blueprint('vendor_support',__name__,url_prefix='/vendor/support')
    bind=app.extensions.get('identity_bind_key');control={'info':{'identity_control':True}}
    class Ticket(db.Model):
        __bind_key__=bind;__tablename__='support_ticket';__table_args__=control
        id=db.Column(db.String(43),primary_key=True)
        school_id=db.Column(db.Integer,index=True)
        school_code=db.Column(db.String(40),nullable=False)
        actor=db.Column(db.String(100),nullable=False,index=True)
        label=db.Column(db.String(160),nullable=False)
        campus=db.Column(db.String(160),nullable=False,default='')
        subject=db.Column(db.String(180),nullable=False)
        category=db.Column(db.String(40),nullable=False)
        priority=db.Column(db.String(10),nullable=False)
        status=db.Column(db.String(30),nullable=False,default='Open')
        created=db.Column(db.Float,nullable=False,default=time.time)
        updated=db.Column(db.Float,nullable=False,default=time.time,index=True)
        school_seen=db.Column(db.Integer,nullable=False,default=0)
        vendor_seen=db.Column(db.Integer,nullable=False,default=0)
        nonce=db.Column(db.String(64),nullable=False,unique=True)
        fingerprint=db.Column(db.String(64),nullable=False)
        version=db.Column(db.Integer,nullable=False,default=1)
        __mapper_args__={'version_id_col':version}
    class Reply(db.Model):
        __bind_key__=bind;__tablename__='support_reply';__table_args__=control
        id=db.Column(db.Integer,primary_key=True)
        ticket_id=db.Column(db.String(43),db.ForeignKey(Ticket.id),nullable=False,index=True)
        sender=db.Column(db.String(160),nullable=False,index=True)
        label=db.Column(db.String(160),nullable=False)
        human=db.Column(db.Boolean,nullable=False,default=False)
        body=db.Column(db.Text,nullable=False)
        created=db.Column(db.Float,nullable=False,default=time.time)
        nonce=db.Column(db.String(64),nullable=False,unique=True)
        fingerprint=db.Column(db.String(64),nullable=False)
    class File(db.Model):
        __bind_key__=bind;__tablename__='support_file';__table_args__=control
        id=db.Column(db.Integer,primary_key=True)
        reply_id=db.Column(db.Integer,db.ForeignKey(Reply.id),nullable=False,index=True)
        name=db.Column(db.String(160),nullable=False)
        mime=db.Column(db.String(100),nullable=False)
        content=db.deferred(db.Column(db.LargeBinary,nullable=False))
    app.extensions['support_models']=dict(ticket=Ticket,reply=Reply,file=File)
    def vendor_mode():return request.blueprint=='vendor_support'
    def protect():
        if vendor_mode():
            user=app.extensions['vendor_helpers']['current']()
            if not user:return redirect(url_for('vendor.login'))
            g.support_actor=dict(key='vendor:'+str(user.id),label='Software owner',school_id=None,school_code='',demo=False)
        else:g.support_actor=actor(app)
        csrf()
        if request.method=='POST' and g.support_actor.get('demo'):abort(403,'Demo preview only. Sign in to a private school to send a ticket to the software owner.')
        if request.method=='POST':
            if request.content_length and request.content_length>22*1024*1024:abort(413)
            app.extensions['vendor_helpers']['lock']()
    bp.before_request(protect);vendor.before_request(protect)
    def query():
        if vendor_mode():return Ticket.query.filter(Ticket.school_id.isnot(None))
        a=g.support_actor;query=Ticket.query.filter_by(school_id=a['school_id'],actor=a['key'])
        permitted=scopes(app,'support.view')
        if permitted is not None:
            if request.method=='POST':permitted &= (scopes(app,'support.create') or set()) if request.endpoint!='support.read' else permitted
            query=query.filter(Ticket.campus.in_(permitted))
        return query
    def get(tid):return query().filter_by(id=tid).first_or_404()
    def route(name,**kw):return url_for(('vendor_support.' if vendor_mode() else 'support.')+name,**kw)
    def file_inputs():return uploads(dict(files=True,voice=False,photos=True,pdf=True,audio=False,max_mb=5,voice_seconds=120))
    def fingerprint(body,files,**fields):return hashlib.sha256(json.dumps(dict(body=body,files=[dict(name=f['name'],sha=hashlib.sha256(f['content']).hexdigest()) for f in files],**fields),sort_keys=True).encode()).hexdigest()
    def nonce():
        raw=request.form.get('token','')
        if not re.fullmatch(r'[A-Za-z0-9_-]{43}',raw):raise ValueError('Reload the support form.')
        a=g.support_actor
        return hashlib.sha256((str(a['school_id'])+'|'+a['key']+'|'+raw).encode()).hexdigest()
    def audit(action,ticket):
        M=app.extensions['vendor_models']['audit'];db.session.add(M(actor=g.support_actor['key'],action=action,school_code=ticket.school_code))
    def invalid(error):db.session.rollback();return render_template('operation_error.html',title='Check Support',error=str(error)),422
    def conflict(error):db.session.rollback();return render_template('operation_error.html',title='Reload Support',error='This ticket changed. Reload before submitting again.'),409
    for b in (bp,vendor):
        b.register_error_handler(ValueError,invalid);b.register_error_handler(IntegrityError,conflict);b.register_error_handler(StaleDataError,conflict)
        @b.after_request
        def headers(response):response.headers['Cache-Control']='no-store';response.headers['Referrer-Policy']='no-referrer';return response
    def render(current=None):
        state=request.args.get('status','')
        if state and state not in STATUSES:raise ValueError('Choose a valid ticket status.')
        q=query()
        if state:q=q.filter_by(status=state)
        rows=q.order_by(Ticket.updated.desc()).limit(100).all()
        replies=[]
        # Long cases have an explicit bounded page; no transcript is silently lost.
        before=request.args.get('before','')
        if current:
            rq=Reply.query.filter_by(ticket_id=current.id)
            if before:
                if not before.isdigit():raise ValueError('Invalid support page.')
                rq=rq.filter(Reply.id<int(before))
            replies=list(reversed(rq.order_by(Reply.id.desc()).limit(100).all()))
        files={r.id:[] for r in replies}
        for f in File.query.filter(File.reply_id.in_(list(files))).all() if files else []:files[f.reply_id].append(f)
        permitted=scopes(app,'support.create') if not vendor_mode() else None
        campuses=sorted(permitted if permitted is not None else app.extensions['staff_access_helpers']['campuses']()) if not vendor_mode() else []
        return render_template('support.html',title='Support inbox' if vendor_mode() else 'Support',vendor_mode=vendor_mode(),current=current,rows=rows,replies=replies,files=files,token=secrets.token_urlsafe(32),statuses=STATUSES,categories=CATEGORIES,support_url=route,actor=g.support_actor,campuses=campuses,can_write=(vendor_mode() or permitted is None or bool(permitted)) and not g.support_actor.get('demo'),last=max([r.id for r in replies]+[0]))
    @bp.get('')
    @vendor.get('')
    def inbox():return render()
    @bp.get('/<tid>')
    @vendor.get('/<tid>')
    def thread(tid):return render(get(tid))
    @bp.post('/new')
    def new():
        a=g.support_actor;key=nonce();subject=request.form.get('subject','').strip();body=request.form.get('body','').strip();category=request.form.get('category','Technical');priority=request.form.get('priority','Normal');campus=request.form.get('campus','')
        if not 1<=len(subject)<=180 or not 1<=len(body)<=10000 or category not in CATEGORIES or priority not in ('Normal','High','Urgent'):raise ValueError('Enter a subject, details, category and priority within the shown limits.')
        permitted=scopes(app,'support.create')
        if permitted is not None and (campus not in permitted or campus not in (scopes(app,'support.view') or set())):abort(403)
        if campus and campus not in app.extensions['staff_access_helpers']['campuses']():raise ValueError('Choose a configured campus.')
        media=file_inputs();digest=fingerprint(body,media,subject=subject,category=category,priority=priority,campus=campus)
        prior=Ticket.query.filter_by(nonce=key).first()
        if prior:
            if prior.fingerprint!=digest:raise ValueError('This submission was already used with different details.')
            return redirect(route('thread',tid=prior.id))
        if Ticket.query.filter_by(school_id=a['school_id'],actor=a['key']).filter(Ticket.created>time.time()-86400).count()>=10:abort(429,'Ticket limit reached. Reply to an existing ticket or try tomorrow.')
        row=Ticket(id=secrets.token_urlsafe(32),school_id=a['school_id'],school_code=a['school_code'],actor=a['key'],label=a['label'],campus=campus,subject=subject,category=category,priority=priority,nonce=key,fingerprint=digest);db.session.add(row);db.session.flush()
        r=Reply(ticket_id=row.id,sender=a['key'],label=a['label'],human=False,body=body,nonce=hashlib.sha256((key+':first').encode()).hexdigest(),fingerprint=digest);db.session.add(r);db.session.flush()
        for f in media:db.session.add(File(reply_id=r.id,name=f['name'],mime=f['mime'],content=f['content']))
        audit('support-ticket-created',row);db.session.commit();flash('Demo ticket saved privately for this browser; it is not sent to the software owner.' if a['demo'] else 'Support ticket saved in the software owner inbox.','success');return redirect(route('thread',tid=row.id))
    @bp.post('/<tid>/reply')
    @vendor.post('/<tid>/reply')
    def reply(tid):
        row=get(tid);key=nonce();body=request.form.get('body','').strip();state=request.form.get('status',row.status)
        if not 1<=len(body)<=10000 or state not in STATUSES:raise ValueError('Write a reply of up to 10,000 characters and choose a valid status.')
        if not vendor_mode() and state not in ('Open','Resolved',row.status):abort(403)
        media=file_inputs();digest=fingerprint(body,media,ticket=tid,status=state)
        prior=Reply.query.filter_by(nonce=key).first()
        if prior:
            if prior.ticket_id!=row.id or prior.fingerprint!=digest:raise ValueError('This reply token was already used with different details.')
            return redirect(route('thread',tid=row.id))
        if request.form.get('version')!=str(row.version):raise ValueError('This ticket changed. Reload before replying.')
        a=g.support_actor
        if Reply.query.filter_by(ticket_id=tid,sender=a['key']).filter(Reply.created>time.time()-3600).count()>=50:abort(429)
        row.status=state;row.updated=time.time();r=Reply(ticket_id=row.id,sender=a['key'],label=a['label'],human=vendor_mode(),body=body,nonce=key,fingerprint=digest);db.session.add(r);db.session.flush()
        for f in media:db.session.add(File(reply_id=r.id,name=f['name'],mime=f['mime'],content=f['content']))
        audit('support-owner-reply' if vendor_mode() else 'support-school-reply',row);db.session.commit();return redirect(route('thread',tid=row.id))
    @bp.post('/<tid>/read')
    @vendor.post('/<tid>/read')
    def read(tid):
        row=get(tid);raw=request.form.get('last','')
        if not raw.isdigit():raise ValueError('Invalid read position.')
        last=Reply.query.filter(Reply.ticket_id==tid,Reply.id<=int(raw)).order_by(Reply.id.desc()).first()
        if last:
            field='vendor_seen' if vendor_mode() else 'school_seen'
            db.session.execute(update(Ticket).where(Ticket.id==row.id,getattr(Ticket,field)<last.id).values(**{field:last.id}));db.session.commit()
        return '',204
    @bp.get('/<tid>/files/<int:fid>')
    @vendor.get('/<tid>/files/<int:fid>')
    def file(tid,fid):
        row=get(tid);f=db.get_or_404(File,fid);r=db.get_or_404(Reply,f.reply_id)
        if r.ticket_id!=row.id:abort(404)
        response=send_file(io.BytesIO(f.content),mimetype=f.mime,download_name=f.name,as_attachment=True,conditional=True);response.headers['Content-Security-Policy']="default-src 'none'; sandbox";return response
    app.register_blueprint(bp);app.register_blueprint(vendor)
    app.extensions['support_helpers']=dict(actor=actor,query=query)
