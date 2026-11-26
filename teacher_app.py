"""Assigned-class Teacher App with role-based, assignment-scoped capabilities."""
import calendar,hashlib,hmac,io,json,re,secrets
from types import SimpleNamespace
from datetime import date,datetime,timedelta
from decimal import Decimal,InvalidOperation
from flask import Blueprint,abort,flash,g,redirect,render_template,request,send_file,session,url_for
from itsdangerous import URLSafeTimedSerializer,BadData
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import StaleDataError
from school_clock import school_today,SCHOOL_TIMEZONE
from exam_enrollment import enrolled
from diary_work import clean_work,plain_work

STUDY={'learning':'Learning','notes':'Student Notes','assignments':'Assignments','vacation':'Vacation Work'}

def configure_teacher_app(app,db,Student,Employee):
    bp=Blueprint('teacher_app',__name__,url_prefix='/teacher-app');rm=app.extensions['record_models'];ops=app.extensions['ops_models'];W=ops['workflow'];Daily=ops['daily'];Audit=ops['audit'];sh=app.extensions['staff_access_helpers']
    class Submission(db.Model):
        __tablename__='teacher_app_submission'
        token=db.Column(db.String(43),primary_key=True)
        staff_id=db.Column(db.Integer,nullable=False)
        kind=db.Column(db.String(30),nullable=False)
        digest=db.Column(db.String(64),nullable=False)
        target_id=db.Column(db.Integer)
    app.extensions['teacher_app_models']=dict(submission=Submission)
    def grants(permission):return sh['teacher_app_grant'](g.staff_principal,permission)
    @bp.before_request
    def guard():
        p=getattr(g,'staff_principal',None)
        if not p or p.data.get('role')!='Teacher' or not getattr(g,'school_identity',{}).get('scope'):abort(403,'Sign in with an active teacher account supplied by this school.')
        if not app.extensions['mobile_client_helpers']['role_allowed']('teacher'):abort(403)
        if request.method=='POST':
            if not session.get('record_csrf') or not hmac.compare_digest(request.form.get('_csrf',''),session['record_csrf']):abort(400)
            app.extensions['admission_capacity']['lock']();db.session.refresh(p)
            if not sh['resolve'](p.id,session.get('staff_version')) or p.data.get('role')!='Teacher':abort(403)
        g.teacher_employee=db.get_or_404(Employee,p.employee_id)
    @bp.errorhandler(ValueError)
    def invalid(e):db.session.rollback();return render('error',error=str(e)),422
    @bp.errorhandler(IntegrityError)
    @bp.errorhandler(StaleDataError)
    def changed(e):db.session.rollback();return render('error',error='Another request changed these records. Reload before saving again.'),409
    def cohorts(permission=None):
        permitted=grants(permission) if permission else set(g.staff_principal.data.get('campuses',[]))&set(sh['campuses']())
        return [r for r in W.query.filter_by(kind='teacher-classes',status='Active').order_by(W.id).all() if str(r.data.get('employee_id'))==str(g.teacher_employee.id) and r.data.get('campus') in permitted and all(r.data.get(k) for k in ('class_name','section'))]
    def subject_choices(row):
        if row.data.get('subject'):return [row.data['subject']]
        cls=row.data['class_name'];campus=row.data['campus'];allowed=app.extensions['school_settings_helpers']['subject_allowed']
        return sorted({r.value for r in rm['settings'].query.filter_by(category='subject').all() if (not r.class_name or r.class_name==cls) and allowed(campus,cls,r.value)},key=str.casefold)
    def subject_cohort(row,subject):
        return SimpleNamespace(id=row.id,data={**row.data,'subject':subject})
    def cohort(cid,permission=None,subject_required=False):
        row=next((r for r in cohorts(permission) if r.id==cid),None)
        if not row:abort(403,'This class or action is not assigned to your teacher account.')
        if subject_required:
            subject=request.args.get('subject','')
            if row.data.get('subject'):
                if subject and subject!=row.data['subject']:abort(403,'This subject is not assigned.')
            else:
                if not subject or subject not in subject_choices(row):abort(403,'Choose a configured subject from your assigned class.')
                g.teacher_subject=(cid,subject)
                return subject_cohort(row,subject)
        return row
    @bp.url_defaults
    def subject_urls(endpoint,values):
        selected=getattr(g,'teacher_subject',None)
        if selected and values.get('cid')==selected[0] and endpoint in ('teacher_app.diary','teacher_app.diary_file','teacher_app.materials','teacher_app.study_file','teacher_app.exam_list','teacher_app.create_exam','teacher_app.marks'):
            values.setdefault('subject',selected[1])
    @bp.get('/classes/<int:cid>/subjects/<feature>')
    def subjects(cid,feature):
        features={'diary':('student_extras.view','Class Diary'),'materials':('student_extras.view','Study Material'),'exam_list':('exam.view','Exam Marks')}
        if feature not in features:abort(404)
        code,label=features[feature];row=cohort(cid,code)
        return render('subjects',cohort=row,subjects=subject_choices(row),feature=feature,feature_label=label,kind=request.args.get('kind',''))
    def roster(c,subject=True):
        D=rm['student'];q=Student.query.join(D,D.student_id==Student.id).filter(Student.status=='Active',Student.class_name==c.data['class_name'],D.data['campus'].as_string()==c.data['campus'],D.data['section'].as_string()==c.data['section'])
        rows=app.extensions['record_helpers']['read_many']('student',q.order_by(Student.name,Student.id).all())
        return [(s,d) for s,d in rows if not subject or not c.data.get('subject') or not d.get('subjects') or c.data['subject'] in d['subjects']]
    def parse_day(raw):
        try:return date.fromisoformat(raw)
        except (ValueError,TypeError):raise ValueError('Choose a valid date.')
    def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,default=str).encode()).hexdigest()
    def review(kind,target,source):
        actor=[g.school_identity['scope'],g.staff_principal.id,g.staff_principal.version,session['record_csrf']];stamp=digest(source);signer=URLSafeTimedSerializer(app.config['SECRET_KEY'],salt='teacher-review-v1')
        if request.method=='POST':
            try:body=signer.loads(request.form.get('review',''),max_age=8*3600)
            except BadData:raise ValueError('This form expired. Reload before saving.')
            if not isinstance(body,dict) or body.get('actor')!=actor or body.get('kind')!=kind or body.get('target')!=target or body.get('stamp')!=stamp:raise ValueError('The assignment, roster or saved records changed. Reload; nothing was saved.')
            token=body.get('nonce','')
            if not re.fullmatch(r'[A-Za-z0-9_-]{43}',token):abort(422)
            if db.session.get(Submission,token):abort(409,'This form was already saved.')
            db.session.add(Submission(token=token,staff_id=g.staff_principal.id,kind=kind,digest=stamp));return None
        return signer.dumps(dict(actor=actor,kind=kind,target=target,stamp=stamp,nonce=secrets.token_urlsafe(32)))
    def extra_ids(prefixes,ids):
        for key in request.form:
            for prefix in prefixes:
                if key.startswith(prefix) and key[len(prefix):] not in {str(n) for n in ids}:abort(403,'A student outside this class was submitted.')
    def audit(action,c=None,**values):db.session.add(Audit(action=action,data=dict(staff_id=g.staff_principal.id,employee_id=g.teacher_employee.id,campus=c.data['campus'] if c else '',**values)))
    def render(view,**values):return render_template('teacher_app.html',view=view,title={'home':'Teacher Home','classes':'My Classes','timetable':'Class Timetable','attendance':'Class Attendance','diary':'Class Diary','materials':'Study Material','marks':'Exam Marks','meetings':'PTM Meetings','profile':'My Profile','error':'Check this form','self':'My Records','tool':'Teacher workspace'}.get(view,view.title()),**values)
    @bp.context_processor
    def context():
        return dict(teacher=g.teacher_employee,teacher_account=g.staff_principal,teacher_today=school_today(),teacher_classes=cohorts(),teacher_periods=app.extensions['automatic_report_helpers']['teacher_periods'](cohorts()) if request.endpoint in ('teacher_app.home','teacher_app.reminders') else [],teacher_can=lambda code,campus:campus in grants(code),teacher_token=secrets.token_urlsafe(32),teacher_study=STUDY,timedelta=timedelta,teacher_own=own_access,teacher_money=lambda n:'Rs '+f'{n/100:,.2f}')
    @bp.get('')
    def home():
        classes=cohorts();today=school_today();details=[]
        for c in classes:
            rows=roster(c,False);ids=[s.id for s,d in rows];marked=Daily.query.filter_by(kind='student',day=today).filter(Daily.person_id.in_(ids)).count() if c.data['campus'] in grants('attendance.view') else None
            details.append(dict(row=c,count=len(rows),marked=marked))
        return render('home',cards=details)
    def period_notice(row,day):
        return dict(key='period:'+row['campus']+':'+row['class_name']+':'+row['section']+':'+row['subject']+':'+row['time'],revision=str(day),title='Upcoming period',detail=row['subject']+' · '+row['class_name']+' / '+row['section']+' · '+row['time_label'])
    def teacher_notification_events():
        events=list(app.extensions['notice_events']())
        for row in app.extensions['automatic_report_helpers']['teacher_periods'](cohorts()):
            if row['due']:
                events.append(period_notice(row,school_today()))
        if own_access('attendance.own','attendance.view','attendance.self'):
            for row in Daily.query.filter_by(kind='staff',person_id=g.teacher_employee.id).order_by(Daily.day.desc()).limit(5):
                events.append(dict(key='attendance:'+str(row.id),revision=digest([row.status,row.time_in,row.time_out]),title='Your attendance',detail=str(row.day)+' · '+row.status))
        if own_access('payroll.self','payroll.view'):
            for row in ops['salary'].query.filter_by(employee_id=g.teacher_employee.id).order_by(ops['salary'].month.desc()).limit(3):
                events.append(dict(key='salary:'+str(row.id),revision=str(row.version),title='Salary record updated',detail=row.month+' · '+('Paid' if row.paid else 'Review salary record')))
        if own_access('hrm.self_requests'):
            for row in W.query.filter(W.kind.in_(['advances','leave-approvals']),W.data['employee_id'].as_string()==str(g.teacher_employee.id)).order_by(W.id.desc()).limit(10):
                events.append(dict(key='request:'+str(row.id),revision=row.status,title='Your request · '+row.status,detail='Advance salary' if row.kind=='advances' else 'Leave request'))
        return events
    @bp.get('/notifications')
    def notifications():return render('notifications',events=teacher_notification_events())
    @bp.get('/notification-feed')
    def native_notification_feed():
        from mobile_notices import feed
        alerts=app.extensions['automatic_report_helpers']['teacher_lecture_alerts'](cohorts())
        notices=[dict(period_notice(row,row['day']),due_at=row['due_at'],starts_at=row['starts_at']) for row in alerts]
        return feed('teacher',g.school_identity['scope'],g.staff_principal.id,teacher_notification_events(),lecture_alerts=notices)
    @bp.get('/classes')
    def classes():return render('classes')
    @bp.get('/timetable')
    def timetable():
        periods=app.extensions['automatic_report_helpers']['teacher_timetable'](cohorts())
        days=[dict(name=name,today=index==school_today().weekday(),periods=[p for p in periods if p['weekday']==index]) for index,name in enumerate(calendar.day_name)]
        full_class_count=sum(p['mode']=='full-class' for p in periods)
        return render('timetable',days=days,period_count=len(periods)-full_class_count,full_class_count=full_class_count,schedule_count=len(periods))

    @bp.route('/classes/<int:cid>/attendance',methods=['GET','POST'])
    def attendance(cid):
        c=cohort(cid,'attendance.update' if request.method=='POST' else 'attendance.view');day=parse_day(request.values.get('day',str(school_today())))
        if day>school_today():raise ValueError('Future attendance cannot be marked.')
        rows=roster(c,False);ids=[s.id for s,d in rows];existing={r.person_id:r for r in Daily.query.filter_by(kind='student',day=day).filter(Daily.person_id.in_(ids)).all()}
        token=review('attendance',cid,dict(assignment=c.data,day=day,roster=[(s.id,s.name,d.get('roll_no')) for s,d in rows],saved=[(k,r.status,r.time_in,r.time_out,r.lectures) for k,r in sorted(existing.items())]));statuses=app.extensions['attendance_control_helpers']['statuses']('student')
        if request.method=='POST':
            extra_ids(['status_'],ids);count=0
            for s,d in rows:
                status=request.form.get('status_'+str(s.id),'')
                if not status:continue
                old=existing.get(s.id)
                if status not in statuses or not app.extensions['attendance_control_helpers']['allowed']('student',status,old.status if old else None):raise ValueError('A selected attendance status is disabled or invalid.')
                if not old:old=Daily(kind='student',person_id=s.id,day=day);db.session.add(old)
                if old.status==status:continue
                old.status=status;app.extensions['attendance_device_helpers']['manual_write'](old);count+=1
            audit('Teacher saved class attendance',c,day=str(day),count=count);db.session.commit();flash('Attendance saved.','success');return redirect(url_for('teacher_app.attendance',cid=cid,day=day))
        return render('attendance',cohort=c,rows=rows,existing=existing,day=day,statuses=statuses,review_token=token)
    @bp.route('/classes/<int:cid>/diary',methods=['GET','POST'])
    def diary(cid):
        c=cohort(cid,('student_extras.update' if request.form.get('action')=='update' else 'student_extras.create') if request.method=='POST' else 'student_extras.view',subject_required=True);E=app.extensions['student_extras_models']['entry']
        if request.method=='POST':
            if parse_day(request.form.get('starts'))!=school_today():raise ValueError('Previous diaries are read-only. Choose today to write a diary.')
            if any(request.form.get(k)!=str(c.data[k]) for k in ('campus','class_name','section')) or request.form.getlist('subjects')!=[c.data['subject']] or request.form.get('subject_name_0')!=c.data['subject'] or request.form.getlist('subject_slot')!=['0'] or request.form.get('action') not in ('save','update') or request.form.get('channel')!='app':abort(403)
            if request.form.get('action')=='update':
                row=db.get_or_404(E,request.form.get('entry',type=int));ids={eid for sub in app.extensions['student_extras_models']['submission'].query.filter_by(actor='staff:'+str(g.staff_principal.id)).all() for eid in sub.entry_ids}
                if row.id not in ids or row.kind!='diary' or row.starts!=school_today() or row.campus!=c.data['campus'] or any(row.data.get(k)!=c.data[k] for k in ('class_name','section','subject')):abort(403,'Only your own subject diary for today can be edited.')
                review('diary-update',row.id,[row.body,row.data,c.data]);data=dict(row.data);size=0;count=0
                for part in ('classwork','homework'):
                    data[part]=clean_work(request.form.get(part+'_0',''));data[part+'_attachments']=list(data.get(part+'_attachments',[]))
                    for name,mime,content in app.extensions['student_extra_uploads'](part+'_files_0'):
                        size+=len(content);count+=1
                        if size>15*1024*1024 or count>20:raise ValueError('Use up to twenty new files and 15 MB combined.')
                        file=app.extensions['student_extras_models']['attachment'](entry_id=row.id,filename=name,mime=mime,content=content);db.session.add(file);db.session.flush();data[part+'_attachments'].append(file.id)
                if not any(plain_work(data[part]) or data[part+'_attachments'] for part in ('classwork','homework')):raise ValueError('Enter classwork, homework or an attachment.')
                row.data=data;row.body='Classwork: '+plain_work(data['classwork'])+'\nHomework: '+plain_work(data['homework']);audit('Teacher updated own subject diary',c,entry_id=row.id);db.session.commit();flash('Today’s subject diary updated.','success');return redirect(url_for('teacher_app.diary',cid=cid))
            def choices(key):return [c.data[key]] if key in c.data else []
            def scope_ok(campus):
                if campus!=c.data['campus']:abort(403)
            app.extensions['diary_work_helpers']['save'](choices,scope_ok,parse_day,app.extensions['student_extra_uploads'])
            return redirect(url_for('teacher_app.diary',cid=cid))
        entries=E.query.filter_by(kind='diary',campus=c.data['campus']).order_by(E.starts.desc(),E.id.desc()).limit(300).all();entries=[e for e in entries if all(e.data.get(k)==c.data[k] for k in ('class_name','section','subject'))]
        own_ids={eid for sub in app.extensions['student_extras_models']['submission'].query.filter_by(actor='staff:'+str(g.staff_principal.id)).all() for eid in sub.entry_ids};editing=next((r for r in entries if r.id in own_ids and r.starts==school_today()),None)
        return render('diary',cohort=c,entries=entries,editing=editing,diary_writable=request.args.get('day',str(school_today()))==str(school_today()),diary_review=review('diary-update',editing.id,[editing.body,editing.data,c.data]) if editing else '')
    @bp.get('/classes/<int:cid>/diary/<int:eid>/files/<int:fid>')
    def diary_file(cid,eid,fid):
        c=cohort(cid,'student_extras.view',subject_required=True);M=app.extensions['student_extras_models'];e=db.get_or_404(M['entry'],eid)
        if e.kind!='diary' or e.campus!=c.data['campus'] or any(e.data.get(k)!=c.data[k] for k in ('class_name','section','subject')):abort(404)
        f=M['attachment'].query.filter_by(id=fid,entry_id=eid).first_or_404();return attachment(f)
    def attachment(f):
        response=send_file(io.BytesIO(f.content),mimetype=f.mime,download_name=f.filename,as_attachment=True);response.headers['Content-Security-Policy']="default-src 'none'; sandbox";return response
    def study_item(c,i):
        M=app.extensions['parent_study_models'];r=db.get_or_404(M['item'],i)
        if r.kind not in STUDY or r.campus!=c.data['campus'] or r.class_name!=c.data['class_name'] or r.section not in ('',c.data['section']) or r.subject!=c.data['subject']:abort(404)
        return r
    @bp.route('/classes/<int:cid>/materials',methods=['GET','POST'])
    def materials(cid):
        c=cohort(cid,'student_extras.view' if request.method=='GET' else 'student_extras.create' if request.form.get('action')=='create' else 'student_extras.update',subject_required=True);M=app.extensions['parent_study_models']
        if request.method=='POST':
            action=request.form.get('action')
            if action=='create':
                kind=request.form.get('kind','');title=request.form.get('title','').strip();body=clean_work(request.form.get('body',''));start=parse_day(request.form.get('starts',''));end=parse_day(request.form.get('ends',''));due=parse_day(request.form['due']) if request.form.get('due') else None;token=request.form.get('token','')
                if kind not in STUDY or not 1<=len(title)<=180 or end<start or (end-start).days>1096 or due and not start<=due<=end or not re.fullmatch(r'[A-Za-z0-9_-]{43}',token):raise ValueError('Check the resource title, type, dates and deadline.')
                files=app.extensions['student_extra_uploads']();published=request.form.get('published')=='1'
                if published and c.data['campus'] not in grants('student_extras.update'):abort(403)
                value=dict(assignment=c.data,kind=kind,title=title,body=body,starts=str(start),ends=str(end),due=str(due),published=published,files=[(n,m,hashlib.sha256(b).hexdigest()) for n,m,b in files]);stamp=digest(value);old=M['item'].query.filter_by(token=token).first()
                if old:
                    if old.data.get('teacher_id')!=g.staff_principal.id or old.data.get('submission_digest')!=stamp:abort(409)
                    return redirect(url_for('teacher_app.materials',cid=cid))
                row=M['item'](kind=kind,title=title,body=body,campus=c.data['campus'],class_name=c.data['class_name'],section=c.data['section'],subject=c.data['subject'],starts=start,ends=end,due=due,published=published,token=token,data=dict(teacher_id=g.staff_principal.id,submission_digest=stamp));db.session.add(row);db.session.flush()
                for n,m,b in files:db.session.add(M['file'](item_id=row.id,filename=n,mime=m,content=b))
                audit('Teacher created study resource',c,item_id=row.id,published=published)
            elif action in ('toggle','grade'):
                row=study_item(c,request.form.get('item',type=int))
                if action=='toggle':
                    if row.data.get('teacher_id')!=g.staff_principal.id:abort(403,'Only the author can change publication visibility.')
                    if request.form.get('version')!=str(row.version):abort(409)
                    row.published=not row.published;audit('Teacher changed resource visibility',c,item_id=row.id,published=row.published)
                else:
                    sub=M['submission'].query.filter_by(id=request.form.get('submission',type=int),item_id=row.id).first_or_404()
                    if sub.student_id not in {s.id for s,d in roster(c)}:abort(403)
                    if request.form.get('version')!=str(sub.version):abort(409)
                    marks=request.form.get('marks','').strip();feedback=request.form.get('feedback','').strip()
                    if len(marks)>40 or len(feedback)>2000:raise ValueError('Marks or feedback are too long.')
                    sub.marks=marks;sub.feedback=feedback;audit('Teacher graded assignment response',c,submission_id=sub.id,student_id=sub.student_id)
            else:abort(422)
            db.session.commit();flash('Study material saved. Published items appear in the Parent App.','success');return redirect(url_for('teacher_app.materials',cid=cid))
        items=M['item'].query.filter_by(campus=c.data['campus'],class_name=c.data['class_name'],subject=c.data['subject']).filter(M['item'].section.in_(['',c.data['section']]),M['item'].kind.in_(list(STUDY))).order_by(M['item'].id.desc()).limit(100).all();ids=[i.id for i in items];pupils={s.id:s for s,d in roster(c)}
        return render('materials',cohort=c,items=items,pupils=pupils,files={i.id:M['file'].query.filter_by(item_id=i.id).all() for i in items},responses=M['submission'].query.filter(M['submission'].item_id.in_(ids),M['submission'].student_id.in_(pupils)).order_by(M['submission'].id.desc()).limit(100).all())
    @bp.get('/classes/<int:cid>/materials/<int:iid>/files/<int:fid>')
    def study_file(cid,iid,fid):
        c=cohort(cid,'student_extras.view',subject_required=True);study_item(c,iid);f=app.extensions['parent_study_models']['file'].query.filter_by(id=fid,item_id=iid).first_or_404();return attachment(f)
    def exam_rows(c,award):
        rows=[(s,d) for s,d in roster(c,False) if all(not award.data.get(k) or d.get(k)==award.data[k] for k in ('section','gender','group_name','academic_session'))]
        def roll(pair):
            student,data=pair;value=str(data.get('roll_no','')).strip();return (not bool(value),0 if value.isdigit() else 1,int(value) if value.isdigit() else value.casefold(),student.id)
        rows.sort(key=roll if award.data.get('sort_order')=='roll' else (lambda pair:pair[0].id))
        return rows
    def exams(c):
        out=[]
        for a in W.query.filter_by(kind='awards',status='Active').order_by(W.id.desc()).all():
            if a.data.get('campus')!=c.data['campus'] or a.data.get('class_name')!=c.data['class_name'] or a.data.get('section') not in ('',None,c.data['section']):continue
            for i,p in enumerate(a.data.get('papers',[])):
                if p.get('subject')==c.data['subject'] and str(p.get('teacher') or g.teacher_employee.id)==str(g.teacher_employee.id):out.append((a,i,p))
        return out
    @bp.route('/classes/<int:cid>/exams/new',methods=['GET','POST'])
    def create_exam(cid):
        c=cohort(cid,'exam.create',subject_required=True);rows=roster(c,False);catalog={k:sorted({d.get(k) for s,d in rows if d.get(k)}) for k in ('gender','group_name','academic_session')};settings=app.extensions['school_settings_helpers'];config=settings['subject_config'](c.data['subject']);grading=config.get('grading','Marks');token=review('new-exam',cid,dict(assignment=c.data,catalog=catalog,config=config))
        if request.method=='POST':
            name=request.form.get('name','').strip();day=parse_day(request.form.get('exam_date'));returned=parse_day(request.form.get('return_date'));typ=request.form.get('test_type');sort=request.form.get('sort_order');filtering=request.form.get('student_filter')
            if not 1<=len(name)<=180 or typ not in ('Written','Oral','Practical') or sort not in ('sid','roll','section') or filtering not in ('class','subject') or returned<day:raise ValueError('Check exam name, dates, assessment type and sorting.')
            selection={k:request.form.get(k,'') for k in catalog}
            if any(value and value not in catalog[k] for k,value in selection.items()):raise ValueError('Choose values present in this assigned class.')
            maximum=Decimal(0)
            if grading=='Marks':
                try:maximum=Decimal(request.form.get('total',''))
                except InvalidOperation:raise ValueError('Enter the numeric paper total.')
                if not maximum.is_finite() or not 0<maximum<=10000:raise ValueError('Total marks must be positive and at most 10,000.')
            if W.query.filter(W.kind=='awards',W.data['name'].as_string()==name).first():raise ValueError('An award list already uses this name. Choose a unique name.')
            data=dict(name=name,print_heading=name,campus=c.data['campus'],class_name=c.data['class_name'],section=c.data['section'],return_date=str(returned),sort_order=sort,student_filter=filtering,recheck=request.form.get('recheck')=='1',**selection,papers=[dict(subject=c.data['subject'],grading=grading,subject_group=config.get('group',''),date=str(day),type=typ,total=float(maximum),teacher=str(g.teacher_employee.id),time='',syllabus='')])
            row=W(kind='awards',status='Active',data=data);db.session.add(row);audit('Teacher created assigned subject award list',c);db.session.commit();return redirect(url_for('teacher_app.exam_list',cid=cid))
        return render('create_exam',cohort=c,catalog=catalog,grading=grading,review_token=token)

    @bp.get('/classes/<int:cid>/exams')
    def exam_list(cid):
        c=cohort(cid,'exam.view',subject_required=True);q=request.args.get('q','').strip()[:120].casefold();rows=[r for r in exams(c) if not q or q in (' '.join([str(r[0].id),str(r[0].data.get('name','')),c.data['class_name'],r[2]['subject']])).casefold()]
        return render('exams',cohort=c,exams=rows,search=request.args.get('q','')[:120])
    @bp.route('/classes/<int:cid>/marks/<int:aid>/<int:paper>',methods=['GET','POST'])
    def marks(cid,aid,paper):
        c=cohort(cid,'exam.update' if request.method=='POST' else 'exam.view',subject_required=True);selected=next(((a,i,p) for a,i,p in exams(c) if a.id==aid and i==paper),None)
        if not selected:abort(403,'This exam subject is not assigned to you.')
        a,i,p=selected
        if request.method=='POST':app.extensions['admission_capacity']['lock']()
        release_model=app.extensions.get('parent_exam_release_model')
        release=db.session.get(release_model,aid) if release_model is not None else None
        published=bool(release and release.published)
        if published and request.method=='POST':abort(403,'Published results are locked. Contact the school owner.')
        rows=[(s,d) for s,d in exam_rows(c,a) if enrolled(a,p,d)];ids=[s.id for s,d in rows];numeric=p.get('grading','Marks')=='Marks';Model=ops['score'] if numeric else ops['qualitative'];saved={r.student_id:r for r in Model.query.filter_by(award_id=aid,paper=i).filter(Model.student_id.in_(ids)).all()};direct=app.extensions['school_settings_helpers']['direct_choices'](c.data['campus'],c.data['class_name'])
        snapshot=dict(publication_version=release.version if release else 0,published=published,assignment=c.data,award=a.data,roster=[(s.id,s.name,d.get('roll_no')) for s,d in rows],grading=direct,saved=[(sid,r.obtained if numeric else r.value,r.state,'' if numeric else r.remarks) for sid,r in sorted(saved.items())]);token=review('marks',str(cid)+':'+str(aid)+':'+str(i),snapshot)
        if request.method=='POST':
            extra_ids(['mark_','state_'],ids)
            for s,d in rows:
                if not any(k+str(s.id) in request.form for k in ('mark_','state_')):continue
                state=request.form.get('state_'+str(s.id),'');value=request.form.get('mark_'+str(s.id),'').strip()
                if state not in ('','A','L'):raise ValueError('Invalid paper attendance.')
                row=saved.get(s.id)
                if numeric:
                    try:n=Decimal(value) if value else None;maximum=Decimal(str(p['total']))
                    except (InvalidOperation,KeyError):raise ValueError('Enter valid marks.')
                    if n is not None and (not n.is_finite() or not 0<=n<=maximum):raise ValueError('Marks must be within the saved paper total.')
                    if not row:row=Model(award_id=aid,student_id=s.id,paper=i);db.session.add(row)
                    row.obtained=None if state or n is None else float(n)
                else:
                    mode=p.get('grading');permitted={'0','1'} if mode=='Checkbox' else set(direct) if mode=='Direct Grading' else set()
                    if value and value not in permitted and (not row or value!=row.value):raise ValueError('Choose a configured grade.')
                    if not row:row=Model(award_id=aid,student_id=s.id,paper=i);db.session.add(row)
                    row.value=None if state else value or None;row.remarks=direct.get(value,'') if mode=='Direct Grading' else ''
                row.state=state
            audit('Teacher saved subject marks',c,award_id=aid,paper=i);db.session.commit();flash('Marks saved. Parent report publication remains with the school.','success');return redirect(url_for('teacher_app.marks',cid=cid,aid=aid,paper=i))
        return render('marks',cohort=c,award=a,paper=p,paper_index=i,rows=rows,saved=saved,numeric=numeric,direct=direct,review_token=token,published=published)
    @bp.route('/meetings',methods=['GET','POST'])
    def meetings():
        M=app.extensions['ptm_models'];allowed=grants('ptm.update' if request.method=='POST' else 'ptm.view');query=M['meeting'].query.filter_by(employee_id=g.teacher_employee.id).filter(M['meeting'].campus.in_(allowed))
        if request.method=='POST':
            row=query.filter_by(id=request.form.get('id',type=int)).first_or_404();status=request.form.get('status');notes=request.form.get('notes','').strip()
            if request.form.get('version')!=str(row.version):abort(409)
            if status not in ('Scheduled','In Progress','Completed','Cancelled') or len(notes)>4000:raise ValueError('Check meeting status and notes.')
            row.status=status;row.notes=notes;audit('Teacher updated own PTM',meeting_id=row.id);db.session.commit();return redirect(url_for('teacher_app.meetings'))
        return render('meetings',meetings=query.order_by(M['meeting'].day.desc()).limit(100).all(),events={r.id:r for r in M['event'].query.filter(M['event'].campus.in_(allowed)).all()})
    @bp.get('/logo')
    def logo():
        row=db.session.get(app.extensions['institute_setup_models']['profile'],1)
        if not row or not row.logo or row.logo_mime not in ('image/png','image/jpeg','image/webp'):abort(404)
        return send_file(io.BytesIO(row.logo),mimetype=row.logo_mime)
    @bp.get('/settings')
    def settings():
        release=app.extensions['school_app_helpers']['releases']([dict(key='teacher')])[0]
        return render('settings',release=release)
    @bp.get('/profile')
    def profile():return render('profile',details=employee_details(),has_photo=rm['file'].query.filter_by(owner_kind='employee',owner_id=g.teacher_employee.id,photo=True).first() is not None)
    @bp.get('/my-photo')
    def my_photo():
        row=rm['file'].query.filter_by(owner_kind='employee',owner_id=g.teacher_employee.id,photo=True).first_or_404()
        if row.mime not in ('image/jpeg','image/png','image/webp'):abort(404)
        return send_file(io.BytesIO(row.content),mimetype=row.mime)
    def employee_details():
        row=rm['employee'].query.filter_by(employee_id=g.teacher_employee.id).first()
        return row.data if row else {}
    def own_access(*codes):
        campus=employee_details().get('campus','')
        return any(campus in grants(code) for code in codes)
    def month_range():
        today=school_today();start=request.args.get('from_month',today.strftime('%Y-%m'));end=request.args.get('to_month',start)
        if not re.fullmatch(r'\d{4}-\d{2}',start) or not re.fullmatch(r'\d{4}-\d{2}',end):raise ValueError('Choose valid months.')
        first=parse_day(start+'-01');last=parse_day(end+'-01')
        if last<first or (last.year-first.year)*12+last.month-first.month>23:raise ValueError('Choose an ordered range of up to 24 months.')
        return first,last.replace(day=calendar.monthrange(last.year,last.month)[1])
    @bp.get('/my-records')
    def own_records():return redirect(url_for('teacher_app.staff_attendance'))
    @bp.get('/my-attendance')
    def staff_attendance():
        if not own_access('attendance.own','attendance.view','attendance.self'):abort(403)
        first,last=month_range();rows=Daily.query.filter_by(kind='staff',person_id=g.teacher_employee.id).filter(Daily.day>=first,Daily.day<=min(last,school_today())).order_by(Daily.day.desc()).all()
        counts={status:sum(r.status==status for r in rows) for status in app.extensions['attendance_control_helpers']['statuses']('staff')}
        return render('staff_attendance',attendance=rows,counts=counts,first=first,last=last)
    @bp.get('/my-salary')
    def own_salary():
        if not own_access('payroll.self','payroll.view'):abort(403)
        first,last=month_range();S=ops['salary'];rows=S.query.filter_by(employee_id=g.teacher_employee.id).filter(S.month>=first.strftime('%Y-%m'),S.month<=last.strftime('%Y-%m')).order_by(S.month.desc()).all()
        totals={key:sum(getattr(r,key) for r in rows) for key in ('earnings','deductions','net','paid')}
        totals['security']=sum(r.detail.get('plan',{}).get('security_payment',0) for r in rows)
        return render('salary',salaries=rows,totals=totals,first=first,last=last)
    @bp.route('/requests/<kind>',methods=['GET','POST'])
    def own_requests(kind):
        if kind not in ('advance','leave'):abort(404)
        if not own_access('hrm.self_requests'):abort(403,'Ask the school to enable My HRM Requests for your account.')
        wk='advances' if kind=='advance' else 'leave-approvals'
        token=review('request-'+kind,g.teacher_employee.id,{'employee':g.teacher_employee.id,'campus':employee_details().get('campus')})
        if request.method=='POST':
            reason=request.form.get('reason','').strip()
            if not reason or len(reason)>2000:raise ValueError('Enter a reason of up to 2000 characters.')
            data=dict(employee_id=str(g.teacher_employee.id),reason=reason)
            if kind=='advance':
                values=[]
                for key in ('amount','return_amount'):
                    try:value=Decimal(request.form.get(key,''))
                    except InvalidOperation:raise ValueError('Enter valid advance and monthly return amounts.')
                    if not value.is_finite() or value<=0 or value>Decimal('100000000') or value.as_tuple().exponent < -2:raise ValueError('Use positive amounts with at most two decimal places.')
                    values.append(value);data[key]=format(value,'.2f')
                if values[1]>values[0]:raise ValueError('Monthly return cannot exceed the advance.')
                data['date']=str(parse_day(request.form.get('date')))
            else:
                start=parse_day(request.form.get('from_date'));end=parse_day(request.form.get('to_date'));typ=request.form.get('type','')
                if typ not in ('Leave','Short Leave','Death Leave','Paper Leave') or end<start or (end-start).days>365:raise ValueError('Choose a configured leave type and an ordered date range of at most 366 days.')
                data.update(type=typ,from_date=str(start),to_date=str(end))
            # The linked employee and Pending status are derived server-side.
            row=W(kind=wk,data=data,status='Pending');db.session.add(row);audit('Teacher requested '+kind,request_kind=wk);db.session.commit();flash('Request sent to the school for approval.','success');return redirect(url_for('teacher_app.own_requests',kind=kind))
        first=parse_day(request.args.get('from_date',str(school_today()-timedelta(days=30))));last=parse_day(request.args.get('to_date',str(school_today()+timedelta(days=30))))
        if first>last or (last-first).days>732:raise ValueError('Choose an ordered date range of up to two years.')
        rows=W.query.filter(W.kind==wk,W.data['employee_id'].as_string()==str(g.teacher_employee.id)).order_by(W.id.desc()).all()
        rows=[r for r in rows if str(first)<=r.data.get('date' if kind=='advance' else 'from_date','')<=str(last)]
        return render('requests',kind=kind,rows=rows,review_token=token,first=first,last=last)
    @bp.get('/diaries')
    def diaries():
        assigned=[subject_cohort(c,subject) for c in cohorts('student_extras.view') for subject in subject_choices(c)];first=parse_day(request.args.get('from_date',str(school_today())));last=parse_day(request.args.get('to_date',str(school_today())))
        if last<first or (last-first).days>30 or last>school_today():raise ValueError('Choose a diary range of up to 31 days through today.')
        filters={k:request.args.get(k,'').strip() for k in ('class_name','section','subject')};search=request.args.get('q','').strip()[:120].casefold();choices={k:sorted({c.data[k] for c in assigned}) for k in filters}
        E=app.extensions['student_extras_models']['entry'];entries=E.query.filter(E.kind=='diary',E.starts>=first,E.starts<=last,E.campus.in_({c.data['campus'] for c in assigned})).all();keys={(r.campus,r.data.get('class_name'),r.data.get('section'),r.data.get('subject'),r.starts) for r in entries};cards=[]
        for c in assigned:
            if any(v and c.data[k]!=v for k,v in filters.items()) or search and search not in ' '.join(str(v) for v in c.data.values()).casefold():continue
            for n in range((last-first).days+1):
                day=first+timedelta(days=n);sent=(c.data['campus'],c.data['class_name'],c.data['section'],c.data['subject'],day) in keys
                cards.append(dict(row=c,day=day,sent=sent))
        return render('diaries',cards=cards,first=first,last=last,filters=filters,choices=choices,search=request.args.get('q','')[:120],sent=sum(c['sent'] for c in cards))
    @bp.get('/classes/<int:cid>/absentees')
    def absentees(cid):
        c=cohort(cid,'attendance.view');first=parse_day(request.args.get('from_date',str(school_today())));last=parse_day(request.args.get('to_date',str(school_today())))
        try:minimum=int(request.args.get('minimum','1'))
        except ValueError:raise ValueError('Use a valid minimum absence count.')
        if last<first or (last-first).days>366 or last>school_today() or not 1<=minimum<=367:raise ValueError('Choose a valid range through today and a positive absence count.')
        pupils={s.id:(s,d) for s,d in roster(c,False)};D=Daily;records=D.query.filter(D.kind=='student',D.person_id.in_(pupils),D.day>=first,D.day<=last).order_by(D.day).all();grouped={}
        for sid in pupils:
            history=[r for r in records if r.person_id==sid];absent=[r for r in history if r.status=='Absent'];longest=run=0
            for r in history:
                run=run+1 if r.status=='Absent' else 0;longest=max(longest,run)
            if len(absent)>=minimum and (request.args.get('consecutive')!='1' or longest>=minimum):grouped[sid]=absent
        return render('absentees',cohort=c,pupils=pupils,history=grouped,first=first,last=last,minimum=minimum,consecutive=request.args.get('consecutive')=='1')
    @bp.get('/classes/<int:cid>/fee-defaulters')
    def fee_defaulters(cid):
        c=cohort(cid,'fees.view');pupils={s.id:(s,d) for s,d in roster(c,False)};B=ops['bill'];query=B.query.filter(B.student_id.in_(pupils));future=request.args.get('future')=='1';search=request.args.get('q','').strip()[:120].casefold()
        if not future:query=query.filter(B.due<school_today())
        bills=[b for b in query.order_by(B.due,B.id).all() if b.remaining>0 and (not search or search in pupils[b.student_id][0].name.casefold())]
        return render('defaulters',cohort=c,pupils=pupils,bills=bills,future=future,search=request.args.get('q','')[:120])
    @bp.route('/student-leaves',methods=['GET','POST'])
    def student_leaves():
        permission='teacher.leave_approve' if request.method=='POST' else 'teacher.leave_view';assigned=cohorts(permission);pupils={s.id:(s,d) for c in assigned for s,d in roster(c,False)}
        if not assigned:abort(403,'The school has not enabled student leave access for your assigned classes.')
        L=app.extensions['general_leave_model'];query=L.query.filter(L.institute_scope==g.school_identity['scope'],L.student_id.in_(pupils));status=request.args.get('status','Pending')
        if status not in ('Pending','Approved','Rejected','All'):raise ValueError('Choose a valid leave status.')
        if request.method=='POST':
            row=query.filter_by(id=request.form.get('id',type=int)).first_or_404();review('student-leave',row.id,[row.status,row.comment,row.reason,str(row.from_date),str(row.to_date)])
            decision=request.form.get('status');comment=request.form.get('comment','').strip()
            if row.status!='Pending':abort(409,'This leave has already been decided.')
            if decision not in ('Approved','Rejected') or len(comment)>2000:raise ValueError('Choose approve or reject and a comment up to 2000 characters.')
            row.status=decision;row.comment=comment;audit('Teacher decided student leave',student_id=row.student_id,leave_id=row.id,status=decision);db.session.commit();return redirect(url_for('teacher_app.student_leaves'))
        if status!='All':query=query.filter_by(status=status)
        rows=query.order_by(L.id.desc()).limit(100).all();tokens={r.id:review('student-leave',r.id,[r.status,r.comment,r.reason,str(r.from_date),str(r.to_date)]) for r in rows}
        return render('leaves',rows=rows,pupils=pupils,status=status,tokens=tokens)
    @bp.route('/reminders',methods=['GET','POST'])
    def reminders():
        query=W.query.filter(W.kind=='teacher-reminder',W.data['staff_id'].as_integer()==g.staff_principal.id)
        if request.method=='POST':
            action=request.form.get('action')
            if action=='create':
                review('reminder','new',g.staff_principal.id);title=request.form.get('title','').strip();audience=request.form.get('audience','self');cid=request.form.get('cohort',type=int);assigned=cohort(cid,'student_extras.update') if audience=='parents' else None;note=request.form.get('note','').strip();due=request.form.get('due','');repeat=request.form.get('repeat','none')
                if audience not in ('self','parents'):raise ValueError('Choose yourself or assigned class parents.')
                if not 1<=len(title)<=180 or len(note)>2000 or repeat not in ('none','daily','weekly'):raise ValueError('Check the reminder title, note and repetition.')
                try:stamp=datetime.fromisoformat(due)
                except ValueError:raise ValueError('Choose a date and time.')
                if stamp.tzinfo is not None or not 2020<=stamp.year<=2100:raise ValueError('Choose a local school date and time.')
                if query.filter(W.status=='Active').count()>=100:raise ValueError('Complete old reminders before adding more (100 active maximum).')
                db.session.add(W(kind='teacher-reminder',status='Active',data=dict(staff_id=g.staff_principal.id,title=title,note=note,due=stamp.isoformat(timespec='minutes'),repeat=repeat,audience=audience,cohort=assigned.id if assigned else None,assignment=dict(assigned.data) if assigned else {})))
            elif action in ('done','delete'):
                row=query.filter_by(id=request.form.get('id',type=int)).first_or_404();review('reminder',row.id,[row.status,row.data])
                if action=='delete':row.status='Voided'
                elif row.data.get('audience')=='parents':raise ValueError('Delete a scheduled parent notice to cancel future visibility.')
                elif row.data.get('repeat') in ('daily','weekly'):
                    due=datetime.fromisoformat(row.data['due']);step=timedelta(days=1 if row.data['repeat']=='daily' else 7)
                    while due<=datetime.now(SCHOOL_TIMEZONE).replace(tzinfo=None):due+=step
                    row.data={**row.data,'due':due.isoformat(timespec='minutes')}
                else:row.status='Completed'
            else:abort(422)
            db.session.commit();return redirect(url_for('teacher_app.reminders'))
        tab=request.args.get('tab','todos');now=datetime.now(SCHOOL_TIMEZONE).replace(tzinfo=None).isoformat(timespec='minutes');rows=query.filter(W.status!='Voided').order_by(W.id.desc()).all()
        rows=[r for r in rows if (request.args.get('completed')=='1' or r.status!='Completed') and (tab=='todos' or (r.data['due']>now if tab=='upcoming' else r.data['due']<=now))]
        return render('reminders',rows=rows,tab=tab,now=now,new_token=review('reminder','new',g.staff_principal.id),tokens={r.id:review('reminder',r.id,[r.status,r.data]) for r in rows})

    @bp.get('/tool/<key>')
    def tool(key):
        if key=='messages':
            if not grants('messages.view'):abort(403)
            target=url_for('messages.inbox',teacher_embed=1)
        elif key=='geo':
            if not own_access('attendance.self'):abort(403)
            target=url_for('attendance_controls.self_attendance',teacher_embed=1)
        elif key=='password':target=url_for('staff_access.my_password',teacher_embed=1)
        else:abort(404)
        return render('tool',tool_url=target)
    def parent_reminders(student,details):
        # Pure read: a scheduled notice becomes visible at its chosen Pakistan
        # time. No anonymous scheduler or GET request writes messages/SMS.
        current=datetime.now(SCHOOL_TIMEZONE).replace(tzinfo=None);result=[];staff_model=app.extensions['staff_account_model']
        for row in W.query.filter(W.kind=='teacher-reminder',W.status=='Active',W.data['audience'].as_string()=='parents').all():
            d=row.data;assignment=d.get('assignment',{})
            if assignment.get('campus')!=details.get('campus') or assignment.get('class_name')!=student.class_name or assignment.get('section')!=details.get('section'):continue
            staff=db.session.get(staff_model,d.get('staff_id'));employee=db.session.get(Employee,staff.employee_id) if staff else None
            if not staff or not staff.active or staff.data.get('role')!='Teacher' or not employee or employee.status!='Active' or details.get('campus') not in sh['teacher_app_grant'](staff,'student_extras.update'):continue
            link=db.session.get(W,d.get('cohort'))
            if not link or link.kind!='teacher-classes' or link.status!='Active' or link.data!=assignment or str(link.data.get('employee_id'))!=str(employee.id):continue
            due=datetime.fromisoformat(d['due'])
            if due>current:continue
            if d.get('repeat') in ('daily','weekly'):
                period=timedelta(days=1 if d['repeat']=='daily' else 7);due+=period*((current-due)//period)
            result.append(dict(key='teacher-reminder:'+str(row.id),revision=digest([d,due.isoformat()]),title=d['title'],body=d.get('note',''),when=due.isoformat()))
        return result

    @bp.after_request
    def private(response):response.headers['Cache-Control']='no-store';return response
    @app.context_processor
    def embed():return dict(is_teacher_embed=bool(request.args.get('teacher_embed')=='1' and getattr(g,'staff_principal',None) and g.staff_principal.data.get('role')=='Teacher' and (request.blueprint=='messages' or request.endpoint in ('staff_access.my_password','attendance_controls.self_attendance'))))
    app.extensions['teacher_app_helpers']=dict(cohorts=cohorts,cohort=cohort,roster=roster,parent_reminders=parent_reminders)
    app.register_blueprint(bp)
