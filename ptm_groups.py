"""Additive event preferences and class/session/section PTM batches."""
import hashlib,json,re,secrets
from flask import abort,flash,g,jsonify,redirect,render_template,request,session,url_for


def configure_ptm_groups(app,db,bp,Student,Employee,Event,scope,day,audit):
    rm=app.extensions['record_models'];models=app.extensions['ptm_models']
    class EventConfig(db.Model):
        __tablename__='ptm_event_config'
        event_id=db.Column(db.Integer,db.ForeignKey(Event.id),primary_key=True)
        identity_key=db.Column(db.String(64),unique=True,nullable=False)
        data=db.Column(db.JSON,nullable=False)
    class Group(db.Model):
        __tablename__='ptm_group'
        id=db.Column(db.Integer,primary_key=True)
        event_id=db.Column(db.Integer,db.ForeignKey(Event.id),index=True)
        campus=db.Column(db.String(160),nullable=False)
        day=db.Column(db.Date,nullable=False)
        data=db.Column(db.JSON,nullable=False)
        token=db.Column(db.String(43),unique=True,nullable=False)
        fingerprint=db.Column(db.String(64),nullable=False)
        actor=db.Column(db.String(100),nullable=False)
    class Evaluation(db.Model):
        __tablename__='ptm_evaluation'
        id=db.Column(db.Integer,primary_key=True)
        group_id=db.Column(db.Integer,db.ForeignKey(Group.id),nullable=False,index=True)
        student_id=db.Column(db.Integer,db.ForeignKey(Student.id),nullable=False,index=True)
        campus=db.Column(db.String(160),nullable=False)
        status=db.Column(db.String(20),nullable=False,default='Scheduled')
        feedback=db.Column(db.Text,nullable=False,default='')
        version=db.Column(db.Integer,nullable=False,default=1)
        __table_args__=(db.UniqueConstraint('group_id','student_id'),)
        __mapper_args__={'version_id_col':version}
    models.update(event_config=EventConfig,group=Group,evaluation=Evaluation)
    statuses=('Scheduled','Attended','Absent','Cancelled')
    def actor():return 'staff:'+str(session['staff_id']) if session.get('staff_id') else 'owner:'+str(session['owner_id']) if session.get('owner_id') else 'demo'
    def event_config(row):
        from datetime import datetime
        data={k:request.form.get(k,'').strip() for k in ('term','academic_year','feedback_opens','feedback_closes')}
        if not data['academic_year']:raise ValueError('Enter the academic year.')
        if any(len(v)>80 for v in data.values()):raise ValueError('Event preferences are too long.')
        dates=[]
        for key in ('feedback_opens','feedback_closes'):
            value=data[key]
            try:dates.append(datetime.fromisoformat(value) if value else None)
            except ValueError:raise ValueError('Choose valid feedback dates and times.')
            if dates[-1] and dates[-1].tzinfo:raise ValueError('Use local school time for feedback dates.')
        if dates[0] and dates[1] and dates[1]<dates[0]:raise ValueError('Feedback closes before it opens.')
        data.update(notify_parents=request.form.get('notify_parents')=='1',voice_notes=request.form.get('voice_notes')=='1',notification_status='Provider not configured' if request.form.get('notify_parents')=='1' else 'Not requested')
        key=hashlib.sha256(json.dumps([row.title.casefold(),row.campus,data['academic_year']]).encode()).hexdigest()
        db.session.add(EventConfig(event_id=row.id,identity_key=key,data=data))
    def catalogue(campus,cls='',sessions=(),sections=()):
        scope(campus)
        settings=rm['settings'].query.all()
        def values(category):return sorted({r.value for r in settings if r.category==category})
        if campus not in values('campus'):raise ValueError('Choose a configured campus.')
        maps=app.extensions['institute_setup_models']['mapping'].query.filter_by(campus=campus).all()
        classes=values('class_name')
        if maps:classes=[c for c in classes if any(m.class_name==c and m.active for m in maps)]
        if cls and cls not in classes:raise ValueError('Choose a class at this campus.')
        pupils=app.extensions['record_helpers']['read_many']('student',Student.query.filter_by(status='Active').order_by(Student.name,Student.id).all())
        pupils=[(s,d) for s,d in pupils if d.get('campus')==campus and s.class_name==cls]
        session_options=sorted(set(values('academic_session'))|{d.get('academic_session') for s,d in pupils if d.get('academic_session')})
        section_options=sorted({r.value for r in settings if r.category=='section' and (not r.class_name or r.class_name==cls)})
        subjects=sorted({r.value for r in settings if r.category=='subject' and (not r.class_name or r.class_name==cls) and app.extensions['school_settings_helpers']['subject_allowed'](campus,cls,r.value)}) if cls else []
        teachers=[]
        for e,d in app.extensions['record_helpers']['read_many']('employee',Employee.query.filter_by(status='Active').order_by(Employee.name).all()):
            if 'teacher' in (e.role or '').casefold() and d.get('campus')==campus:teachers.append(dict(id=e.id,name=e.name))
        selected=[dict(id=s.id,name=s.name,admission_no=s.admission_no,section=d.get('section',''),session=d.get('academic_session','')) for s,d in pupils if d.get('academic_session') in sessions and d.get('section') in sections]
        return dict(classes=classes,sessions=session_options,sections=section_options,subjects=subjects,teachers=teachers,students=selected,test_types=app.extensions['school_settings_helpers']['exam_types'](campus))
    @bp.get('/options')
    def group_options():
        return jsonify(catalogue(request.args.get('campus',''),request.args.get('class_name',''),request.args.getlist('sessions'),request.args.getlist('sections')))
    def teacher_visible(group):
        p=getattr(g,'staff_principal',None)
        return not p or p.data.get('role')!='Teacher' or p.employee_id in group.data.get('teachers',[])
    def save():
        token=request.form.get('submission','')
        if not re.fullmatch(r'[A-Za-z0-9_-]{43}',token):raise ValueError('Reload this PTM form.')
        campus=request.form.get('campus','');cls=request.form.get('class_name','');sessions=sorted(set(request.form.getlist('sessions')));sections=sorted(set(request.form.getlist('sections')))
        data=catalogue(campus,cls,sessions,sections)
        if not cls or not sessions or not sections or not set(sessions)<=set(data['sessions']) or not set(sections)<=set(data['sections']):raise ValueError('Choose class, sessions and sections.')
        raw=request.form.getlist('students')
        if not raw or len(raw)>500 or any(not x.isdigit() for x in raw):raise ValueError('Select active students for this meeting (up to 500).')
        ids=sorted({int(x) for x in raw});eligible={s['id']:s for s in data['students']}
        if not set(ids)<=set(eligible):raise ValueError('A student no longer belongs to the selected campus, class, sessions and sections.')
        raw=request.form.getlist('teachers')
        if any(not x.isdigit() for x in raw):raise ValueError('Choose active teachers.')
        teachers=sorted({int(x) for x in raw})
        if not set(teachers)<={e['id'] for e in data['teachers']}:raise ValueError('Choose active teachers at this campus.')
        p=getattr(g,'staff_principal',None)
        if p and p.data.get('role')=='Teacher' and p.employee_id not in teachers:abort(403,'Assign yourself when creating a teacher meeting.')
        meeting_day=day(request.form.get('day',''));eid=request.form.get('event_id','');event=None
        if eid:
            if not eid.isdigit():raise ValueError('Choose a PTM event.')
            event=db.get_or_404(Event,int(eid));scope(event.campus)
            if event.campus and event.campus!=campus or not event.starts<=meeting_day<=event.ends:raise ValueError('Meeting campus/date must match the event.')
        criteria={k:request.form.get(k,'').strip() for k in ('test_type','exam_from','exam_to')};criteria['subjects']=sorted(set(request.form.getlist('subjects')))
        if criteria['test_type'] and criteria['test_type'] not in data['test_types'] or not set(criteria['subjects'])<=set(data['subjects']):raise ValueError('Choose valid evaluation filters.')
        for key in ('exam_from','exam_to'):
            if criteria[key]:day(criteria[key])
        if criteria['exam_from'] and criteria['exam_to'] and criteria['exam_to']<criteria['exam_from']:raise ValueError('Exam end precedes exam start.')
        notes=request.form.get('notes','').strip()
        if len(notes)>4000:raise ValueError('Notes may contain up to 4,000 characters.')
        payload=dict(class_name=cls,sessions=sessions,sections=sections,teachers=teachers,students=ids,criteria=criteria,notes=notes)
        fingerprint=hashlib.sha256(json.dumps([campus,meeting_day.isoformat(),event.id if event else None,payload],sort_keys=True).encode()).hexdigest()
        old=Group.query.filter_by(token=token).first()
        if old:
            if old.actor!=actor() or old.fingerprint!=fingerprint:raise ValueError('This submission was saved with different details.')
            return redirect(url_for('ptm.meetings'))
        snapshots=[]
        if any(criteria.values()):
            if p and campus not in app.extensions['staff_access_helpers']['grant'](p,'exam.view'):abort(403,'Exam access is required to include marks.')
            for award in app.extensions['ops_models']['workflow'].query.filter_by(kind='awards').all():
                if award.data.get('campus')!=campus or award.data.get('class_name')!=cls:continue
                papers=[i for i,paper in enumerate(award.data.get('papers',[])) if (not criteria['test_type'] or paper.get('type')==criteria['test_type']) and (not criteria['exam_from'] or paper.get('date','')>=criteria['exam_from']) and (not criteria['exam_to'] or paper.get('date','')<=criteria['exam_to']) and (not criteria['subjects'] or paper.get('subject') in criteria['subjects'])]
                if not papers:continue
                for result in app.extensions['school_settings_helpers']['result_rows'](award):
                    if result['student'].id not in ids:continue
                    for i in papers:
                        r=result['papers'][i]
                        if r.get('excluded'):continue
                        snapshots.append(dict(student_id=result['student'].id,exam=award.data.get('name',''),subject=r['paper']['subject'],date=r['paper'].get('date',''),obtained=str(r['obtained']) if r['obtained'] is not None else '',total=str(r['total']),state=r['state'],grade=r['grade'],marked=r['marked']))
        payload.update(roster=[eligible[i] for i in ids],marks=snapshots)
        group=Group(event_id=event.id if event else None,campus=campus,day=meeting_day,data=payload,token=token,fingerprint=fingerprint,actor=actor());db.session.add(group);db.session.flush()
        for sid in ids:db.session.add(Evaluation(group_id=group.id,student_id=sid,campus=campus))
        audit('Create class PTM',group);db.session.commit();flash('PTM saved for '+str(len(ids))+' students.','success');return redirect(url_for('ptm.meetings'))
    def listing():
        result=[]
        for group in Group.query.order_by(Group.day,Group.id).all():
            scope(group.campus)
            if not teacher_visible(group):continue
            if request.args.get('event_id') and str(group.event_id)!=request.args['event_id']:continue
            if request.args.get('campus') and group.campus!=request.args['campus']:continue
            if request.args.get('from') and group.day<day(request.args['from']):continue
            if request.args.get('to') and group.day>day(request.args['to']):continue
            if request.args.get('employee_id') and int(request.args['employee_id']) not in group.data['teachers']:continue
            for evaluation in Evaluation.query.filter_by(group_id=group.id).all():
                if request.args.get('status') and evaluation.status!=request.args['status']:continue
                if request.args.get('student_id') and str(evaluation.student_id)!=request.args['student_id']:continue
                result.append((group,evaluation,next((s for s in group.data['roster'] if s['id']==evaluation.student_id),{})))
        return result
    @bp.post('/evaluations/<int:mid>')
    def update_group(mid):
        row=db.get_or_404(Evaluation,mid);group=db.get_or_404(Group,row.group_id);scope(group.campus)
        if not teacher_visible(group):abort(403)
        if request.form.get('version')!=str(row.version):raise ValueError('Meeting changed. Reload before saving.')
        status=request.form.get('status');feedback=request.form.get('feedback','').strip()
        if status not in statuses or len(feedback)>4000:raise ValueError('Choose a valid status and feedback (up to 4,000 characters).')
        row.status=status;row.feedback=feedback;audit('Update class PTM evaluation',group);db.session.commit();flash('PTM attendance and feedback saved.','success');return redirect(url_for('ptm.meetings'))
    return dict(event_config=event_config,save=save,listing=listing,teacher_visible=teacher_visible)
