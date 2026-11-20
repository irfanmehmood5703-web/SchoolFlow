"""Explicit school publication and family-bound study resources/submissions."""
import hashlib,hmac,io,json,re,secrets
from datetime import date,datetime,timedelta,timezone
from urllib.parse import urlsplit
from flask import Blueprint,abort,flash,g,redirect,render_template,request,send_file,session,url_for
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import StaleDataError
from diary_work import clean_work
from school_clock import school_today
KINDS={'learning':'Learning','notes':'Student Notes','assignments':'Student Assignments','vacation':'Vacation Work','dates':'Date Sheet','rollslip':'Roll-No Slip'}

def configure_parent_study(app,db,Student,public,principal,access,render,link,selected,family_rows):
    bp=Blueprint('parent_study',__name__,url_prefix='/workspace/general/parent-study');rm=app.extensions['record_models'];ops=app.extensions['ops_models']
    class Item(db.Model):
        __tablename__='parent_study_item'
        id=db.Column(db.Integer,primary_key=True)
        kind=db.Column(db.String(20),nullable=False)
        title=db.Column(db.String(180),nullable=False)
        campus=db.Column(db.String(160),nullable=False)
        class_name=db.Column(db.String(80),nullable=False)
        section=db.Column(db.String(80),nullable=False,default='')
        subject=db.Column(db.String(120),nullable=False,default='')
        body=db.Column(db.Text,nullable=False)
        resource_url=db.Column(db.String(2000),nullable=False,default='')
        starts=db.Column(db.Date,nullable=False)
        ends=db.Column(db.Date,nullable=False)
        due=db.Column(db.Date)
        published=db.Column(db.Boolean,nullable=False,default=False)
        data=db.Column(db.JSON,nullable=False,default=dict)
        token=db.Column(db.String(43),unique=True,nullable=False)
        version=db.Column(db.Integer,nullable=False,default=1)
        __mapper_args__={'version_id_col':version}
    class File(db.Model):
        __tablename__='parent_study_file'
        id=db.Column(db.Integer,primary_key=True)
        item_id=db.Column(db.Integer,db.ForeignKey(Item.id),nullable=False,index=True)
        filename=db.Column(db.String(180),nullable=False)
        mime=db.Column(db.String(100),nullable=False)
        content=db.deferred(db.Column(db.LargeBinary,nullable=False))
    class Submission(db.Model):
        __tablename__='parent_study_submission'
        id=db.Column(db.Integer,primary_key=True)
        item_id=db.Column(db.Integer,db.ForeignKey(Item.id),nullable=False)
        student_id=db.Column(db.Integer,db.ForeignKey(Student.id),nullable=False)
        family_id=db.Column(db.Integer,nullable=False)
        body=db.Column(db.Text,nullable=False)
        marks=db.Column(db.String(40),nullable=False,default='')
        feedback=db.Column(db.String(2000),nullable=False,default='')
        created=db.Column(db.DateTime,nullable=False,default=lambda:datetime.now(timezone.utc))
        version=db.Column(db.Integer,nullable=False,default=1)
        __mapper_args__={'version_id_col':version}
        __table_args__=(db.UniqueConstraint('item_id','student_id'),)
    app.extensions['parent_study_models']=dict(item=Item,file=File,submission=Submission)
    def choices(key):return sorted({r.value for r in rm['settings'].query.filter_by(category=key).all()})
    def visible(row,s,d):
        return row.published and row.starts<=school_today()<=row.ends and row.campus==d.get('campus','') and row.class_name==s.class_name and (not row.section or row.section==d.get('section','')) and (not row.subject or not d.get('subjects') or row.subject in d['subjects']) and (not row.data.get('students') or str(s.id) in row.data['students'])
    def allowed(row,s,d):return access(s.id,d.get('campus',''),'dates' if row.kind=='dates' else 'rollslip' if row.kind=='rollslip' else 'quizzes' if row.kind=='vacation' else 'diary')['effective']!='block'
    def listing(kind,s,d):return [r for r in Item.query.filter_by(kind=kind).order_by(Item.starts.desc(),Item.id.desc()).all() if visible(r,s,d) and allowed(r,s,d)]
    def parent_page(kind,s,d,renderer):
        items=listing(kind,s,d);f=principal()
        return renderer(kind,s,d,study=items,files={r.id:File.query.filter_by(item_id=r.id).all() for r in items},submissions={r.item_id:r for r in Submission.query.filter_by(student_id=s.id,family_id=f.id).all()})
    def submit(f,s,d,save_action,link):
        raw=request.form.get('item','');body=request.form.get('body','').strip()
        if not raw.isdigit() or not 1<=len(body)<=10000:abort(422,'Enter your assignment response.')
        row=db.get_or_404(Item,int(raw))
        if row.kind!='assignments' or not visible(row,s,d):abort(404)
        if not allowed(row,s,d):abort(403)
        if row.due and row.due<school_today():abort(422,'The submission deadline has passed. Contact the school.')
        def create():
            if Submission.query.filter_by(item_id=row.id,student_id=s.id).first():abort(409,'A response is already submitted. Contact the school to revise it.')
            return Submission(item_id=row.id,student_id=s.id,family_id=f.id,body=body)
        save_action(f,s,'submission',dict(item=row.id,body=body),create);flash('Assignment response sent to the school.','success');return redirect(link('assignments',s.id))
    @public.get('/app/students/<int:sid>/study/files/<int:fid>')
    def study_file(code,sid,fid):
        f,rows=family_rows()
        if not f:abort(403)
        s,d=selected(rows,sid);file=db.get_or_404(File,fid);row=db.get_or_404(Item,file.item_id)
        if not visible(row,s,d):abort(404)
        if not allowed(row,s,d):abort(403)
        response=send_file(io.BytesIO(file.content),mimetype=file.mime,download_name=file.filename,as_attachment=True);response.headers['Content-Security-Policy']="default-src 'none'; sandbox";return response
    @bp.before_request
    def protect():
        if not session.get('owner_id') or session.get('staff_id') or session.get('demo'):abort(403)
        if request.method=='POST':
            if not session.get('record_csrf') or not hmac.compare_digest(request.form.get('_csrf',''),session['record_csrf']):abort(400)
            app.extensions['admission_capacity']['lock']()
    @bp.errorhandler(ValueError)
    def invalid(e):db.session.rollback();return render_template('operation_error.html',title='Check parent publication',error=str(e)),422
    @bp.errorhandler(IntegrityError)
    @bp.errorhandler(StaleDataError)
    def conflict(e):db.session.rollback();return 'Publication changed. Reload this page before saving.',409
    def document(wid):
        row=db.get_or_404(ops['workflow'],wid)
        if row.kind not in ('awards','date-sheets'):abort(404)
        pupils=app.extensions['record_helpers']['read_many']('student',Student.query.filter_by(status='Active').all())
        matched={str(s.id):dict(roll=d.get('roll_no',''),section=d.get('section','')) for s,d in pupils if s.class_name==row.data.get('class_name') and all(not row.data.get(k) or d.get(k)==row.data[k] for k in ('campus','section','gender','group_name','academic_session')) and (row.data.get('student_filter')!='subject' or not d.get('subjects') or any(p.get('subject') in d['subjects'] for p in row.data.get('papers',[])))}
        if not matched:raise ValueError('No active students match this saved document.')
        papers=[{k:p.get(k,'') for k in ('subject','date','time','type','syllabus')} for p in row.data.get('papers',[])]
        value=dict(workflow_id=wid,exam=row.data.get('name','Exam'),students=matched,papers=papers)
        return row,value,hashlib.sha256(json.dumps(dict(source=row.data,snapshot=value),sort_keys=True).encode()).hexdigest()
    @bp.route('',methods=['GET','POST'])
    def publisher():
        review=None
        raw=request.args.get('workflow','')
        if raw:
            if not raw.isdigit():abort(422)
            row,data,digest=document(int(raw));review=dict(row=row,data=data,fingerprint=digest)
        if request.method=='POST':
            action=request.form.get('action')
            if action=='toggle':
                row=db.get_or_404(Item,request.form.get('id',type=int))
                if request.form.get('version')!=str(row.version):abort(409)
                row.published=not row.published;db.session.add(ops['audit'](action='Change parent publication visibility',data=dict(item_id=row.id,published=row.published,campus=row.campus)));db.session.commit();return redirect(url_for('parent_study.publisher'))
            if action=='grade':
                row=db.get_or_404(Submission,request.form.get('id',type=int))
                if request.form.get('version')!=str(row.version):abort(409)
                marks=request.form.get('marks','').strip();feedback=request.form.get('feedback','').strip()
                if len(marks)>40 or len(feedback)>2000:raise ValueError('Marks/feedback are too long.')
                row.marks=marks;row.feedback=feedback;db.session.add(ops['audit'](action='Review parent assignment response',data=dict(submission_id=row.id,student_id=row.student_id)));db.session.commit();return redirect(url_for('parent_study.publisher'))
            if action!='publish':abort(422)
            token=request.form.get('token','')
            if not re.fullmatch(r'[A-Za-z0-9_-]{43}',token):abort(422)
            if Item.query.filter_by(token=token).first():return redirect(url_for('parent_study.publisher'))
            kind=request.form.get('kind','');campus=request.form.get('campus','');cls=request.form.get('class_name','');section=request.form.get('section','');subject=request.form.get('subject','');title=request.form.get('title','').strip();body=clean_work(request.form.get('body',''))
            if kind not in KINDS or campus not in choices('campus') or cls not in choices('class_name') or (section and section not in choices('section')) or (subject and subject not in choices('subject')) or not 1<=len(title)<=180:raise ValueError('Choose valid class, campus, subject and title.')
            mapping=app.extensions['institute_setup_helpers']['payload']();maps=mapping['maps'];cohort=next((m for m in maps.get(campus,[]) if m['class_name']==cls),None)
            if mapping['campuses'].get(campus) is False or campus in maps and (not cohort or section and section not in cohort.get('sections',[])):raise ValueError('Choose an active campus, class and section combination.')
            if subject and not app.extensions['school_settings_helpers']['subject_allowed'](campus,cls,subject):raise ValueError('Subject is not assigned to this class.')
            try:start=date.fromisoformat(request.form.get('starts',''));end=date.fromisoformat(request.form.get('ends',''));due=date.fromisoformat(request.form['due']) if request.form.get('due') else None
            except ValueError:raise ValueError('Choose valid publication dates.')
            if end<start or (end-start).days>1096 or (due and not start<=due<=end):raise ValueError('Check the publication window and deadline.')
            resource=request.form.get('resource_url','').strip()
            if resource:
                parsed=urlsplit(resource)
                if len(resource)>2000 or parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password or any(c.isspace() for c in resource):raise ValueError('Use a public HTTPS study link without credentials.')
            data={}
            if kind in ('dates','rollslip'):
                wid=request.form.get('workflow','')
                if not wid.isdigit():raise ValueError('Review a saved examination document first.')
                source,data,digest=document(int(wid))
                if not re.fullmatch(r'[a-f0-9]{64}',request.form.get('fingerprint','')) or not hmac.compare_digest(request.form.get('fingerprint',''),digest):raise ValueError('Exam or pupil roster changed. Review again.')
                if kind!=('dates' if source.kind=='date-sheets' else 'rollslip') or source.data.get('campus')!=campus or source.data.get('class_name')!=cls or section!=source.data.get('section',''):raise ValueError('Use the reviewed document campus, class and section.')
            files=app.extensions['student_extra_uploads']()
            row=Item(kind=kind,campus=campus,class_name=cls,section=section,subject=subject,title=title,body=body,starts=start,ends=end,due=due,resource_url=resource,data=data,published=request.form.get('published')=='1',token=token);db.session.add(row);db.session.flush()
            for name,mime,content in files:db.session.add(File(item_id=row.id,filename=name,mime=mime,content=content))
            db.session.add(ops['audit'](action='Publish parent study resource',data=dict(item_id=row.id,campus=campus,kind=kind,published=row.published)));db.session.commit();return redirect(url_for('parent_study.publisher'))
        return render_template('parent_study_admin.html',title='Parent Study & Documents',kinds=KINDS,choices=choices,items=Item.query.order_by(Item.id.desc()).limit(100).all(),submissions=Submission.query.order_by(Submission.id.desc()).limit(100).all(),review=review,token=secrets.token_urlsafe(32),today=school_today(),end=school_today()+timedelta(days=180))
    app.extensions['parent_study_helpers']=dict(parent_page=parent_page,submit=submit,listing=listing)
    app.register_blueprint(bp)
