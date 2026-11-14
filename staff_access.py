"""Institute staff accounts and default-deny Phase-1 route permissions."""
import hmac,re,secrets,hashlib,json
from datetime import date,datetime,timezone
from zoneinfo import ZoneInfo
from flask import Blueprint,abort,flash,g,has_request_context,redirect,render_template,request,session,url_for
from sqlalchemy import event,select,or_,cast,Integer,inspect
from sqlalchemy.orm import with_loader_criteria
from sqlalchemy.exc import IntegrityError,OperationalError
from sqlalchemy.orm.exc import StaleDataError
from werkzeug.security import check_password_hash,generate_password_hash
from identity import InstituteSession
from werkzeug.datastructures import MultiDict

MODULES={'messages':'Internal Messages','apps':'App Links','widgets':'Widgets','dashboard':'Dashboard','admissions':'Admissions','fees':'Student fees','exam':'Examination','attendance':'Attendance','hrm':'Employees / HRM','payroll':'Payroll','certificates':'Certificates','parents':'Parents App','ptm':'Parent Teacher Meetings','student_extras':'Student Extras','communication':'Communication requests','requisitions':'Requisitions','finance':'Finance accounting','core':'Core Settings','access':'Users & Privileges','logs':'User Logging'}
ACTIONS=('view','create','update','delete','approve','export','print','pay','reverse','import')
PERMISSIONS={m+'.'+a:label+' · '+a.title() for m,label in MODULES.items() for a in ACTIONS}
PERMISSIONS['requisitions.manage']='Requisitions · Management reports'
PERMISSIONS['widgets.manage']='Widgets · Manage role visibility'
PERMISSIONS['parents.codes']='Parents App · View sensitive login codes'
PERMISSIONS['attendance.self']='My Geo Attendance · self only'
PERMISSIONS['messages.manage']='Messages · Institute settings'
PERMISSIONS['messages.report']='Messages · Campus reports'
ACCOUNTS=('Cash in Hand','Cash at Bank','Petty Cash','Accounts Receivable','Fee Receivable','Discounts','Bad Debts')
ROLES=('Super Admin','Admin','User','Teacher')

