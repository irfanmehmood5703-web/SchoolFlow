"""Parent teacher events, scheduled meetings and actual attendance reports."""
import hmac,secrets
from datetime import date,datetime,timezone
from flask import Blueprint,abort,flash,g,redirect,render_template,request,session,url_for
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import StaleDataError


def configure_ptm(app,db,Student,Employee):
    bp=Blueprint('ptm',__name__,url_prefix='/workspace/general/ptm')
    rm=app.extensions['record_models'];Audit=app.extensions['ops_models']['audit']
    class Event(db.Model):
        __tablename__='ptm_event'
        id=db.Column(db.Integer,primary_key=True)
        campus=db.Column(db.String(160),nullable=False,default='')
        title=db.Column(db.String(180),nullable=False)
        starts=db.Column(db.Date,nullable=False)
        ends=db.Column(db.Date,nullable=False)
        notes=db.Column(db.Text,nullable=False,default='')
        token=db.Column(db.String(64),nullable=False,unique=True)
        version=db.Column(db.Integer,nullable=False,default=1)
        __mapper_args__={'version_id_col':version}
    class Meeting(db.Model):
        __tablename__='ptm_meeting'
        id=db.Column(db.Integer,primary_key=True)
        event_id=db.Column(db.Integer,db.ForeignKey(Event.id),nullable=False,index=True)
        student_id=db.Column(db.Integer,db.ForeignKey(Student.id),nullable=False,index=True)
        employee_id=db.Column(db.Integer,db.ForeignKey(Employee.id),nullable=False)
        campus=db.Column(db.String(160),nullable=False)
        day=db.Column(db.Date,nullable=False)
        time=db.Column(db.String(5),nullable=False)
        status=db.Column(db.String(20),nullable=False,default='Scheduled')
        notes=db.Column(db.Text,nullable=False,default='')
        feedback=db.Column(db.Text,nullable=False,default='')
        token=db.Column(db.String(64),nullable=False,unique=True)
        version=db.Column(db.Integer,nullable=False,default=1)
        teacher_slot=db.Column(db.String(100),unique=True)
        student_slot=db.Column(db.String(100),unique=True)
        __mapper_args__={'version_id_col':version}
    app.extensions['ptm_models']=dict(event=Event,meeting=Meeting)
    def options(category):return sorted({r.value for r in rm['settings'].query.filter_by(category=category).all()})
    def scope(campus):
        allowed=getattr(g,'access_campuses',None)
        if allowed is not None and (campus not in allowed if campus else set(allowed)!=set(app.extensions['staff_access_helpers']['campuses']())):abort(403)
    def text(key,limit=2000,required=False):
        value=request.form.get(key,'').strip()
        if len(value)>limit or (required and not value):raise ValueError('Check '+key+'.')
        return value
    def day(raw):
        try:
            value=date.fromisoformat(raw)
            if value.isoformat()!=raw:raise ValueError()
            return value
        except ValueError:raise ValueError('Choose valid event/meeting dates.')
    def event_query():
        q=Event.query;allowed=getattr(g,'access_campuses',None)
        if allowed is not None and set(allowed)!=set(app.extensions['staff_access_helpers']['campuses']()):q=q.filter(Event.campus.in_(allowed))
        return q
    def selected_event(eid):
        if not str(eid).isdigit():raise ValueError('Choose an event.')
        row=event_query().filter_by(id=int(eid)).first_or_404();scope(row.campus);return row
    def audit(action,row):db.session.add(Audit(action=action,data=dict(id=row.id,campus=row.campus,staff_id=session.get('staff_id'),owner_id=session.get('owner_id'))))
    @bp.before_request
    def protect():
        if request.method=='POST':
            if not request.form.get('_csrf') or not hmac.compare_digest(request.form['_csrf'],session.get('record_csrf','')):abort(400,'Reload the PTM form.')
            app.extensions['admission_capacity']['lock']()
    @bp.errorhandler(ValueError)
    def invalid(e):db.session.rollback();return render_template('operation_error.html',title='Check PTM',error=str(e)),422
    @bp.errorhandler(IntegrityError)
    @bp.errorhandler(StaleDataError)
    def conflict(e):db.session.rollback();return render_template('operation_error.html',title='Check PTM',error='This submission or teacher/student time slot already exists, or a record changed. Reload before saving.'),409
    @bp.route('/events',methods=['GET','POST'])
    def events():
        if request.method=='POST':
            token=text('submission',64,True)
            if len(token)!=43:raise ValueError('Reload this form.')
            old=Event.query.filter_by(token=token).first()
            if old:scope(old.campus);return redirect(url_for('ptm.events'))
            campus=text('campus',160)
            if campus and campus not in options('campus'):raise ValueError('Choose a configured campus.')
            scope(campus);starts=day(request.form.get('starts',''));ends=day(request.form.get('ends',''))
            if ends<starts:raise ValueError('Event end must be on or after its start.')
            row=Event(campus=campus,title=text('title',180,True),starts=starts,ends=ends,notes=text('notes'),token=token)
            db.session.add(row);db.session.flush()
            if request.form.get('event_preferences')=='1':groups['event_config'](row)
            audit('Create PTM event',row);db.session.commit();flash('PTM event saved.','success');return redirect(url_for('ptm.events'))
        rows=event_query().order_by(Event.starts.desc(),Event.id.desc()).all()
        return render_template('ptm.html',title='PTM Events',tab='events',rows=rows,creating=request.args.get('new')=='1',event_configs={c.event_id:c.data for c in app.extensions['ptm_models']['event_config'].query.all()},campuses=options('campus'),submission=secrets.token_urlsafe(32))
    @bp.route('/create',methods=['GET','POST'])
    def create():
        events=event_query().order_by(Event.starts.desc()).all()
        students=app.extensions['record_helpers']['read_many']('student',Student.query.filter_by(status='Active').order_by(Student.name).all())
        employees=Employee.query.filter_by(status='Active').order_by(Employee.name).all()
        if request.method=='POST':
            if request.form.get('scope_mode')=='group':return groups['save']()
            token=text('submission',64,True)
            if len(token)!=43:raise ValueError('Reload this form.')
            old=Meeting.query.filter_by(token=token).first()
            if old:scope(old.campus);return redirect(url_for('ptm.meetings'))
            event=selected_event(request.form.get('event_id',''))
            sid=request.form.get('student_id','');eid=request.form.get('employee_id','')
            if not sid.isdigit() or not eid.isdigit():raise ValueError('Choose a student and teacher.')
            student=next(((s,d) for s,d in students if s.id==int(sid)),None)
            employee=next((e for e in employees if e.id==int(eid)),None)
            if not student or not employee:raise ValueError('Choose an active student and employee in your scope.')
            campus=student[1].get('campus','');scope(campus)
            if not campus or event.campus and event.campus!=campus:raise ValueError('Choose a student from the event campus.')
            ed=rm['employee'].query.filter_by(employee_id=employee.id).first()
            if ed and ed.data.get('campus') and ed.data['campus']!=campus:raise ValueError('Teacher must belong to the meeting campus.')
            meeting_day=day(request.form.get('day',''))
            if not event.starts<=meeting_day<=event.ends:raise ValueError('Meeting date must fall within the event.')
            raw=text('time',5,True)
            try:
                if datetime.strptime(raw,'%H:%M').strftime('%H:%M')!=raw:raise ValueError()
            except ValueError:raise ValueError('Choose a valid meeting time.')
            row=Meeting(event_id=event.id,student_id=student[0].id,employee_id=employee.id,campus=campus,day=meeting_day,time=raw,notes=text('notes'),token=token,teacher_slot=f'{employee.id}:{meeting_day}:{raw}',student_slot=f'{student[0].id}:{meeting_day}:{raw}')
            db.session.add(row);db.session.flush();audit('Schedule PTM meeting',row);db.session.commit();flash('PTM meeting saved. No message was sent.','success');return redirect(url_for('ptm.meetings'))
        return render_template('ptm.html',title='Create PTM',tab='create',events=events,students=students,employees=employees,campuses=options('campus'),submission=secrets.token_urlsafe(32))
    def matching():
        q=Meeting.query
        for key in ('event_id','student_id','employee_id'):
            raw=request.args.get(key,'')
            if raw:
                if not raw.isdigit():raise ValueError('Choose a valid filter.')
                if key=='event_id':selected_event(raw)
                q=q.filter(getattr(Meeting,key)==int(raw))
        campus=request.args.get('campus','')
        if campus:scope(campus);q=q.filter_by(campus=campus)
        status=request.args.get('status','')
        if status:
            if status not in ('Scheduled','Attended','Absent','Cancelled'):raise ValueError('Choose a valid status.')
            q=q.filter_by(status=status)
        if request.args.get('from'):q=q.filter(Meeting.day>=day(request.args['from']))
        if request.args.get('to'):q=q.filter(Meeting.day<=day(request.args['to']))
        p=getattr(g,'staff_principal',None)
        if p and p.data.get('role')=='Teacher':q=q.filter_by(employee_id=p.employee_id)
        return q.order_by(Meeting.day,Meeting.time,Meeting.id).all()
    @bp.get('/meetings')
    def meetings():
        return listing('meetings')
    @bp.get('/reports')
    def reports():
        return listing('reports')
    def listing(tab):
        rows=matching();student_names={s.id:s.name for s in Student.query.all()};teacher_names={e.id:e.name for e in Employee.query.all()};events=event_query().order_by(Event.starts.desc()).all();event_names={e.id:e.title for e in events}
        group_rows=groups['listing']()
        counts={s:sum(r.status==s for r in rows)+sum(e.status==s for group,e,student in group_rows) for s in ('Scheduled','Attended','Absent','Cancelled')}
        if request.args.get('export')=='xlsx':
            from report_exports import report_xlsx
            return report_xlsx(['Event','Student','Teacher','Date','Time','Status','Feedback'],[[event_names.get(r.event_id,''),student_names.get(r.student_id,''),teacher_names.get(r.employee_id,''),str(r.day),r.time,r.status,r.feedback] for r in rows]+[[event_names.get(group.event_id,'Standalone PTM'),student.get('name',''),', '.join(teacher_names.get(t,'') for t in group.data['teachers']),str(group.day),'',e.status,e.feedback] for group,e,student in group_rows],'ptm-meetings')
        return render_template('ptm.html',title='PTM Reports' if tab=='reports' else 'PTM Meetings',tab=tab,rows=rows,group_rows=group_rows,events=events,student_names=student_names,teacher_names=teacher_names,event_names=event_names,counts=counts,campuses=options('campus'))
    @bp.post('/meetings/<int:mid>')
    def update(mid):
        row=db.get_or_404(Meeting,mid);scope(row.campus)
        p=getattr(g,'staff_principal',None)
        if p and p.data.get('role')=='Teacher' and row.employee_id!=p.employee_id:abort(403)
        if request.form.get('version')!=str(row.version):raise ValueError('Meeting changed. Reload first.')
        status=text('status',20,True)
        if status not in ('Scheduled','Attended','Absent','Cancelled'):raise ValueError('Choose a valid meeting status.')
        row.status=status;row.feedback=text('feedback',4000)
        row.teacher_slot=None if status=='Cancelled' else f'{row.employee_id}:{row.day}:{row.time}'
        row.student_slot=None if status=='Cancelled' else f'{row.student_id}:{row.day}:{row.time}'
        audit('Update PTM meeting',row);db.session.commit();flash('Meeting attendance and feedback saved.','success');return redirect(url_for('ptm.meetings',event_id=row.event_id))
    from ptm_groups import configure_ptm_groups
    groups=configure_ptm_groups(app,db,bp,Student,Employee,Event,scope,day,audit)
    app.register_blueprint(bp)
