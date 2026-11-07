"""Family-bound parent web access and auditable school-side management.

Native Android clients and SIM delivery are separate integrations. No invitation
or OTP is sent by these routes; verified staff can hand a short-lived code/link
to the correct family after checking identity.
"""
import base64,hashlib,hmac,io,re,secrets,time
from collections import defaultdict
from datetime import date,datetime
from zoneinfo import ZoneInfo
from cryptography.fernet import Fernet
from flask import Blueprint,abort,flash,g,redirect,render_template,request,send_file,session,url_for
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import StaleDataError

FEATURES=[('shop','School Shop'),('quizzes','Vacation quizzes'),('notice','Notice Board'),('messages','Messages & Notifications'),('attendance','Attendance'),('diary','Daily Diary'),('marks','Academics & Marks'),('results','Exam Report Cards'),('dates','Date Sheet'),('rollslip','Roll Number Slip'),('fees','Fee Details'),('leave','Leave Application'),('complaints','Complaints & Suggestions'),('talk','Teacher Talk'),('overview','Student 360°'),('profile','Student Profile'),('pickup','Pickup pass'),('help','Get Help / Contact Us')]
ALWAYS={'fees','pickup','help'}
MODES={'allow','warn','block'}


def configure_parents(app,db,Student):
    bp=Blueprint('parents',__name__,url_prefix='/workspace/general/parents')
    public=Blueprint('parent_portal',__name__,url_prefix='/parents/<code>')
    rm=app.extensions['record_models'];Audit=app.extensions['ops_models']['audit'];Bill=app.extensions['ops_models']['bill']
    class Account(db.Model):
        __tablename__='parent_account'
        family_id=db.Column(db.Integer,db.ForeignKey(rm['family'].id),primary_key=True)
        last_used=db.Column(db.Float,nullable=False,default=0)
        version=db.Column(db.Integer,nullable=False,default=1)
    class Challenge(db.Model):
        __tablename__='parent_challenge'
        id=db.Column(db.String(43),primary_key=True)
        family_id=db.Column(db.Integer,db.ForeignKey(rm['family'].id),nullable=False,index=True)
        kind=db.Column(db.String(10),nullable=False)
        digest=db.Column(db.String(64),nullable=False)
        encrypted=db.Column(db.LargeBinary,nullable=False)
        created=db.Column(db.Float,nullable=False)
        expires=db.Column(db.Float,nullable=False)
        used=db.Column(db.Float,nullable=False,default=0)
        replaced=db.Column(db.Boolean,nullable=False,default=False)
        attempts=db.Column(db.Integer,nullable=False,default=0)
    class Policy(db.Model):
        __tablename__='parent_access_policy'
        id=db.Column(db.Integer,primary_key=True)
        data=db.Column(db.JSON,nullable=False,default=dict)
        version=db.Column(db.Integer,nullable=False,default=1)
        __mapper_args__={'version_id_col':version}
    class Seen(db.Model):
        __tablename__='parent_notice_seen'
        id=db.Column(db.Integer,primary_key=True)
        entry_id=db.Column(db.Integer,db.ForeignKey(app.extensions['student_extras_models']['entry'].id),nullable=False,index=True)
        student_id=db.Column(db.Integer,db.ForeignKey(Student.id),nullable=False)
        family_id=db.Column(db.Integer,db.ForeignKey(rm['family'].id),nullable=False)
        seen=db.Column(db.Float,nullable=False)
        __table_args__=(db.UniqueConstraint('entry_id','student_id','family_id'),)
    class Rate(db.Model):
        __tablename__='parent_rate'
        key=db.Column(db.String(64),primary_key=True)
        count=db.Column(db.Integer,nullable=False,default=0)
        expires=db.Column(db.Float,nullable=False)
    app.extensions['parent_models']=dict(account=Account,challenge=Challenge,policy=Policy,rate=Rate,seen=Seen)
    def now():return time.time()
    def today():return datetime.now(ZoneInfo('Asia/Karachi')).date()
    def secret():return str(app.config['SECRET_KEY']).encode()
    def cipher():return Fernet(base64.urlsafe_b64encode(hashlib.sha256(secret()+b'parent-code-encryption-v1').digest()))
    def digest(cid,value):return hmac.new(secret(),(cid+'\0'+value).encode(),hashlib.sha256).hexdigest()
    @app.template_filter('parent_stamp')
    def stamp(raw):return datetime.fromtimestamp(raw,ZoneInfo('Asia/Karachi')).strftime('%Y-%m-%d %H:%M')
    def phone(raw):
        value=re.sub(r'[^0-9]','',str(raw or ''))
        if value.startswith('0092'):value='0'+value[4:]
        elif value.startswith('92') and len(value)==12:value='0'+value[2:]
        return value
    def campuses():return app.extensions['staff_access_helpers']['campuses']()
    def policy():return db.session.get(Policy,1)
    def pending():
        result=defaultdict(set);day=today()
        for b in Bill.query.filter(Bill.due<day).all():
            if b.remaining>0 and re.fullmatch(r'\d{4}-\d{2}',b.month or '') and b.month<=day.strftime('%Y-%m'):result[b.student_id].add(b.month)
        return {sid:len(months) for sid,months in result.items()}
    def access(sid,campus,feature,months=None):
        if feature not in dict(FEATURES):raise ValueError('Unknown parent feature.')
        if feature in ALWAYS:return dict(rule='allow',effective='allow',manual='follow')
        cfg=policy();data=cfg.data if cfg else {};months=pending().get(sid,0) if months is None else months
        rules=data.get('rules',{})
        bands={**rules.get('',{}).get(feature,{}),**rules.get(campus,{}).get(feature,{})}
        eligible=[b for b in (1,2,3) if b<=months and bands.get(str(b)) in ('warn','block')]
        rule=bands[str(max(eligible))] if eligible else 'allow'
        over=data.get('overrides',{}).get(str(sid),{}).get(feature,{})
        expired=over.get('until') and over['until']<today().isoformat()
        manual=over.get('mode','follow') if not expired else 'follow'
        return dict(rule=rule,effective=rule if manual=='follow' else manual,manual=manual)
    app.extensions['parent_helpers']=dict(access=access,pending=pending,phone=phone)
    def audit(action,**data):
        db.session.add(Audit(action=action,data={**data,'owner_id':session.get('owner_id'),'staff_id':session.get('staff_id'),'campus':data.get('campus','')}))
    def students():return app.extensions['record_helpers']['read_many']('student',Student.query.filter_by(status='Active').order_by(Student.name).all())
    def family(fid):
        f=db.session.get(rm['family'],fid)
        if not f or not rm['student'].query.join(Student,Student.id==rm['student'].student_id).filter(rm['student'].family_id==fid,Student.status=='Active').first():abort(404)
        return f
    def status(c):return 'Signed in' if c.used else 'Replaced by newer code' if c.replaced else 'Expired unused' if c.expires<=now() or c.attempts>=5 else 'Waiting for parent'
    def issue(fid,kind):
        family(fid);stamp=now()
        Challenge.query.filter_by(family_id=fid,kind=kind,used=0,replaced=False).update({'replaced':True})
        cid=secrets.token_urlsafe(32);value=str(secrets.randbelow(1000000)).zfill(6) if kind=='otp' else secrets.token_urlsafe(32)
        row=Challenge(id=cid,family_id=fid,kind=kind,digest=digest(cid,value),encrypted=cipher().encrypt(value.encode()),created=stamp,expires=stamp+600)
        db.session.add(row);return row,value
    def rate(key,limit,seconds=3600):
        key=hmac.new(secret(),key.encode(),hashlib.sha256).hexdigest();row=db.session.get(Rate,key);stamp=now()
        if not row:row=Rate(key=key,count=0,expires=stamp+seconds);db.session.add(row)
        elif row.expires<=stamp:row.count=0;row.expires=stamp+seconds
        row.count+=1
        if row.count>limit:db.session.commit();abort(429,'Too many attempts. Try again later.')
    def csrf():
        if request.method=='POST' and (not request.form.get('_csrf') or not hmac.compare_digest(request.form['_csrf'],session.get('record_csrf',''))):abort(400,'Reload this form before continuing.')
    @bp.before_request
    def protect():
        csrf()
        # Family credentials can span siblings/campuses: never expose a partial family.
        allowed=getattr(g,'access_campuses',None)
        if allowed is not None and set(allowed)!=set(campuses()):abort(403,'Parent administration requires this permission for every campus.')
        if request.method=='POST':app.extensions['admission_capacity']['lock']()
    @bp.errorhandler(ValueError)
    @public.errorhandler(ValueError)
    def invalid(error):db.session.rollback();return render_template('operation_error.html',title='Check Parents App',error=str(error)),422
    @bp.errorhandler(IntegrityError)
    @bp.errorhandler(StaleDataError)
    def conflict(error):db.session.rollback();return render_template('operation_error.html',title='Reload parent settings',error='Settings changed or this action already exists. Reload before saving.'),409
    @bp.context_processor
    def choices_context():
        return dict(parent_choices={k:sorted({r.value for r in rm['settings'].query.filter_by(category=k).all()}) for k in ('campus','class_name','section')},page_size=getattr(g,'parent_page_size',50))
    def selection():
        for key in ('from','to'):
            if request.args.get(key):
                try:
                    if date.fromisoformat(request.args[key]).isoformat()!=request.args[key]:raise ValueError()
                except ValueError:raise ValueError('Choose valid last-used dates.')
        if request.args.get('from') and request.args.get('to') and request.args['from']>request.args['to']:raise ValueError('To must be on or after From.')
        for key in ('campus','class_name','section'):
            if request.args.get(key) and not rm['settings'].query.filter_by(category=key,value=request.args[key]).first():raise ValueError('Choose a configured '+key+'.')
        rows=students();accounts={a.family_id:a for a in Account.query.all()};out=[];q=request.args.get('q','').strip().casefold()
        for s,d in rows:
            if q and q not in ' '.join(str(x) for x in (s.id,s.name,s.admission_no,d.get('father',''),d.get('phone',''))).casefold():continue
            if any(request.args.get(k) and request.args[k]!=d.get(k,s.class_name if k=='class_name' else '') for k in ('campus','class_name','section')):continue
            account=accounts.get(int(d['family_id'])) if str(d.get('family_id','')).isdigit() else None
            active=bool(account and account.last_used)
            if request.args.get('login') in ('active','inactive') and active!=(request.args['login']=='active'):continue
            if request.args.get('from') or request.args.get('to'):
                if not active:continue
                last=datetime.fromtimestamp(account.last_used,ZoneInfo('Asia/Karachi')).date().isoformat()
                if request.args.get('from') and last<request.args['from'] or request.args.get('to') and last>request.args['to']:continue
            out.append((s,d,account))
        return out
    def pagination(rows):
        try:page=max(1,int(request.args.get('page','1')))
        except ValueError:raise ValueError('Choose a valid page.')
        raw=request.args.get('per_page','50')
        if raw not in ('25','50','100'):raise ValueError('Choose 25, 50 or 100 entries per page.')
        g.parent_page_size=int(raw)
        return rows[(page-1)*g.parent_page_size:page*g.parent_page_size],page,len(rows)
    @bp.get('')
    def analytics():
        allrows=selection();rows,page,total=pagination(allrows)
        if request.args.get('export')=='xlsx':
            from report_exports import report_xlsx
            headers=['SID','Family No','Roll No','Student','Father/Guardian','Campus','Class','Section','Login Status','Last Used']
            chosen=request.args.getlist('columns') or headers
            if any(c not in headers for c in chosen):raise ValueError('Choose valid export columns.')
            positions=[headers.index(c) for c in dict.fromkeys(chosen)]
            data=[[s.id,d.get('family_no',''),d.get('roll_no',''),s.name,d.get('father',''),d.get('campus',''),s.class_name,d.get('section',''),'Active' if a and a.last_used else 'Inactive',datetime.fromtimestamp(a.last_used,ZoneInfo('Asia/Karachi')).isoformat() if a and a.last_used else ''] for s,d,a in allrows]
            return report_xlsx([headers[i] for i in positions],[[row[i] for i in positions] for row in data],'parent-analytics')
        return render_template('parents.html',title='Parents App Analytics',tab='analytics',rows=rows,page=page,total=total,active=sum(bool(a and a.last_used) for _,_,a in allrows),inactive=sum(not(a and a.last_used) for _,_,a in allrows))
    @bp.post('/invitation')
    def invitation():
        ids=request.form.getlist('students');rows={str(s.id):(s,d,a) for s,d,a in selection()}
        if not ids or any(s not in rows for s in ids):raise ValueError('Select available students.')
        message=request.form.get('message','').strip()
        contacts=[v for v in ('father','mother','student') if request.form.get(v)=='1'];channels=[v for v in ('branded','app','whatsapp','notification') if request.form.get(v)=='1']
        if not message or len(message)>4000 or not contacts or not channels:raise ValueError('Enter a message and select contact/channel options.')
        for sid in set(ids):db.session.add(rm['communication'](student_id=int(sid),preferences=dict(source='Parents App invitation',message=message,contacts=contacts,channels=channels),status='Provider not configured'))
        audit('Record parent invitation request',students=list(set(ids)));db.session.commit();flash('Invitation requests recorded. Provider not configured; no messages sent.','success');return redirect(url_for('parents.analytics'))
    @bp.get('/otp')
    def otp():
        tab=request.args.get('tab','live')
        if tab not in ('live','contact','not-installed','activity'):abort(404)
        p=getattr(g,'staff_principal',None);can_codes=p is None or set(app.extensions['staff_access_helpers']['grant'](p,'parents.codes'))==set(campuses())
        records=[]
        if tab in ('live','contact'):
            query=Challenge.query.filter_by(kind='otp').filter(Challenge.created>=now()-7200)
            if tab=='contact':
                q=phone(request.args.get('q',''))
                families=[f.id for f in rm['family'].query.all() if q and q in {phone(f.data.get(k)) for k in ('phone','mother_phone','whatsapp')}]
                query=query.filter(Challenge.family_id.in_(families))
            for row in query.order_by(Challenge.created.desc()).limit(100).all():
                value=None
                if tab=='live' and can_codes and status(row)=='Waiting for parent':
                    value=cipher().decrypt(row.encrypted).decode();audit('View live parent OTP',challenge_id=row.id,family_id=row.family_id)
                records.append((row,status(row),value,max(0,int(row.expires-now()))))
            if any(v for _,_,v,_ in records):db.session.commit()
        accounts={a.family_id:a for a in Account.query.all()}
        summaries={s:sum(status(r)==s for r in Challenge.query.filter_by(kind='otp').filter(Challenge.created>=now()-7200).all()) for s in ('Waiting for parent','Signed in','Expired unused','Replaced by newer code')}
        return render_template('parents.html',title='Parents App OTP Portal',tab='otp',otp_tab=tab,records=records,can_codes=can_codes,rows=selection() if tab in ('not-installed','activity') else [],accounts=accounts,summaries=summaries)
    @bp.post('/otp/<cid>/reveal')
    def reveal(cid):
        row=db.get_or_404(Challenge,cid)
        if row.kind!='otp' or status(row)!='Waiting for parent':raise ValueError('This code is no longer available.')
        audit('Reveal parent OTP',challenge_id=cid,family_id=row.family_id);db.session.commit()
        return render_template('parent_secret.html',title='Parent login code',value=cipher().decrypt(row.encrypted).decode(),remaining=max(0,int(row.expires-now())),is_link=False)
    @bp.get('/links')
    def links():
        rows,page,total=pagination(selection());latest={}
        for row in Challenge.query.filter_by(kind='link').order_by(Challenge.created).all():latest[row.family_id]=row
        return render_template('parents.html',title='Parents App Login Links',tab='links',rows=rows,page=page,total=total,latest=latest,status=status)
    @bp.post('/links/<int:fid>')
    def link_action(fid):
        family(fid);action=request.form.get('action')
        if action=='revoke':
            account=db.session.get(Account,fid)
            if account:account.version+=1
            Challenge.query.filter_by(family_id=fid,used=0,replaced=False).update({'replaced':True})
            audit('Revoke parent sessions',family_id=fid);db.session.commit();flash('Existing parent sessions and unused credentials revoked.','success');return redirect(url_for('parents.links'))
        if action=='cancel':
            Challenge.query.filter_by(family_id=fid,kind='link',used=0,replaced=False).update({'replaced':True});audit('Cancel parent login links',family_id=fid);db.session.commit();flash('Unused links cancelled.','success');return redirect(url_for('parents.links'))
        if action not in ('issue','qr'):raise ValueError('Choose a link action.')
        school=getattr(g,'school_identity',None)
        if not school or school.get('demo'):raise ValueError('Use a private institute to issue a parent link.')
        row,value=issue(fid,'link');audit('Issue parent login link',family_id=fid,challenge_id=row.id);db.session.commit()
        # Fragment keeps the secret out of HTTP URLs, proxy logs and Referer headers.
        target=url_for('parent_portal.enter',code=school['code'],_external=True)+'#'+row.id+'.'+value
        return render_template('parent_secret.html',title='One-time parent login link',value=target,remaining=600,is_link=True,qr_url=url_for('parents.qr',cid=row.id))
    @bp.get('/links/<cid>/qr')
    def qr(cid):
        row=db.get_or_404(Challenge,cid)
        if row.kind!='link' or status(row)!='Waiting for parent':abort(404)
        school=getattr(g,'school_identity',None)
        if not school or school.get('demo'):abort(403)
        value=cipher().decrypt(row.encrypted).decode();target=url_for('parent_portal.enter',code=school['code'],_external=True)+'#'+row.id+'.'+value
        import qrcode
        stream=io.BytesIO();qrcode.make(target).save(stream,format='PNG');stream.seek(0);audit('Print parent login QR',challenge_id=cid,family_id=row.family_id);db.session.commit()
        return send_file(stream,mimetype='image/png')
    @bp.route('/privileges',methods=['GET','POST'])
    def privileges():
        cfg=policy();data=dict(cfg.data) if cfg else {};tab=request.args.get('tab','rules');months=pending();manage=None
        if request.args.get('student'):
            if not request.args['student'].isdigit():abort(404)
            manage=next(((s,d,a) for s,d,a in selection() if s.id==int(request.args['student'])),None)
            if not manage:abort(404)
        if request.method=='POST':
            if request.form.get('version')!=str(cfg.version if cfg else 0):raise ValueError('Parent settings changed. Reload first.')
            action=request.form.get('action');rules={k:dict(v) for k,v in data.get('rules',{}).items()};overrides={k:dict(v) for k,v in data.get('overrides',{}).items()}
            if action=='rules':
                campus=request.form.get('campus','')
                if campus and campus not in campuses():raise ValueError('Choose a configured campus.')
                updated={}
                for feature,_ in FEATURES:
                    bands={}
                    for band in ('1','2','3'):
                        mode=request.form.get(feature+'_'+band,'allow')
                        if mode not in MODES or feature in ALWAYS and mode!='allow':raise ValueError('Choose valid rules; fee details, pickup and help must remain accessible.')
                        if mode!='allow':bands[band]=mode
                    if bands:updated[feature]=bands
                rules[campus]=updated
            elif action in ('student','clear'):
                sid=request.form.get('student_id','')
                if not sid.isdigit() or not any(s.id==int(sid) for s,_,_ in selection()):raise ValueError('Choose an available student.')
                if action=='clear':overrides.pop(sid,None)
                else:
                    updated={}
                    for feature,_ in FEATURES:
                        mode=request.form.get(feature+'_mode','follow');note=request.form.get(feature+'_note','').strip();until=request.form.get(feature+'_until','')
                        if mode not in MODES|{'follow'} or feature in ALWAYS and mode not in ('allow','follow') or len(note)>1000:raise ValueError('Check student access settings.')
                        if until:
                            try:day=date.fromisoformat(until)
                            except ValueError:raise ValueError('Choose a valid expiry date.')
                            if day<today():raise ValueError('Override expiry must be today or later.')
                        if mode!='follow':updated[feature]=dict(mode=mode,note=note,until=until)
                    overrides[sid]=updated
            else:raise ValueError('Choose a settings action.')
            if cfg:cfg.data=dict(rules=rules,overrides=overrides)
            else:cfg=Policy(id=1,data=dict(rules=rules,overrides=overrides));db.session.add(cfg)
            audit('Update parent privileges',action_kind=action);db.session.commit();flash('Parent access settings saved.','success');return redirect(url_for('parents.privileges',tab='students' if action!='rules' else 'rules'))
        campus=request.args.get('campus','')
        if campus and campus not in campuses():raise ValueError('Choose a configured campus.')
        matching=selection();show=request.args.get('show','all')
        if show not in ('all','restricted','full'):raise ValueError('Choose a valid access filter.')
        if show!='all':
            matching=[row for row in matching if any(access(row[0].id,row[1].get('campus',''),key,months.get(row[0].id,0))['effective']!='allow' for key,_ in FEATURES)==(show=='restricted')]
        rows,page,total=pagination(matching)
        return render_template('parents.html',title='Parents App Privileges',tab='privileges',priv_tab=tab,features=FEATURES,always=ALWAYS,campuses=campuses(),campus=campus,rules=data.get('rules',{}).get(campus,{}),overrides=data.get('overrides',{}),version=cfg.version if cfg else 0,rows=rows,page=page,total=total,months=months,manage=manage,access=access)

    @public.before_request
    def public_scope():
        code=(request.view_args or {}).get('code','').upper();School=app.extensions['identity_models']['institute']
        school=School.query.filter_by(code=code,active=True).first_or_404()
        g.parent_school=school;g.institute_engine=app.extensions['identity_helpers']['engine'](school.id);db.session.remove()
        csrf()
        if request.method=='POST':app.extensions['admission_capacity']['lock']()
    def principal():
        school=g.parent_school
        if session.get('parent_scope')!=school.storage_key or session.get('parent_expiry',0)<=now():return None
        account=db.session.get(Account,session.get('parent_family'))
        if not account or account.version!=session.get('parent_version'):return None
        g.parent_actor=dict(kind='Parent',id=account.family_id,label='Family #'+str(account.family_id))
        return db.session.get(rm['family'],account.family_id)
    def sign_in(row):
        account=db.session.get(Account,row.family_id)
        if not account:account=Account(family_id=row.family_id,version=1);db.session.add(account)
        account.last_used=now();g.parent_actor=dict(kind='Parent',id=row.family_id,label='Family #'+str(row.family_id));db.session.flush();audit('Parent signed in',family_id=row.family_id,challenge_id=row.id);db.session.commit()
        session.clear();session.update(parent_scope=g.parent_school.storage_key,parent_family=account.family_id,parent_version=account.version,parent_expiry=now()+28800,record_csrf=secrets.token_urlsafe(32))
        return redirect(url_for('parent_portal.home',code=g.parent_school.code))
    def consume(cid,value,kind):
        row=db.session.get(Challenge,cid)
        if not row or row.kind!=kind:return None
        row.attempts+=1
        valid=row.attempts<=5 and row.expires>now() and not row.used and not row.replaced and hmac.compare_digest(row.digest,digest(cid,value))
        if not valid:db.session.commit();return None
        family(row.family_id)
        # Every public POST holds the tenant write gate until commit; concurrent
        # redemption cannot consume the same challenge twice.
        row.used=now();return row
    @public.route('/login',methods=['GET','POST'])
    def login(code):
        challenge='';error=''
        if request.method=='POST':
            rate('ip:'+request.remote_addr,30)
            action=request.form.get('action')
            if action=='request':
                raw=phone(request.form.get('phone',''));rate('phone:'+raw,5)
                matches=[f for f in rm['family'].query.all() if len(raw)>=10 and raw in {phone(f.data.get(k)) for k in ('phone','mother_phone','whatsapp')}]
                challenge=secrets.token_urlsafe(32)
                if len(matches)==1 and rm['student'].query.join(Student,Student.id==rm['student'].student_id).filter(rm['student'].family_id==matches[0].id,Student.status=='Active').first():
                    row,_=issue(matches[0].id,'otp');challenge=row.id;audit('Parent requested login code',family_id=row.family_id,challenge_id=row.id)
                db.session.commit();error='If your contact matches one active family, the school office can verify your identity and provide the code. No automatic SMS is sent.'
            elif action=='verify':
                challenge=request.form.get('challenge','')[:43];row=consume(challenge,request.form.get('otp','')[:10],'otp')
                if row:return sign_in(row)
                db.session.commit();error='This code is invalid, expired, replaced or already used.'
            else:abort(400)
        return render_template('parent_portal.html',title='Parent sign in',view='login',school=g.parent_school,challenge=challenge,error=error)
    @public.route('/enter',methods=['GET','POST'])
    def enter(code):
        error=''
        if request.method=='POST':
            rate('link:'+request.remote_addr,30);raw=request.form.get('credential','')
            parts=raw.split('.',1)
            row=consume(parts[0],parts[1],'link') if len(parts)==2 and len(raw)<100 else None
            if row:return sign_in(row)
            db.session.commit();error='This link is invalid, expired, cancelled or already used.'
        return render_template('parent_portal.html',title='One-time parent login',view='enter',school=g.parent_school,error=error)
    @public.post('/logout')
    def logout(code):session.clear();return redirect(url_for('parent_portal.login',code=code))
    @public.get('')
    def home(code):
        f=principal()
        if not f:return redirect(url_for('parent_portal.login',code=code))
        rows=app.extensions['record_helpers']['read_many']('student',Student.query.join(rm['student'],rm['student'].student_id==Student.id).filter(rm['student'].family_id==f.id,Student.status=='Active').order_by(Student.name).all())
        return render_template('parent_portal.html',title='Parent Portal',view='home',school=g.parent_school,children=rows)
    @public.get('/students/<int:sid>/<feature>')
    def feature(code,sid,feature):
        if feature not in dict(FEATURES):abort(404)
        f=principal()
        if not f:return redirect(url_for('parent_portal.login',code=code))
        student=Student.query.join(rm['student'],rm['student'].student_id==Student.id).filter(Student.id==sid,rm['student'].family_id==f.id,Student.status=='Active').first_or_404()
        data=app.extensions['record_helpers']['read_many']('student',[student])[0][1];decision=access(sid,data.get('campus',''),feature)
        if decision['effective']=='block':return render_template('parent_portal.html',title=dict(FEATURES)[feature],view='blocked',school=g.parent_school,student=student),403
        warn=decision['effective']=='warn';content=[];label=dict(FEATURES)[feature]
        if feature=='fees':content=[dict(title=b.month,body='Payable Rs '+format(b.total/100,'.2f')+' · Paid Rs '+format(b.paid/100,'.2f')+' · Remaining Rs '+format(b.remaining/100,'.2f')) for b in Bill.query.filter_by(student_id=sid).order_by(Bill.month.desc()).all()]
        elif feature in ('notice','diary'):
            Entry=app.extensions['student_extras_models']['entry'];day=today()
            for e in Entry.query.filter(Entry.campus.in_(['',data.get('campus','')]),Entry.kind==('notices' if feature=='notice' else 'diary')).order_by(Entry.starts.desc()).all():
                if feature=='notice' and not(e.starts<=day<=e.ends and (e.data.get('all_students') or student.class_name in e.data.get('classes',[]))):continue
                if feature=='diary' and not(e.starts<=day and e.data.get('class_name')==student.class_name and e.data.get('section')==data.get('section')):continue
                attachments=[]
                if feature=='notice':
                    files=app.extensions['student_extras_models']['attachment'].query.filter_by(entry_id=e.id).all()
                    attachments=[dict(name=a.filename,url=url_for('parent_portal.notice_file',code=code,sid=sid,entry_id=e.id,aid=a.id)) for a in files]
                    from sqlalchemy.dialects.postgresql import insert as pg_insert
                    from sqlalchemy.dialects.sqlite import insert as sqlite_insert
                    insert=pg_insert if db.session.get_bind(mapper=Seen.__mapper__).dialect.name=='postgresql' else sqlite_insert
                    db.session.execute(insert(Seen).values(entry_id=e.id,student_id=sid,family_id=f.id,seen=now()).on_conflict_do_nothing(index_elements=['entry_id','student_id','family_id']))
                content.append(dict(title=e.title,body=e.body,attachments=attachments))
            if feature=='notice':db.session.commit()
        elif feature=='attendance':
            Daily=app.extensions['ops_models']['daily'];content=[dict(title=str(r.day),body=r.status) for r in Daily.query.filter_by(kind='student',person_id=sid).order_by(Daily.day.desc()).limit(60).all()]
        elif feature=='profile':content=[dict(title=student.name,body=student.class_name+' / '+data.get('section',''))]
        elif feature in ('help','pickup'):content=[dict(title='Contact the school office',body='Ask the office for help or pickup arrangements. This page always remains accessible.')]
        else:content=[dict(title='No parent records published',body='This feature has no published parent content yet.')]
        return render_template('parent_portal.html',title=label,view='feature',school=g.parent_school,student=student,content=content,warn=warn)
    @public.get('/students/<int:sid>/notices/<int:entry_id>/files/<int:aid>')
    def notice_file(code,sid,entry_id,aid):
        f=principal()
        if not f:return redirect(url_for('parent_portal.login',code=code))
        student=Student.query.join(rm['student'],rm['student'].student_id==Student.id).filter(Student.id==sid,rm['student'].family_id==f.id,Student.status=='Active').first_or_404()
        d=app.extensions['record_helpers']['read_many']('student',[student])[0][1]
        e=db.get_or_404(app.extensions['student_extras_models']['entry'],entry_id)
        if e.kind!='notices' or e.campus not in ('',d.get('campus','')) or not(e.starts<=today()<=e.ends) or not(e.data.get('all_students') or student.class_name in e.data.get('classes',[])):abort(404)
        if access(sid,d.get('campus',''),'notice')['effective']=='block':abort(403)
        a=app.extensions['student_extras_models']['attachment'].query.filter_by(id=aid,entry_id=e.id).first_or_404()
        audit('Parent downloaded notice attachment',family_id=f.id,student_id=sid,entry_id=e.id);db.session.commit()
        response=send_file(io.BytesIO(a.content),mimetype=a.mime,download_name=a.filename,as_attachment=True)
        response.headers['Content-Security-Policy']="default-src 'none'; sandbox"
        return response
    @public.after_request
    def private_headers(response):
        response.headers['Cache-Control']='no-store';response.headers['Referrer-Policy']='no-referrer';return response
    app.register_blueprint(bp);app.register_blueprint(public)