def configure_staff_access(app,db,Student,Employee):
    bp=Blueprint('staff_access',__name__,url_prefix='/workspace/core/users')
    rm=app.extensions['record_models'];ops=app.extensions['ops_models'];Item=app.extensions['school_settings_models']['item'];Config=app.extensions['school_settings_models']['setting'];Audit=ops['audit']
    class Staff(db.Model):
        __tablename__='staff_account'
        id=db.Column(db.Integer,primary_key=True)
        employee_id=db.Column(db.Integer,db.ForeignKey('employee.id'),unique=True,nullable=False)
        username=db.Column(db.String(120),nullable=False,unique=True)
        email=db.Column(db.String(254),unique=True)
        password_hash=db.Column(db.String(300),nullable=False)
        active=db.Column(db.Boolean,nullable=False,default=True)
        data=db.Column(db.JSON,nullable=False,default=dict)
        created=db.Column(db.DateTime,nullable=False,default=lambda:datetime.now(timezone.utc))
        version=db.Column(db.Integer,nullable=False,default=1)
        __mapper_args__={'version_id_col':version}
    app.extensions['staff_account_model']=Staff
    dummy=generate_password_hash(secrets.token_urlsafe(32))
    def campuses():
        # GET-only, request-local cache: all grant/source checks share one
        # campus catalogue read. Mutations always re-read inside their lock.
        if has_request_context() and request.method=='GET' and hasattr(request,'staff_campus_catalog'):
            return list(request.staff_campus_catalog)
        table=rm['settings'].__table__
        values=sorted({r[0] for r in db.session.execute(select(table.c.value).where(table.c.category=='campus')).all()})
        if has_request_context() and request.method=='GET':request.staff_campus_catalog=values
        return values
    def accounts():return sorted(set(ACCOUNTS)|{x[0] for x in db.session.query(ops['receipt'].account).distinct().all()})
    def resolve(sid,version):
        try:row=db.session.get(Staff,sid)
        except OperationalError:db.session.rollback();return None
        if not row or not row.active or row.version!=version:return None
        employee=db.session.get(Employee,row.employee_id)
        return row if employee and employee.status=='Active' else None
    def authenticate(school,login,password):
        g.institute_engine=app.extensions['identity_helpers']['engine'](school.id);db.session.remove()
        try:row=Staff.query.filter(or_(Staff.username==login,Staff.email==login)).first()
        except OperationalError:db.session.rollback();check_password_hash(dummy,password[:129]);return None
        valid=check_password_hash(row.password_hash if row else dummy,password[:129])
        if not row or not valid or len(password)>128 or not resolve(row.id,row.version):return None
        return dict(id=row.id,version=row.version,username=row.username)
    def grant(row,code):
        return set(row.data.get('campuses',[]))&set(row.data.get('permissions',{}).get(code,[]))&set(campuses())
    def is_owner():return bool(session.get('owner_id')) and getattr(g,'staff_principal',None) is None
    def can_manage():
        principal=getattr(g,'staff_principal',None)
        return principal is None or grant(principal,'access.update')==set(campuses())
    def commit():
        try:db.session.commit()
        except (IntegrityError,StaleDataError):db.session.rollback();raise ValueError('An account changed or the username/email/employee is already linked. Reload before saving.')
    def check_version(row):
        if request.form.get('version')!=str(row.version if row else 0):raise ValueError('This account changed. Reload first.')
    def staff_snapshot(row):
        return dict(row.data,username=row.username,email=row.email,employee_id=row.employee_id,active=row.active) if row else {}
    def linked_employee(value):
        if not value.isdigit():raise ValueError('Choose an active HRM employee.')
        e=db.session.get(Employee,int(value))
        if not e or e.status!='Active':raise ValueError('Choose an active HRM employee.')
        return e
    def policy():
        scope=list(dict.fromkeys(request.form.getlist('campuses')));cash=list(dict.fromkeys(request.form.getlist('accounts')))
        if any(c not in campuses() for c in scope) or any(a not in accounts() for a in cash):raise ValueError('Choose configured campuses and receiving accounts.')
        mode=request.form.get('payment_mode','none');raw=request.form.get('payment_days','0')
        if mode not in ('none','day','month','custom') or not raw.isdigit() or int(raw)>3660:raise ValueError('Choose a valid payment-date rule and 0–3,660 days.')
        return dict(campuses=scope,accounts=cash,payment_mode=mode,payment_days=int(raw) if mode=='custom' else 0,two_step=request.form.get('two_step')=='1')
    def role_titles():
        row=db.session.get(Config,'staff-role-titles');return {r:(row.data.get(r,r) if row else r) for r in ROLES}
    def assert_delegation(data,target=None):
        p=getattr(g,'staff_principal',None)
        if p is None:return
        if target and (target.id==p.id or any(not set(v)<=grant(p,k) for k,v in target.data.get('permissions',{}).items())):abort(403,'A delegated administrator cannot alter their own or a more privileged account.')
        if not set(data.get('campuses',[]))<=set(p.data.get('campuses',[])) or not set(data.get('accounts',[]))<=set(p.data.get('accounts',[])):abort(403)
        if any(not set(v)<=grant(p,k) for k,v in data.get('permissions',{}).items()):abort(403,'You cannot grant access you do not hold.')
    @bp.before_request
    def protect():
        if request.method=='POST':
            if not request.form.get('_csrf') or not hmac.compare_digest(request.form['_csrf'],session.get('record_csrf','')):abort(400,'Reload the account form.')
            app.extensions['admission_capacity']['lock']()
    @bp.errorhandler(ValueError)
    def invalid(error):db.session.rollback();return render_template('operation_error.html',title='Check staff access',error=str(error)),422
    @bp.get('')
    def index():
        q=request.args.get('q','').strip().casefold();status=request.args.get('status','');role=request.args.get('role','')
        if len(q)>160 or status not in ('','active','inactive') or (role and role not in ROLES):raise ValueError('Choose valid directory filters.')
        query=Staff.query
        if q:query=query.filter(or_(Staff.username.contains(q,autoescape=True),Staff.email.contains(q,autoescape=True)))
        if status:query=query.filter_by(active=status=='active')
        rows=query.order_by(Staff.username).all();rows=[r for r in rows if not role or r.data.get('role')==role]
        prefs=grid_preferences('users');cols=request.args.getlist('columns') or prefs.get('columns') or GRID_COLUMNS['users']
        if any(c not in GRID_COLUMNS['users'] for c in cols):raise ValueError('Choose valid staff columns.')
        try:size=int(request.args.get('size',prefs.get('size',50)));page=int(request.args.get('page',1))
        except ValueError:raise ValueError('Choose valid pagination.')
        if size not in (25,50,100) or page<1:raise ValueError('Choose 25, 50 or 100 rows and a valid page.')
        total=len(rows);pages=max(1,(total+size-1)//size);page=min(page,pages)
        employees={e.id:e for e in Employee.query.all()}
        if request.args.get('export')=='xlsx':
            from report_exports import report_xlsx
            labels=dict(username='Username',email='Login email',employee='Employee',status='Status',role='Role');values=[dict(username=r.username,email=r.email or '',employee=employees[r.employee_id].name if r.employee_id in employees else 'Unavailable',status='Active' if r.active else 'Inactive',role=role_titles().get(r.data.get('role'),'User')) for r in rows]
            return report_xlsx([labels[c] for c in cols],[[r[c] for c in cols] for r in values],'staff-directory')
        return render_template('staff_directory.html',title='Users & Privileges',rows=rows[(page-1)*size:page*size],employees=employees,roles=role_titles(),total=total,pages=pages,page=page,size=size,cols=cols)
    @bp.route('/new',methods=['GET','POST'])
    @bp.route('/<int:sid>',methods=['GET','POST'])
    def editor(sid=None):
        row=db.get_or_404(Staff,sid) if sid else None
        if request.method=='POST':
            check_version(row);action=request.form.get('action','profile');before=staff_snapshot(row)
            if action=='password':
                if not row:abort(404)
                p=getattr(g,'staff_principal',None)
                if p and p.id==row.id and not check_password_hash(row.password_hash,request.form.get('current_password','')):raise ValueError('The current password is incorrect.')
                if p and p.id!=row.id:assert_delegation(row.data,row)
                password=request.form.get('password','')
                if not 10<=len(password)<=128 or password!=request.form.get('confirm_password'):raise ValueError('Use matching passwords of 10–128 characters.')
                row.password_hash=generate_password_hash(password)
            elif action=='permissions':
                if not row:abort(404)
                permissions={}
                for code in PERMISSIONS:
                    values=list(dict.fromkeys(request.form.getlist('perm_'+code)))
                    if any(v not in row.data.get('campuses',[]) for v in values):raise ValueError('Permissions must use allowed campuses.')
                    if values:permissions[code]=values
                updated={**row.data,'permissions':permissions};assert_delegation(updated,row);row.data=updated
            elif action in ('profile','access'):
                data=policy();data={**(row.data if row else {}),**data}
                if action=='profile':
                    employee=linked_employee(request.form.get('employee_id',''));username=request.form.get('username','').strip().casefold();email=request.form.get('email','').strip().casefold();role=request.form.get('role','User')
                    if not re.fullmatch(r'[a-z0-9_.@+-]{3,120}',username) or role not in ROLES or (email and not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',email)):raise ValueError('Enter a valid username, optional email and role.')
                    identifiers=[v for v in (username,email) if v]
                    if Staff.query.filter(or_(Staff.username.in_(identifiers),Staff.email.in_(identifiers))).filter(Staff.id!=(row.id if row else 0)).first():raise ValueError('A username or login email is already used by another staff account.')
                    if len(email)>254 or len(request.form.get('contact',''))>40:raise ValueError('Check email/contact length.')
                    if any(x.email in (username,email) for x in app.extensions['identity_models']['owner'].query.filter_by(institute_id=session.get('institute_id')).all()):raise ValueError('The primary owner login is reserved.')
                    data.update(role=role,designation=request.form.get('designation','')[:160],contact=request.form.get('contact','')[:40],apps=[a for a in ('owner','teacher','parent','sms') if request.form.get('app_'+a)=='1'],account_owner=request.form.get('account_owner')=='1')
                    active=request.form.get('active')=='1'
                    if not row:
                        password=request.form.get('password','')
                        if not 10<=len(password)<=128:raise ValueError('Use a password of 10–128 characters.')
                        row=Staff(employee_id=employee.id,username=username,email=email or None,password_hash=generate_password_hash(password),active=active,data={});db.session.add(row)
                        data['permissions']={}
                    else:assert_delegation(data,row)
                    row.employee_id=employee.id;row.username=username;row.email=email or None;row.active=active
                elif not row:abort(404)
                data['permissions']={k:[c for c in v if c in data['campuses']] for k,v in data.get('permissions',{}).items()};assert_delegation(data,row if sid else None);row.data=data
            else:raise ValueError('Choose a supported staff-account action.')
            db.session.flush();db.session.add(Audit(action=('Create staff account' if not sid else 'Change staff '+('privileges' if action=='permissions' else action)),data=dict(staff_id=row.id,before=before if action!='password' else {},after=staff_snapshot(row) if action!='password' else {})));commit();flash('Account saved. Changed access invalidates prior staff sessions.','success');return redirect(url_for('staff_access.editor',sid=row.id))
        activity=Audit.query.filter(Audit.data['staff_id'].as_integer()==row.id).order_by(Audit.created,Audit.id).all() if row else []
        return render_template('staff_editor.html',activity=activity,title='Manage Staff User' if row else 'Create Staff User',row=row,employees=Employee.query.filter_by(status='Active').order_by(Employee.name).all(),campuses=campuses(),accounts=accounts(),roles=role_titles(),permissions=PERMISSIONS,modules=MODULES)
    @bp.route('/roles',methods=['GET','POST'])
    def roles():
        row=db.session.get(Config,'staff-role-titles')
        if request.method=='POST':
            check_version(row);before=dict(row.data) if row else {};titles={k:request.form.get(k,'').strip() for k in ROLES}
            if any(not v or len(v)>80 for v in titles.values()) or len(set(titles.values()))!=len(titles):raise ValueError('Use unique role titles of 1–80 characters.')
            if row:row.data=titles
            else:db.session.add(Config(key='staff-role-titles',data=titles))
            db.session.add(Audit(action='Change staff role titles',data={'before':before,'after':titles}));commit();return redirect(url_for('staff_access.roles'))
        return render_template('staff_roles.html',title='Role Titles',row=row,roles=role_titles())
    @bp.route('/copy-grid',methods=['GET','POST'])
    def copy_grid():
        if request.method=='POST':
            source=request.form.get('source','');target=request.form.get('target','')
            if not source.isdigit() or not target.isdigit() or source==target:raise ValueError('Choose different source and target users.')
            a=db.get_or_404(Staff,int(source));b=db.get_or_404(Staff,int(target));check_version(b)
            if request.form.get('source_version')!=str(a.version):raise ValueError('The source user changed. Reload first.')
            data={**b.data,'grid_settings':dict(a.data.get('grid_settings',{}))};assert_delegation(data,b);b.data=data
            db.session.add(Audit(action='Copy grid settings',data=dict(source=a.id,target=b.id)));commit();return redirect(url_for('staff_access.copy_grid'))
        return render_template('staff_copy_grid.html',title='Copy Grid Settings',rows=Staff.query.order_by(Staff.username).all())
    @bp.route('/my-password',methods=['GET','POST'])
    def my_password():
        principal=getattr(g,'staff_principal',None)
        owner=db.session.get(app.extensions['identity_models']['owner'],session['owner_id']) if session.get('owner_id') else None
        row=principal or owner
        if not row:abort(403,'Sign in to a private institute account to change its password.')
        if request.method=='POST':
            db.session.refresh(row)
            if session.get('staff_version' if principal else 'owner_version')!=row.version:abort(403,'Your account changed. Sign in again.')
            if not check_password_hash(row.password_hash,request.form.get('current_password','')):raise ValueError('The current password is incorrect.')
            password=request.form.get('password','')
            if not 10<=len(password)<=128 or password!=request.form.get('confirm_password'):raise ValueError('Use matching passwords of 10–128 characters.')
            row.password_hash=generate_password_hash(password)
            if owner:owner.version+=1
            db.session.add(Audit(action='Change own password',data={'staff_id':principal.id if principal else None}));commit()
            session['staff_version' if principal else 'owner_version']=row.version
            flash('Password changed. Other existing sign-ins have expired.','success');return redirect(url_for('staff_access.my_password'))
        return render_template('staff_my_password.html',title='My Password')
    GRID_COLUMNS={'logs':['severity','summary','record','action','area','actor','when'],'certificates':['id','campus','name','created','updated','creator','updater'],'users':['username','email','employee','status','role']}
    def grid_preferences(key):
        principal=getattr(g,'staff_principal',None)
        if principal:return principal.data.get('grid_settings',{}).get(key,{})
        return session.get('grid_settings',{}).get(key,{})
    @bp.route('/my-grids',methods=['GET','POST'])
    def my_grids():
        principal=getattr(g,'staff_principal',None)
        if request.method=='POST':
            key=request.form.get('grid');cols=list(dict.fromkeys(request.form.getlist('columns')));size=request.form.get('size','50')
            if key not in GRID_COLUMNS or not cols or any(c not in GRID_COLUMNS[key] for c in cols) or size not in ('25','50','100'):raise ValueError('Choose a grid, valid columns and row count.')
            saved={**(principal.data.get('grid_settings',{}) if principal else session.get('grid_settings',{})),key:dict(columns=cols,size=int(size))}
            if principal:
                principal.data={**principal.data,'grid_settings':saved};commit();session['staff_version']=principal.version
            else:session['grid_settings']=saved
            flash('Grid preferences saved.','success');return redirect(url_for('staff_access.my_grids'))
        return render_template('staff_my_grids.html',title='My Grid Settings',grids=GRID_COLUMNS,preferences={k:grid_preferences(k) for k in GRID_COLUMNS})
    def payment_policy(p, form, scopes,permission='fees.pay'):
        if not scopes <= grant(p,permission):abort(403,'The requester no longer has payment access to every selected campus.')
        account=form.get('account','')
        if not account or account not in p.data.get('accounts',[]):abort(403,'This receiving account is not granted.')
        from operations import money
        if any(k.startswith('discount_') and k!='discount_account' and money(v)>0 for k,v in form.items()) and form.get('discount_account','Discounts') not in p.data.get('accounts',[]):abort(403,'The discount account is not granted.')
        try:paid=date.fromisoformat(form.get('paid_date',''))
        except ValueError:raise ValueError('Choose the payment date explicitly.')
        today=datetime.now(ZoneInfo('Asia/Karachi')).date();mode=p.data.get('payment_mode','none')
        if paid>today or (mode=='day' and paid!=today) or (mode=='month' and paid.strftime('%Y-%m')!=today.strftime('%Y-%m')) or (mode=='custom' and (today-paid).days>p.data.get('payment_days',0)):abort(403,'This payment date is outside the staff account limit.')
    def payment_snapshot(form, endpoint):
        from operations import money
        Bill=ops['bill'];selected=[];scope=set()
        for key,value in form.items():
            match=re.fullmatch(r'(amount|discount)_(\d+)',key)
            if not match or not money(value):continue
            if endpoint=='ops.batch_payment' and match[1]=='discount':raise ValueError('Use the individual challan form for discounts.')
            bid=int(match[2])
            if bid in selected:continue
            bill=db.session.get(Bill,bid)
            if not bill:abort(403,'A selected challan is outside the available campus scope.')
            student=db.get_or_404(Student,bill.student_id);detail=rm['student'].query.filter_by(student_id=student.id).first();campus=(detail.data if detail else {}).get('campus','')
            if not campus:raise ValueError('Set the student campus before requesting approval.')
            if endpoint=='ops.pay':
                if str(student.id)!=form.get('student_id') or (form.get('mode','current')=='current' and str(bill.id)!=form.get('bill_id')):raise ValueError('A selected amount is outside this payment form.')
            elif request.path.endswith('family-payment') or form.get('_family')=='1':
                if str((detail.data if detail else {}).get('family_no',''))!=form.get('number',''):raise ValueError('A selected challan is outside this family.')
            else:
                lookup=form.get('lookup','sid');actual=str(bill.id) if lookup=='challan' else str((detail.data if detail else {}).get('roll_no','')) if lookup=='roll' else str(student.id)
                if actual!=form.get('number',''):raise ValueError('A selected challan is outside this lookup.')
            amount=money(form.get('amount_'+str(bid)));discount=money(form.get('discount_'+str(bid)))
            if bill.frozen or amount+discount>bill.remaining:raise ValueError('Unfreeze challans and check current balances before requesting approval.')
            selected.append(bid);scope.add(campus)
        if not selected:raise ValueError('Enter a payment or discount amount.')
        return [dict(id=b.id,version=b.version,paid=b.paid,discount=b.discount,lines=b.lines,student_id=b.student_id) for b in Bill.query.filter(Bill.id.in_(selected)).order_by(Bill.id).all()],scope
    def queue_payment(p):
        protect()
        form=request.form.to_dict();form.pop('_csrf',None)
        if request.path.endswith('family-payment'):form['_family']='1'
        if not re.fullmatch(r'[a-zA-Z0-9_-]{20,100}',form.get('token','')):raise ValueError('Reload the payment form.')
        snapshot,scope=payment_snapshot(form,request.endpoint);payment_policy(p,form,scope)
        Workflow=ops['workflow'];digest=hashlib.sha256((str(p.id)+':'+form['token']).encode()).hexdigest()
        existing=Workflow.query.filter_by(kind='staff-payment-approval').filter(Workflow.data['dedupe'].as_string()==digest).first()
        if existing:
            if existing.status!='Pending':raise ValueError('This request has already been decided. Reload the payment form.')
        else:
            row=Workflow(kind='staff-payment-approval',status='Pending',data=dict(requester=p.id,requester_name=p.username,requester_version=p.version,endpoint=request.endpoint,path=request.path,form=form,bills=snapshot,campus=sorted(scope)[0],campuses=sorted(scope),dedupe=digest))
            db.session.add(row);db.session.flush();db.session.add(Audit(action='Request fee payment approval',data=dict(request_id=row.id,campus=sorted(scope)[0],bill_ids=[b['id'] for b in snapshot])));commit()
        flash('Payment submitted for approval. No receipt or paid balance is posted until a different authorized user approves.','success')
        return redirect(url_for('staff_access.payment_requests'))
    @bp.route('/payment-requests',methods=['GET','POST'])
    def payment_requests():
        Workflow=ops['workflow'];principal=getattr(g,'staff_principal',None)
        if request.method=='POST':
            rid=request.form.get('id','')
            if not rid.isdigit():raise ValueError('Choose a payment request.')
            row=db.get_or_404(Workflow,int(rid));d=row.data
            if row.kind!='staff-payment-approval' or row.status!='Pending':raise ValueError('This request has already been decided.')
            scope=set(d['campuses'])
            if principal and (principal.id==d['requester'] or not scope<=grant(principal,'fees.approve')):abort(403,'Approval requires a different user with approval access to every selected campus.')
            action=request.form.get('action')
            if action not in ('approve','reject'):raise ValueError('Choose approve or reject.')
            decision=dict(decided_at=datetime.now(timezone.utc).isoformat(),decided_by=principal.username if principal else (getattr(g,'school_identity',None) or {}).get('email','Demo owner'),reason=request.form.get('reason','').strip()[:500])
            if action=='reject':
                row.status='Rejected';row.data={**d,**decision};db.session.add(Audit(action='Reject fee payment request',data=dict(request_id=row.id,campus=d['campus'],reason=decision['reason'])));commit();return redirect(url_for('staff_access.payment_requests'))
            requester=resolve(d['requester'],d['requester_version'])
            if not requester:raise ValueError('The requesting account changed or was disabled. Reject this request and submit a fresh one.')
            form=MultiDict(d['form']);snapshot,current_scope=payment_snapshot(form,d['endpoint'])
            if snapshot!=d['bills'] or current_scope!=scope:raise ValueError('Challan balances or campus changed. Reject this request and submit a fresh one.')
            payment_policy(requester,form,scope)
            if principal:payment_policy(principal,form,scope,'fees.approve')
            if d['endpoint'] not in ('ops.pay','ops.batch_payment') or d['path'] not in ('/workspace/pay','/workspace/direct-payment','/workspace/family-payment'):abort(403)
            row.status='Approved';row.data={**d,**decision};db.session.add(Audit(action='Approve fee payment request',data=dict(request_id=row.id,campus=d['campus'],bill_ids=[b['id'] for b in snapshot])))
            credentials=dict(session);form['_csrf']=session['record_csrf']
            # Reuse the ordinary receipt engine under the shared write gate;
            # its single commit includes the decision, receipts and audit row.
            with app.test_request_context(d['path'],method='POST',data=form):
                session.update(credentials);response=app.make_response(app.view_functions[d['endpoint']]())
                if response.status_code!=302:db.session.rollback();raise ValueError('Payment was not posted. Reload the request.')
            return redirect(url_for('staff_access.payment_requests'))
        rows=Workflow.query.filter_by(kind='staff-payment-approval').order_by(Workflow.id.desc()).all()
        if principal:rows=[r for r in rows if r.data.get('requester')==principal.id or set(r.data.get('campuses',[]))<=grant(principal,'fees.approve')]
        return render_template('staff_payment_requests.html',title='Challan Payment Approvals',rows=rows,principal=principal)
    app.extensions['staff_access_helpers']=dict(resolve=resolve,authenticate=authenticate,grant=grant,campuses=campuses,permissions=PERMISSIONS,grid_preferences=grid_preferences)
    app.register_blueprint(bp)

    def required_permission():
        ep=request.endpoint or '';args=request.view_args or {};area=None
        if ep.startswith('messages.'):
            if ep=='messages.settings':return 'messages.manage'
            if ep=='messages.export_file':return 'messages.export'
            if ep=='messages.report':return 'messages.export' if request.method=='POST' else 'messages.report'
            if ep in ('messages.new','messages.reply','messages.recipients'):return 'messages.create'
            return 'messages.update' if ep in ('messages.status','messages.flag') else 'messages.view'
        if ep in ('challan_branding.student_photo','challan_payment_qr'):return 'fees.print'
        if ep.startswith('school_apps.'):
            return 'apps.'+('view' if request.method=='GET' else 'update')
        if ep.startswith('general_tools.'):
            if ep=='general_tools.app_links':return 'apps.'+('update' if request.method=='POST' else 'view')
            if ep=='general_tools.permissions':return 'widgets.manage'
            return 'widgets.'+('export' if request.args.get('export') else 'view')
        if ep.startswith('parents.'):
            if ep in ('parents.reveal','parents.qr','parents.link_action'):return 'parents.codes'
            return 'parents.'+('export' if request.args.get('export') else 'create' if ep=='parents.invitation' else 'update' if request.method=='POST' else 'view')
        if ep.startswith('ptm.'):
            return 'ptm.'+('export' if request.args.get('export') else 'update' if ep in ('ptm.update','ptm.update_group') else 'create' if request.method=='POST' else 'view')
        if ep.startswith('student_extras.'):
            return 'student_extras.'+('create' if request.method=='POST' else 'view')
        if ep.startswith('fee_ledger.'):
            return 'core.'+('update' if request.method=='POST' else 'view')
        if ep.startswith('daily_snapshots.'):
            return 'finance.'+('create' if request.method=='POST' else 'print' if request.args.get('print')=='1' else 'view')
        if ep.startswith('req_posting.'):
            return 'requisitions.'+('manage' if request.method=='GET' else 'pay' if args.get('kind') in ('issue','reimburse') else 'update')
        if ep.startswith('requisitions.'):
            if ep=='requisitions.settings':return 'core.'+('update' if request.method=='POST' else 'view')
            if ep in ('requisitions.approvals','requisitions.decide'):return 'requisitions.approve'
            if ep in ('requisitions.issue','requisitions.settle','requisitions.reports'):return 'requisitions.print' if request.args.get('print')=='1' else 'requisitions.manage'
            if ep=='requisitions.blocked_posting':return 'requisitions.'+('pay' if request.path.endswith('/issue') else 'update')
            return 'requisitions.'+('create' if ep=='requisitions.mine' and request.method=='POST' else 'update' if ep=='requisitions.cancel' else 'print' if request.args.get('print')=='1' else 'view')
        if ep.startswith('shareholder_posting.'):
            return 'finance.'+('delete' if ep=='shareholder_posting.reverse' and request.method=='POST' else 'create' if request.method=='POST' else 'print' if request.args.get('print')=='1' else 'view')
        if ep.startswith('finance_partners.'):
            return 'finance.'+('create' if ep=='finance_partners.edit' and not args.get('rid') else 'update' if ep=='finance_partners.edit' else 'export' if request.args.get('export') else 'print' if request.args.get('print')=='1' else 'view')
        if ep.startswith('finance_audit.'):
            return 'finance.'+('export' if request.args.get('export') else 'print' if request.args.get('print')=='1' else 'view')
        if ep.startswith('finance_reports.'):
            return 'finance.'+('delete' if ep=='finance_reports.void' else 'update' if ep=='finance_reports.correct' else 'print' if request.args.get('print')=='1' else 'view')
        if ep.startswith('ledger.'):
            return 'finance.'+('create' if request.method=='POST' else 'print' if request.args.get('print')=='1' else 'view')
        if ep.startswith('finance.'):
            return 'finance.'+('print' if ep=='finance.chart' and request.args.get('print')=='1' else 'view' if request.method=='GET' else 'delete' if request.form.get('action')=='delete' else 'create' if ep=='finance.initialize' or not args.get('rid') else 'update')
        if ep=='attendance_controls.self_attendance':return 'attendance.self'
        if ep=='whatsapp_settings.command' and request.form.get('operation')=='send':return 'communication.create'
        if ep.startswith(('whatsapp_settings.','client_subscription.')):
            return 'core.'+('delete' if request.form.get('action')=='delete-provider' or request.form.get('operation')=='account_remove' else 'update' if request.method=='POST' else 'view')
        if ep.startswith('attendance_controls.'):
            return 'core.'+('delete' if ep=='attendance_controls.devices' and request.method=='POST' else 'update' if request.method=='POST' else 'view')
        if ep.startswith('attendance_devices.'):
            area='attendance' if ep in ('attendance_devices.scans','attendance_devices.scanner') else 'core'
            return area+'.'+('export' if request.args.get('export') else 'create' if ep=='attendance_devices.gates' and request.method=='POST' else 'update' if request.method=='POST' else 'view')
        if ep=='staff_access.payment_requests':
            return 'fees.approve' if request.method=='POST' and request.form.get('action') in ('approve','reject') else 'fees.view'
        if ep.startswith('records.'):
            kind=args.get('kind')
            if ep in ('records.settings','records.add_option'):area='core'
            elif ep=='records.salary_handoff':area='payroll'
            elif ep=='records.record_file':
                f=db.session.get(rm['file'],args.get('id'));area='admissions' if f and f.owner_kind=='student' else 'hrm'
            elif ep=='records.family_data':area='admissions'
            else:area='admissions' if kind=='student' else 'hrm' if kind=='employee' else None
        elif ep.startswith('ops.'):
            name=ep.split('.')[1]
            if name=='entry':
                key=args.get('key','');area='dashboard' if key=='dashboard' else 'admissions' if key in ('students','queries','approvals') else 'hrm' if key=='employees' else None
            else:
                area={'dashboard':'dashboard','register':'hrm','approve_students':'admissions','fees':'fees','generate_challans':'fees','pay':'fees','fee_action':'fees','reverse_receipts':'fees','history':'fees','take_attendance':'attendance','attendance_report':'attendance','examination':'exam','assessment_category':'exam','marks':'exam','rolls':'exam','plans':'payroll','payroll':'payroll','lecture_import':'payroll','messages':'communication','message_log':'communication','installment':'fees','batch_payment':'fees','readiness':'dashboard'}.get(name)
                if name=='register' and args.get('kind') in ('increments','advances','loans','lecture-rates','lecture-register'):area='payroll'
        else:
            prefix=ep.split('.')[0]
            area={'dashboard':'dashboard','student_plans':'fees','student_overview':'admissions','admission_limits':'admissions','student_import':'admissions','fee_setup':'core','fee_increments':'fees','yearly_fees':'core','roll_numbers':'core','holiday_calendar':'core','fine_automation':'core','late_fees':'core','attendance_fines':'core','fine_queue':'fees','challan_branding':'core','institute_setup':'core','school_settings':'core','certificates':'certificates','certificate_manager':'certificates','staff_access':'access','user_logging':'logs','payroll_calendar':'payroll','hrm_reports':'hrm','reports':'fees' if args.get('view') and ep.endswith('.fees') else 'attendance' if 'attendance' in ep else 'exam'}.get(prefix)
        if not area:return None
        action='view'
        if request.args.get('export') or ep=='records.export':action='export'
        if request.method=='POST':
            value=request.form.get('action','').split(':')[0]
            if ep=='certificate_manager.delete':action='delete'
            elif ep=='certificate_manager.copy' or (ep in ('certificate_manager.editor','staff_access.editor') and not (args.get('tid') or args.get('sid'))):action='view' if value=='preview' else 'create'
            elif value in ('preview','simulate','review'):action='view'
            elif value in ('approve','allow','reject','refuse','unlock-daily','unlock-monthly'):action='approve'
            elif value in ('delete','remove','undo','cancel'):action='delete'
            elif value in ('pay','paid') or ep in ('ops.pay','ops.batch_payment') or (ep=='ops.payroll' and value=='send'):action='pay'
            elif value in ('reverse','unpay') or ep=='ops.reverse_receipts':action='reverse'
            elif value in ('issue','print','branded','horizontal','vertical','family') or ep.endswith('.qr_print'):action='print'
            elif ep=='records.new_record' or ep.endswith(('.upload','.setup','.new')) or value in ('add-plan','add-year'):action='create'
            elif ep.endswith(('.apply','.lecture_import')):action='import'
            else:action='update'
        return area+'.'+action
    @app.before_request
    def enforce():
        p=getattr(g,'staff_principal',None)
        if p is None:return
        # Static instructions contain no school records and grant no target-page
        # access. Institute authentication above still applies to these GETs.
        if request.blueprint == 'how_to' and request.method in ('GET', 'HEAD'):return
        if request.endpoint in ('staff_access.my_password','staff_access.my_grids','home','favicon','health','static') or request.blueprint in ('identity','mobile_clients'):return
        code=required_permission()
        if not code or not grant(p,code):abort(403,'This action is not granted to this staff account.')
        if request.method=='POST':
            if not request.form.get('_csrf') or not hmac.compare_digest(request.form['_csrf'],session.get('record_csrf','')):abort(400,'Reload this form.')
            app.extensions['admission_capacity']['lock']()
            db.session.refresh(p)
            if not resolve(p.id,session.get('staff_version')) or not grant(p,code):abort(403,'Your access changed. Sign in again.')
        allowed=grant(p,code);g.access_campuses=allowed
        if (code.split('.')[0] in ('core','access','finance') or (request.blueprint=='certificate_manager' and request.method=='POST') or request.endpoint=='whatsapp_settings.command') and allowed!=set(campuses()):abort(403,'Institute-wide settings require this permission for every configured campus.')
        if request.values.get('campus') and request.values['campus'] not in allowed:abort(403,'This campus is not granted for this action.')
        if code.endswith(('.pay','.reverse')):
            for key in ('account','discount_account','credit','debit'):
                value=request.form.get(key)
                if value and value not in p.data.get('accounts',[]):abort(403,'This cash account is not granted.')
            raw=request.form.get('day' if request.blueprint=='req_posting' else 'paid_date','')
            if code.endswith('.pay') and not raw:abort(422,'Choose the payment date explicitly.')
            if raw:
                try:paid=date.fromisoformat(raw)
                except ValueError:abort(422,'Choose a valid payment date.')
                today=datetime.now(ZoneInfo('Asia/Karachi')).date();mode=p.data.get('payment_mode','none')
                if paid>today or (mode=='day' and paid!=today) or (mode=='month' and paid.strftime('%Y-%m')!=today.strftime('%Y-%m')) or (mode=='custom' and (today-paid).days>p.data.get('payment_days',0)):abort(403,'This payment date is outside the staff account limit.')
            if request.endpoint in ('ops.pay','ops.batch_payment'):payment_policy(p,request.form,allowed)
            if p.data.get('two_step') and request.endpoint in ('ops.pay','ops.batch_payment'):return queue_payment(p)
    @event.listens_for(InstituteSession,'do_orm_execute')
    def restrict_rows(execute):
        if not execute.is_orm_statement:return
        if execute.bind_mapper and (execute.bind_mapper.class_ is Staff or execute.bind_mapper.local_table.info.get('identity_control')):return
        if not has_request_context() or getattr(g,'staff_principal',None) is None or getattr(g,'access_campuses',None) is None:return
        allowed=list(g.access_campuses)
        if set(allowed)==set(campuses()):return
        st=Student.__table__;sd=rm['student'].__table__;et=Employee.__table__;ed=rm['employee'].__table__
        student_ids=select(st.c.id).join(sd,sd.c.student_id==st.c.id).where(sd.c.data['campus'].as_string().in_(allowed))
        employee_ids=select(et.c.id).join(ed,ed.c.employee_id==et.c.id).where(ed.c.data['campus'].as_string().in_(allowed))
        campus_model=app.extensions['certificate_models']['campus'];campus_ids=select(campus_model.__table__.c.id).where(campus_model.__table__.c.campus.in_(allowed+['']))
        criteria=[]
        for mapper in list(db.Model.registry.mappers):
            cls=mapper.class_;table=mapper.local_table
            if table.info.get('identity_control') or cls is Staff:continue
            predicate=None
            if cls is Student:predicate=Student.id.in_(student_ids)
            elif cls is Employee:predicate=Employee.id.in_(employee_ids)
            elif cls is rm['family']:predicate=cls.id.in_(select(sd.c.family_id).where(sd.c.data['campus'].as_string().in_(allowed)))
            elif cls is rm['file']:predicate=or_((cls.owner_kind=='student')&cls.owner_id.in_(student_ids),(cls.owner_kind=='employee')&cls.owner_id.in_(employee_ids))
            elif cls is ops['daily']:predicate=or_((cls.kind=='student')&cls.person_id.in_(student_ids),(cls.kind=='staff')&cls.person_id.in_(employee_ids))
            elif cls is ops['workflow']:predicate=or_((cls.kind=='staff-payment-approval')&(cls.data['requester'].as_integer()==inspect(g.staff_principal).identity[0]),cls.data['campus'].as_string().in_(allowed),cast(cls.data['student_id'].as_string(),Integer).in_(student_ids),cast(cls.data['employee_id'].as_string(),Integer).in_(employee_ids))
            elif cls is Audit:predicate=or_(cls.data['campus'].as_string().in_(allowed),(cls.data['_activity_actor']['kind'].as_string()=='Staff')&(cls.data['_activity_actor']['id'].as_integer()==inspect(g.staff_principal).identity[0]))
            elif cls is rm['settings']:predicate=or_(cls.category!='campus',cls.value.in_(allowed))
            elif 'campus' in table.c:predicate=getattr(cls,'campus').in_(allowed+[''])
            elif 'campus_id' in table.c:predicate=getattr(cls,'campus_id').in_(campus_ids)
            else:
                for column in mapper.columns:
                    if any(fk.column.table is st for fk in column.foreign_keys):predicate=getattr(cls,column.key).in_(student_ids);break
                    if any(fk.column.table is et for fk in column.foreign_keys):predicate=getattr(cls,column.key).in_(employee_ids);break
            if predicate is not None:criteria.append(with_loader_criteria(cls,predicate,include_aliases=True))
        if criteria:execute.statement=execute.statement.options(*criteria)
