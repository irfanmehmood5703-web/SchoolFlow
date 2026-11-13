"""Subject-wise classwork/homework, safe formatting and scoped attachments."""
import hashlib,json,re,html
import bleach
from flask import abort,g,redirect,request,session,url_for,flash
from sqlalchemy.exc import IntegrityError

ALLOWED_TAGS={'b','strong','i','em','br','p','div'}
def clean_work(value):
    if len(value)>20000:raise ValueError('Each classwork/homework editor is limited to 20,000 characters.')
    return bleach.clean(value,tags=ALLOWED_TAGS,attributes={},strip=True,strip_comments=True)
def plain_work(value):
    value=re.sub(r'<(?:br\s*/?|/p|/div)>','\n',value,flags=re.I)
    return html.unescape(bleach.clean(value,tags=set(),attributes={},strip=True)).strip()

def configure_diary_work(app,db):
    M=app.extensions['student_extras_models'];Entry=M['entry'];File=M['attachment'];Audit=app.extensions['ops_models']['audit']
    class Submission(db.Model):
        __tablename__='diary_submission'
        token=db.Column(db.String(43),primary_key=True)
        fingerprint=db.Column(db.String(64),nullable=False)
        actor=db.Column(db.String(100),nullable=False)
        campus=db.Column(db.String(160),nullable=False)
        entry_ids=db.Column(db.JSON,nullable=False)
    M['submission']=Submission
    app.jinja_env.filters['diary_html']=clean_work
    app.jinja_env.filters['diary_text']=plain_work
    def actor():return 'staff:'+str(session['staff_id']) if session.get('staff_id') else 'owner:'+str(session['owner_id']) if session.get('owner_id') else 'demo'
    def save(choices,scope_ok,parse_day,uploads):
        app.extensions['admission_capacity']['lock']()
        token=request.form.get('submission','')
        if not re.fullmatch(r'[A-Za-z0-9_-]{43}',token):raise ValueError('Reload the Diary form.')
        campus=request.form.get('campus','');cls=request.form.get('class_name','');section=request.form.get('section','')
        for key,value in [('campus',campus),('class_name',cls),('section',section)]:
            if not value or value not in choices(key):raise ValueError('Choose a configured '+key.replace('_',' ')+'.')
        scope_ok(campus);day=parse_day(request.form.get('starts',''))
        rm=app.extensions['record_models'];sections=rm['settings'].query.filter_by(category='section',value=section).all()
        if not any(not r.class_name or r.class_name==cls for r in sections):raise ValueError('Section does not belong to this class.')
        Map=app.extensions['institute_setup_models']['mapping'];maps=Map.query.filter_by(campus=campus).all()
        if maps and not any(r.class_name==cls and r.active for r in maps):raise ValueError('Class is not enabled at this campus.')
        slots=request.form.getlist('subject_slot');subjects=request.form.getlist('subjects')
        if not slots or len(slots)>20 or len(set(slots))!=len(slots) or any(not re.fullmatch(r'\d{1,4}',i) for i in slots):raise ValueError('Select between one and twenty subjects and load their editors.')
        if len(subjects)!=len(set(subjects)) or len(subjects)!=len(slots):raise ValueError('Reload the selected subject editors.')
        names=[request.form.get('subject_name_'+i,'') for i in slots]
        if set(names)!=set(subjects):raise ValueError('Selected subjects and editors do not match.')
        action=request.form.get('action');channel=request.form.get('channel')
        if action not in ('save','save-send') or channel not in ('app','branded','whatsapp'):raise ValueError('Choose a save action and message channel.')
        contacts=[c for c in ('father','mother','student') if request.form.get(c)=='1']
        if action=='save-send' and not contacts:raise ValueError('Select at least one contact.')
        work=[];size=0;count=0
        for slot,name in zip(slots,names):
            rows=rm['settings'].query.filter_by(category='subject',value=name).all()
            if name not in choices('subject') or not any(not r.class_name or r.class_name==cls for r in rows) or not app.extensions['school_settings_helpers']['subject_allowed'](campus,cls,name):raise ValueError('Subject is not assigned to the selected class.')
            item=dict(subject=name)
            for part in ('classwork','homework'):
                value=clean_work(request.form.get(part+'_'+slot,''));files=uploads(part+'_files_'+slot)
                item[part]=value;item[part+'_files']=files
                size+=sum(len(content) for _,_,content in files);count+=len(files)
                if size>15*1024*1024 or count>20:raise ValueError('A Diary submission accepts at most twenty files and 15 MB combined.')
            if not any(plain_work(item[k]) or item[k+'_files'] for k in ('classwork','homework')):raise ValueError('Enter classwork, homework or an attachment for '+name+'.')
            work.append(item)
        payload=dict(campus=campus,class_name=cls,section=section,date=day.isoformat(),action=action,channel=channel,contacts=contacts,notification=request.form.get('parent_notification')=='1',work=[{k:([dict(name=n,mime=m,sha256=hashlib.sha256(c).hexdigest()) for n,m,c in v] if k.endswith('_files') else v) for k,v in item.items()} for item in work])
        digest=hashlib.sha256(json.dumps(payload,sort_keys=True).encode()).hexdigest();prior=db.session.get(Submission,token)
        if prior:
            if prior.actor!=actor() or prior.fingerprint!=digest:raise ValueError('This submission was already saved with different details.')
            return redirect(url_for('student_extras.index',kind='diary'))
        ids=[]
        for number,item in enumerate(work):
            summary='Classwork: '+plain_work(item['classwork'])+'\nHomework: '+plain_work(item['homework'])
            row=Entry(kind='diary',campus=campus,title=(item['subject']+' — '+cls)[:180],body=summary,starts=day,ends=day,data={},token=hashlib.sha256((token+':'+str(number)).encode()).hexdigest());db.session.add(row);db.session.flush()
            data=dict(format='subject-work',class_name=cls,section=section,subject=item['subject'],classwork=item['classwork'],homework=item['homework'],channel=channel,contacts=contacts,parent_notification=payload['notification'],message_status='Provider not configured' if action=='save-send' else 'Not requested',notification_status='Provider not configured' if payload['notification'] else 'Not requested')
            for part in ('classwork','homework'):
                data[part+'_attachments']=[]
                for filename,mime,content in item[part+'_files']:
                    f=File(entry_id=row.id,filename=filename,mime=mime,content=content);db.session.add(f);db.session.flush();data[part+'_attachments'].append(f.id)
            row.data=data;ids.append(row.id)
            db.session.add(Audit(action='Create subject Diary',data=dict(entry_id=row.id,campus=campus,subject=item['subject'],actor=actor())))
        db.session.add(Submission(token=token,fingerprint=digest,actor=actor(),campus=campus,entry_ids=ids));db.session.commit()
        flash(str(len(ids))+' subject diaries saved.','success')
        return redirect(url_for('student_extras.index',kind='diary'))
    app.extensions['diary_work_helpers']=dict(save=save)
