"""Recent personal notices derived from authorised saved events, never sample data."""
import time,json
from flask import Blueprint,abort,g,jsonify,request,url_for,render_template
from sqlalchemy import func,or_
from workspace_actor import actor,scopes,csrf

def configure_notices(app,db,Student):
    bp=Blueprint('notices',__name__,url_prefix='/workspace/notifications')
    class State(db.Model):
        __tablename__='personal_notice_state'
        actor=db.Column(db.String(100),primary_key=True)
        source=db.Column(db.String(160),primary_key=True)
        revision=db.Column(db.String(80),nullable=False)
        read_at=db.Column(db.Float,nullable=False,default=time.time)
    app.extensions['notice_model']=State
    def events():
        a=actor(app);result=[];M=app.extensions['message_models'];C=M['conversation'];Msg=M['message'];Seen=M['seen'];message_key='owner:demo' if a['demo'] else a['key'];permitted=scopes(app,'messages.view')
        if (permitted is None or permitted) and message_key not in app.extensions['message_helpers']['config']()['disabled']:
            seen=db.session.query(Seen.conversation_id.label('cid'),Seen.last_id.label('last')).filter(Seen.actor==message_key).subquery()
            q=db.session.query(C.id,C.subject,func.count(Msg.id),func.max(Msg.id)).join(Msg,Msg.conversation_id==C.id).outerjoin(seen,seen.c.cid==C.id).filter(or_(C.first_actor==message_key,C.second_actor==message_key),Msg.actor!=message_key,Msg.blocked==False,Msg.id>func.coalesce(seen.c.last,0))
            if permitted is not None:q=q.filter(C.campus.in_(permitted))
            SD=app.extensions['record_models']['student']
            valid=db.session.query(Student.id).join(SD,SD.student_id==Student.id).filter(Student.status=='Active',SD.data['campus'].as_string()==C.campus).correlate(C)
            q=q.filter(or_(C.student_id.is_(None),C.student_id.in_(valid)))
            for cid,subject,count,last in q.group_by(C.id,C.subject).order_by(func.max(Msg.id).desc()).limit(15).all():result.append(dict(key='message:'+cid,revision=str(last),title='Unread conversation',detail=subject+' · '+str(count)+' unread',url=url_for('messages.thread',cid=cid)))
        S=app.extensions['support_models'];T=S['ticket'];R=S['reply'];permitted=scopes(app,'support.view')
        if not a['demo'] and (permitted is None or permitted):
            q=db.session.query(T.id,T.subject,func.max(R.id)).join(R,R.ticket_id==T.id).filter(T.school_id==a['school_id'],T.actor==a['key'],R.human==True,R.id>T.school_seen)
            if permitted is not None:q=q.filter(T.campus.in_(permitted))
            for tid,subject,last in q.group_by(T.id,T.subject).order_by(func.max(R.id).desc()).limit(10).all():result.append(dict(key='support:'+tid,revision=str(last),title='Software owner replied',detail=subject,url=url_for('support.thread',tid=tid)))
        read=scopes(app,'admissions.view');approve=scopes(app,'admissions.approve')
        allowed=None if read is None else read&(approve or set())
        if allowed is None or allowed:
            D=app.extensions['record_models']['student'];q=db.session.query(Student.id,D.data).outerjoin(D,D.student_id==Student.id).filter(Student.status=='Waiting')
            if allowed is not None:q=q.filter(D.data['campus'].as_string().in_(allowed))
            for sid,data in q.order_by(Student.id.desc()).limit(10).all():result.append(dict(key='admission:'+str(sid),revision='waiting',title='Admission waiting for approval',detail='Student #'+str(sid)+' · '+str((data or {}).get('campus','')),url=url_for('admission_limits.approvals')))
        read=scopes(app,'fees.view');approve=scopes(app,'fees.approve');allowed=None if read is None else read&(approve or set())
        if allowed is None or allowed:
            W=app.extensions['ops_models']['workflow']
            for row in W.query.filter_by(kind='staff-payment-approval',status='Pending').order_by(W.id.desc()).limit(30).all():
                required=set(row.data.get('campuses',[])) or {row.data.get('campus','')}
                if allowed is not None and not required<=allowed:continue
                result.append(dict(key='payment:'+str(row.id),revision=str(row.version) if hasattr(row,'version') else 'pending',title='Payment request pending',detail='Request #'+str(row.id),url=url_for('staff_access.payment_requests')))
                if sum(e['key'].startswith('payment:') for e in result)>=10:break
        states={s.source:s.revision for s in State.query.filter(State.actor==a['key'],State.source.in_([e['key'] for e in result])).all()} if result else {}
        for e in result:e['read']=states.get(e['key'])==e['revision']
        return result[:40]
    @bp.get('/page')
    def page():return render_template('notifications_page.html',title='Notifications')
    @bp.get('')
    def feed():
        data=events();return jsonify(events=data,count=sum(not e['read'] for e in data),limit=40)
    @bp.post('/read')
    def read():
        csrf();app.extensions['admission_capacity']['lock']();a=actor(app);visible=events();key=request.form.get('key','');revision=request.form.get('revision','');raw=request.form.get('items');all_items=raw is not None
        try:displayed=json.loads(raw) if all_items else []
        except (ValueError,TypeError):abort(422)
        if not isinstance(displayed,list) or len(displayed)>40 or any(not isinstance(e,dict) for e in displayed):abort(422)
        selected=[e for e in visible if any(x.get('key')==e['key'] and x.get('revision')==e['revision'] for x in displayed)] if all_items else [e for e in visible if e['key']==key and e['revision']==revision]
        if not all_items and not selected:abort(409,'This notification changed. Refresh it first.')
        for e in selected:
            row=db.session.get(State,(a['key'],e['key']))
            if not row:row=State(actor=a['key'],source=e['key'],revision=e['revision']);db.session.add(row)
            else:row.revision=e['revision'];row.read_at=time.time()
        db.session.commit();return '',204
    @bp.after_request
    def headers(response):response.headers['Cache-Control']='no-store';return response
    app.extensions['notice_events']=events;app.register_blueprint(bp)
