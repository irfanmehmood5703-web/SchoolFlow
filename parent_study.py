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
    class SubmissionFile(db.Model):
        __tablename__='parent_study_submission_file'
        id=db.Column(db.Integer,primary_key=True)
        submission_id=db.Column(db.Integer,db.ForeignKey(Submission.id),nullable=False,index=True)
        filename=db.Column(db.String(180),nullable=False)
        mime=db.Column(db.String(100),nullable=False)
        content=db.deferred(db.Column(db.LargeBinary,nullable=False))
    app.extensions['parent_study_models']=dict(item=Item,file=File,submission=Submission,submission_file=SubmissionFile)
    def response_files(submissions):
        groups={r.id:[] for r in submissions}
        if groups:
            for file in SubmissionFile.query.filter(SubmissionFile.submission_id.in_(groups)).order_by(SubmissionFile.id).all():
                groups[file.submission_id].append(file)
        return groups
    def response_download(file):
        response=send_file(io.BytesIO(file.content),mimetype=file.mime,download_name=file.filename,as_attachment=True)
        response.headers['Content-Security-Policy']="default-src 'none'; sandbox"
        response.headers['Cache-Control']='private, no-store'
        return response
    def choices(key):return sorted({r.value for r in rm['settings'].query.filter_by(category=key).all()})
    def visible(row,s,d):
        return row.published and row.starts<=school_today()<=row.ends and row.campus==d.get('campus','') and row.class_name==s.class_name and (not row.section or row.section==d.get('section','')) and (not row.subject or not d.get('subjects') or row.subject in d['subjects']) and (not row.data.get('students') or str(s.id) in row.data['students']) and (not row.data.get('academic_session') or row.data['academic_session']==d.get('academic_session',''))
    def allowed(row,s,d):return access(s.id,d.get('campus',''),'dates' if row.kind=='dates' else 'rollslip' if row.kind=='rollslip' else 'quizzes' if row.kind=='vacation' else 'diary')['effective']!='block'
    def listing(kind,s,d):return [r for r in Item.query.filter_by(kind=kind).order_by(Item.starts.desc(),Item.id.desc()).all() if visible(r,s,d) and allowed(r,s,d)]
    def parent_page(kind,s,d,renderer,**values):
        items=listing(kind,s,d);f=principal()
        submissions=Submission.query.filter_by(student_id=s.id,family_id=f.id).filter(Submission.item_id.in_([r.id for r in items])).all()
        return renderer(kind,s,d,study=items,files={r.id:File.query.filter_by(item_id=r.id).all() for r in items},submissions={r.item_id:r for r in submissions},response_files=response_files(submissions),**values)
    def submit(f,s,d,save_action,link):
        raw=request.form.get('item','');body=request.form.get('body','').strip()
        if not raw.isascii() or not raw.isdigit() or len(raw)>18:abort(422,'Choose the assignment.')
        row=db.get_or_404(Item,int(raw))
        if row.kind!='assignments' or not visible(row,s,d):abort(404)
        if not allowed(row,s,d):abort(403)
        if row.due and row.due<school_today():abort(422,'The submission deadline has passed. Contact the school.')
        def retry(message):
            db.session.rollback()
            return parent_page('assignments',s,d,render,response_error_item=row.id,response_error=message,response_draft=body),422
        if len(body)>10000:return retry('Keep your written response within 10,000 characters.')
        try:files=app.extensions['student_extra_uploads']()
        except ValueError as error:return retry(str(error))
        if not body and not files:return retry('Write a response or attach at least one file.')
        def create():
            if Submission.query.filter_by(item_id=row.id,student_id=s.id).first():abort(409,'A response is already submitted. Contact the school to revise it.')
            submission=Submission(item_id=row.id,student_id=s.id,family_id=f.id,body=body)
            db.session.add(submission);db.session.flush()
            for name,mime,content in files:
                db.session.add(SubmissionFile(submission_id=submission.id,filename=name,mime=mime,content=content))
            return submission
        # Preserve the historical fingerprint for text-only submissions; a file
        # retry must include identical bytes, not just matching filenames.
        values=dict(item=row.id,body=body)
        if files:values['files']=[(name,mime,hashlib.sha256(content).hexdigest()) for name,mime,content in files]
        save_action(f,s,'submission',values,create)
        flash('Assignment response sent to the school.','success')
        return redirect(link('assignments',s.id))
    @public.get('/app/students/<int:sid>/study/responses/<int:rid>/files/<int:fid>')
    def assignment_response_file(code,sid,rid,fid):
        f,rows=family_rows()
        if not f:abort(403)
        s,d=selected(rows,sid)
        sub=Submission.query.filter_by(id=rid,student_id=s.id,family_id=f.id).first_or_404()
        row=db.get_or_404(Item,sub.item_id)
        if row.kind!='assignments' or not visible(row,s,d):abort(404)
        if not allowed(row,s,d):abort(403)
        file=SubmissionFile.query.filter_by(id=fid,submission_id=sub.id).first_or_404()
        return response_download(file)
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
    @bp.get('/responses/<int:rid>/files/<int:fid>')
    def assignment_response_file_admin(rid,fid):
        db.get_or_404(Submission,rid)
        file=SubmissionFile.query.filter_by(id=fid,submission_id=rid).first_or_404()
        return response_download(file)
    @bp.errorhandler(ValueError)
    def invalid(e):db.session.rollback();return render_template('operation_error.html',title='Check parent publication',error=str(e)),422
    @bp.errorhandler(IntegrityError)
    @bp.errorhandler(StaleDataError)
    def conflict(e):db.session.rollback();return 'Publication changed. Reload this page before saving.',409
    def document(wid):
        row=db.get_or_404(ops['workflow'],wid)
        if row.kind not in ('awards','date-sheets','roll-slips'):abort(404)
        pupils=app.extensions['record_helpers']['read_many']('student',Student.query.filter_by(status='Active').all())
        matched={str(s.id):dict(roll=d.get('roll_no',''),section=d.get('section','')) for s,d in pupils if s.class_name==row.data.get('class_name') and all(not row.data.get(k) or d.get(k)==row.data[k] for k in ('campus','section','gender','group_name','academic_session')) and (row.data.get('student_filter')!='subject' or not d.get('subjects') or any(p.get('subject') in d['subjects'] for p in row.data.get('papers',[])))}
        if row.kind=='roll-slips':
            assigned=row.data.get('students',{})
            matched={sid:dict(roll=assigned[sid]['roll'],hall=assigned[sid].get('hall',''),section=value['section']) for sid,value in matched.items() if sid in assigned}
        if not matched:raise ValueError('No active students match this saved document.')
        papers=[{k:p.get(k,'') for k in ('subject','date','time','type','syllabus')} for p in row.data.get('papers',[])]
        value=dict(workflow_id=wid,exam=row.data.get('name','Exam'),students=matched,papers=papers)
        if row.kind=='roll-slips':value.update(academic_session=row.data.get('academic_session',''),instructions=row.data.get('instructions',''))
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
            if action=='edit-resource':
                row=db.get_or_404(Item,request.form.get('id',type=int))
                if request.form.get('version')!=str(row.version):abort(409)
                if row.published:raise ValueError('Unpublish the resource before editing.')
                title=request.form.get('title','').strip()
                body=clean_work(request.form.get('body',''))
                if not 1<=len(title)<=180:raise ValueError('Enter a title of 1 to 180 characters.')
                try:
                    start=date.fromisoformat(request.form.get('starts',''))
                    end=date.fromisoformat(request.form.get('ends',''))
                    due=date.fromisoformat(request.form['due']) if request.form.get('due') else None
                except ValueError:raise ValueError('Choose valid publication dates.')
                if end<start or (end-start).days>1096 or (due and not start<=due<=end):raise ValueError('Check the publication window and deadline.')
                resource=request.form.get('resource_url','').strip()
                if resource:
                    parsed=urlsplit(resource)
                    if len(resource)>2000 or parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password or any(c.isspace() for c in resource):raise ValueError('Use a public HTTPS study link without credentials.')
                # Reviewed examination snapshots and resources with responses retain their original audience.
                fixed=row.kind in ('dates','rollslip') or Submission.query.filter_by(item_id=row.id).first() is not None
                scope={k:request.form.get(k,getattr(row,k)) for k in ('campus','class_name','section','subject')}
                if fixed and any(v!=getattr(row,k) for k,v in scope.items()):raise ValueError('The reviewed audience cannot be changed. Create a new resource for a different audience.')
                if not fixed:
                    campus,cls,section,subject=(scope[k] for k in ('campus','class_name','section','subject'))
                    if campus not in choices('campus') or cls not in choices('class_name') or (section and section not in choices('section')) or (subject and subject not in choices('subject')):raise ValueError('Choose a valid campus, class, section and subject.')
                    mapping=app.extensions['institute_setup_helpers']['payload']();maps=mapping['maps'];cohort=next((m for m in maps.get(campus,[]) if m['class_name']==cls),None)
                    if mapping['campuses'].get(campus) is False or campus in maps and (not cohort or section and section not in cohort.get('sections',[])):raise ValueError('Choose an active campus, class and section combination.')
                    if subject and not app.extensions['school_settings_helpers']['subject_allowed'](campus,cls,subject):raise ValueError('Subject is not assigned to this class.')
                existing_files=File.query.filter_by(item_id=row.id).all()
                remove=set(request.form.getlist('remove_file'))
                if not remove.issubset({str(f.id) for f in existing_files}):abort(422)
                retained=[f for f in existing_files if str(f.id) not in remove]
                uploads=app.extensions['student_extra_uploads']()
                if len(retained)+len(uploads)>5 or sum(len(f.content) for f in retained)+sum(len(content) for _,_,content in uploads)>15*1024*1024:raise ValueError('Keep at most five attachments and 15 MB combined.')
                before=dict(title=row.title,starts=row.starts.isoformat(),ends=row.ends.isoformat(),scope={k:getattr(row,k) for k in scope})
                row.title=title;row.body=body;row.starts=start;row.ends=end;row.due=due;row.resource_url=resource
                for k,v in scope.items():setattr(row,k,v)
                for f in existing_files:
                    if str(f.id) in remove:db.session.delete(f)
                for name,mime,content in uploads:db.session.add(File(item_id=row.id,filename=name,mime=mime,content=content))
                # Bump optimistic revision even on attachment-only changes.
                row.version+=1
                db.session.add(ops['audit'](action='Edit parent study draft',data=dict(item_id=row.id,campus=row.campus,before=before,after=dict(title=title,starts=start.isoformat(),ends=end.isoformat(),scope=scope),removed_files=len(remove),added_files=len(uploads))))
                db.session.commit();flash('Resource updated. It remains unpublished.','success')
                return redirect(url_for('parent_study.publisher'))
            if action=='edit-dates':
                row=db.get_or_404(Item,request.form.get('id',type=int))
                if request.form.get('version')!=str(row.version):abort(409)
                if row.published:raise ValueError('Unpublish the resource before changing its visibility dates.')
                try:
                    start=date.fromisoformat(request.form.get('starts',''))
                    end=date.fromisoformat(request.form.get('ends',''))
                except ValueError:raise ValueError('Choose valid publication dates.')
                if end<start or (end-start).days>1096 or (row.due and not start<=row.due<=end):raise ValueError('Check the publication window and existing assignment deadline.')
                before=dict(starts=row.starts.isoformat(),ends=row.ends.isoformat())
                row.starts=start;row.ends=end
                db.session.add(ops['audit'](action='Edit parent study visibility dates',data=dict(item_id=row.id,campus=row.campus,before=before,after=dict(starts=start.isoformat(),ends=end.isoformat()))))
                db.session.commit();flash('Visibility dates updated. Resource remains unpublished.','success')
                return redirect(url_for('parent_study.publisher'))
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
                # Serialize publication against date sheet edits/deletions.
                app.extensions['admission_capacity']['lock']()
                wid=request.form.get('workflow','')
                if not wid.isdigit():raise ValueError('Review a saved examination document first.')
                source,data,digest=document(int(wid))
                if not re.fullmatch(r'[a-f0-9]{64}',request.form.get('fingerprint','')) or not hmac.compare_digest(request.form.get('fingerprint',''),digest):raise ValueError('Exam or pupil roster changed. Review again.')
                if kind!=('dates' if source.kind=='date-sheets' else 'rollslip') or source.data.get('campus')!=campus or source.data.get('class_name')!=cls or section!=source.data.get('section',''):raise ValueError('Use the reviewed document campus, class and section.')
            files=app.extensions['student_extra_uploads']()
            row=Item(kind=kind,campus=campus,class_name=cls,section=section,subject=subject,title=title,body=body,starts=start,ends=end,due=due,resource_url=resource,data=data,published=request.form.get('published')=='1',token=token);db.session.add(row);db.session.flush()
            for name,mime,content in files:db.session.add(File(item_id=row.id,filename=name,mime=mime,content=content))
            db.session.add(ops['audit'](action='Publish parent study resource',data=dict(item_id=row.id,campus=campus,kind=kind,published=row.published)));db.session.commit();return redirect(url_for('parent_study.publisher'))
        items=Item.query.order_by(Item.id.desc()).limit(100).all()
        submissions=Submission.query.order_by(Submission.id.desc()).limit(100).all()
        return render_template('parent_study_admin.html',title='Parent Study & Documents',kinds=KINDS,choices=choices,items=items,submissions=submissions,response_files=response_files(submissions),resource_files={i.id:File.query.filter_by(item_id=i.id).all() for i in items},fixed_audiences={i.id for i in items if i.kind in ('dates','rollslip') or Submission.query.filter_by(item_id=i.id).first() is not None},review=review,token=secrets.token_urlsafe(32),today=school_today(),end=school_today()+timedelta(days=180))
    app.extensions['parent_study_helpers']=dict(parent_page=parent_page,submit=submit,listing=listing,response_files=response_files,response_download=response_download)
    app.register_blueprint(bp)
