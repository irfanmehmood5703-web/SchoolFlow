"""Institute-owned Finance masters. No ledger postings or balance mutations."""
import hmac
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo
from flask import Blueprint, abort, flash, g, redirect, render_template, request, session, url_for
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import StaleDataError
from sqlalchemy.orm import declared_attr

CLASSES=('Assets','Liabilities','Equity','Income','Expense')
STANDARD_GROUPS=[('Current Assets','Assets'),('Capital Assets','Assets'),('Funds Collection','Liabilities'),('Current Liabilities','Liabilities'),('Long Term Liabilities','Liabilities'),("Owner's Equity",'Equity'),('Fee Collection','Income'),('Discounts and Bad Debts','Expense'),('Other Revenues','Income'),('Payroll Expenses','Expense'),('General & Administrative Expenses','Expense')]
RANGES={'Assets':(1000,1999),'Liabilities':(2100,2999),'Equity':(3000,3999),'Income':(4100,4999),'Expense':(5000,9999)}
PREFERRED={'Current Assets':1000,'Capital Assets':1100,'Current Liabilities':2100,'Long Term Liabilities':2200,"Owner's Equity":3000,'Other Revenues':4200,'Discounts and Bad Debts':5500,'Payroll Expenses':5000,'General & Administrative Expenses':5100}
PAGES={'periods':'Accounting Periods','groups':'GL Account Groups','accounts':'GL Accounts'}


def configure_finance(app,db):
    bp=Blueprint('finance',__name__,url_prefix='/workspace/finance')
    Audit=app.extensions['ops_models']['audit']
    class Stamp:
        created_at=db.Column(db.DateTime,nullable=False)
        updated_at=db.Column(db.DateTime,nullable=False)
        created_by=db.Column(db.String(254),nullable=False)
        updated_by=db.Column(db.String(254),nullable=False)
        version=db.Column(db.Integer,nullable=False,default=1)
        @declared_attr.directive
        def __mapper_args__(cls):return {'version_id_col':cls.version}
    class Period(Stamp,db.Model):
        __tablename__='finance_period'
        id=db.Column(db.Integer,primary_key=True)
        begin=db.Column(db.Date,nullable=False)
        end=db.Column(db.Date,nullable=False)
        closed=db.Column(db.Boolean,nullable=False,default=False)
    class Group(Stamp,db.Model):
        __tablename__='finance_group'
        id=db.Column(db.Integer,primary_key=True)
        name=db.Column(db.String(160),nullable=False,unique=True)
        account_class=db.Column(db.String(20),nullable=False)
        active=db.Column(db.Boolean,nullable=False,default=True)
    class Account(Stamp,db.Model):
        __tablename__='finance_account'
        id=db.Column(db.Integer,primary_key=True)
        code=db.Column(db.Integer,nullable=False,unique=True)
        name=db.Column(db.String(160),nullable=False,unique=True)
        group_id=db.Column(db.Integer,db.ForeignKey('finance_group.id',ondelete='RESTRICT'),nullable=False,index=True)
        inactive=db.Column(db.Boolean,nullable=False,default=False)
        group=db.relationship(Group)
    models={'periods':Period,'groups':Group,'accounts':Account}
    app.extensions['finance_models']=dict(period=Period,group=Group,account=Account)

    def actor():
        p=getattr(g,'staff_principal',None)
        return p.username if p else (getattr(g,'school_identity',None) or {}).get('email') or ('Demo visitor' if session.get('demo') else 'School owner')
    def stamp(row,new=False):
        now=datetime.now(timezone.utc);who=actor()
        if new:row.created_at=now;row.created_by=who
        row.updated_at=now;row.updated_by=who
    def snapshot(row):return {c.name:(getattr(row,c.name).isoformat() if isinstance(getattr(row,c.name),(date,datetime)) else getattr(row,c.name)) for c in row.__table__.columns}
    def commit():
        try:db.session.commit()
        except (IntegrityError,StaleDataError):
            db.session.rollback();raise ValueError('Another save changed these Finance records or the name/code already exists. Reload before retrying.')
    def version(row):
        if request.form.get('version')!=str(row.version if row else 0):raise ValueError('This record changed. Reload before saving.')
    def text(name):
        value=request.form.get(name,'').strip()
        if not value or len(value)>160:raise ValueError('Enter '+name.replace('_',' ')+' up to 160 characters.')
        return value
    def flag(name):
        value=request.form.get(name,'')
        if value not in ('0','1'):raise ValueError('Choose Yes or No for '+name+'.')
        return value=='1'
    def next_code(group):
        low,high=RANGES[group.account_class];used={x[0] for x in db.session.query(Account.code).all()}
        start=PREFERRED.get(group.name,low)
        if not low<=start<=high:start=low
        for number in range(start,high+1):
            if number not in used:return number
        for number in range(low,start):
            if number not in used:return number
        raise ValueError('No account codes remain in this account class.')
    def title(kind):
        if kind not in models:abort(404)
        return PAGES[kind]
    def getrow(kind,rid):
        title(kind)
        if not 0<rid<10**18:abort(404)
        return db.get_or_404(models[kind],rid)
    def preview_groups():return Group.query.filter_by(active=True).order_by(Group.account_class,Group.name).all()
    def context():return dict(classes=CLASSES,class_options=[(c,c) for c in CLASSES],pages=PAGES,groups=preview_groups(),finance_time=lambda d:d.replace(tzinfo=timezone.utc).astimezone(ZoneInfo('Asia/Karachi')).strftime('%Y-%m-%d %H:%M') if d else '')
    @bp.before_request
    def protect():
        if request.method=='POST':
            token=request.form.get('_csrf','')
            if not token or not hmac.compare_digest(token,session.get('record_csrf','')):abort(400,'Reload this Finance form.')
            app.extensions['admission_capacity']['lock']()
    @bp.errorhandler(IntegrityError)
    @bp.errorhandler(StaleDataError)
    def conflict(error):
        db.session.rollback();return render_template('operation_error.html',title='Check Finance settings',error='Another save changed these Finance records. Reload before retrying.'),422

    @bp.errorhandler(ValueError)
    def invalid(error):
        db.session.rollback();return render_template('operation_error.html',title='Check Finance settings',error=str(error)),422

    @bp.post('/groups/initialize')
    def initialize():
        for name,cls in STANDARD_GROUPS:
            if Group.query.filter(db.func.lower(Group.name)==name.lower()).first():continue
            row=Group(name=name,account_class=cls,active=True);stamp(row,True);db.session.add(row)
        db.session.add(Audit(action='Initialize Finance groups',data={'actor':actor(),'groups':[n for n,_ in STANDARD_GROUPS]}));commit()
        flash('Standard GL groups added. No accounts, balances or transactions were created.','success')
        return redirect(url_for('finance.index',kind='groups'))

    @bp.get('/<kind>')
    def index(kind):
        heading=title(kind);Model=models[kind];q=Model.query
        for key in ('created_by','updated_by'):
            if request.args.get(key):q=q.filter(getattr(Model,key).ilike('%'+request.args[key]+'%'))
        for key in ('created_at','updated_at'):
            value=request.args.get(key,'')
            if value:
                try:day=date.fromisoformat(value)
                except ValueError:raise ValueError('Choose a valid filter date.')
                # Stored UTC, displayed and filtered in school timezone.
                from datetime import timedelta
                start=datetime.combine(day,datetime.min.time(),tzinfo=ZoneInfo('Asia/Karachi')).astimezone(timezone.utc).replace(tzinfo=None)
                q=q.filter(getattr(Model,key)>=start,getattr(Model,key)<start+timedelta(days=1))
        if request.args.get('name') and kind!='periods':q=q.filter(Model.name.ilike('%'+request.args['name']+'%'))
        if kind=='periods':
            for key in ('begin','end'):
                if request.args.get(key):
                    try:value=date.fromisoformat(request.args[key])
                    except ValueError:raise ValueError('Choose valid Begin and End dates.')
                    q=q.filter(getattr(Model,key)==value)
            if request.args.get('closed') in ('0','1'):q=q.filter_by(closed=request.args['closed']=='1')
            sort_map={'begin':Period.begin,'end':Period.end,'created':Period.created_at}
        else:
            if request.args.get('account_class'):
                if request.args['account_class'] not in CLASSES:raise ValueError('Choose a valid account class.')
                q=q.join(Group).filter(Group.account_class==request.args['account_class']) if kind=='accounts' else q.filter_by(account_class=request.args['account_class'])
            if kind=='groups':
                if request.args.get('active') in ('0','1'):q=q.filter_by(active=request.args['active']=='1')
            else:
                if request.args.get('code'):q=q.filter(db.cast(Account.code,db.String).contains(request.args['code'],autoescape=True))
                if request.args.get('group_id'):
                    raw=request.args['group_id']
                    if not raw.isascii() or not raw.isdigit() or len(raw)>18:raise ValueError('Choose a valid account group.')
                    q=q.filter(Account.group_id==int(raw))
                if request.args.get('inactive') in ('0','1'):q=q.filter_by(inactive=request.args['inactive']=='1')
            sort_map={'name':Model.name,'created':Model.created_at}
            if kind=='accounts':sort_map['code']=Account.code
        sort=request.args.get('sort','begin' if kind=='periods' else 'code' if kind=='accounts' else 'name')
        if sort not in sort_map:raise ValueError('Choose a valid sort order.')
        try:page=int(request.args.get('page','1'));size=int(request.args.get('size','25'))
        except ValueError:raise ValueError('Choose valid pagination.')
        if page<1 or size not in (25,50,100):raise ValueError('Choose 25, 50 or 100 rows.')
        total=q.count();pages=max(1,(total+size-1)//size);page=min(page,pages)
        order=sort_map[sort].desc() if request.args.get('direction')=='desc' else sort_map[sort].asc()
        rows=q.order_by(order,Model.id).offset((page-1)*size).limit(size).all()
        def page_url(number):
            args=request.args.to_dict();args.pop('kind',None);args['page']=number
            return url_for('finance.index',kind=kind,**args)
        return render_template('finance_list.html',title=heading,kind=kind,rows=rows,total=total,page=page,pages_count=pages,size=size,sorts=sort_map,selected_sort=sort,page_url=page_url,**context())

    @bp.route('/<kind>/new',methods=['GET','POST'])
    @bp.route('/<kind>/<int:rid>/edit',methods=['GET','POST'])
    def editor(kind,rid=None):
        heading=title(kind);Model=models[kind];row=getrow(kind,rid) if rid else None
        if request.method=='POST':
            version(row);before=snapshot(row) if row else None
            data={}
            if kind=='periods':
                try:begin=date.fromisoformat(request.form.get('begin',''));end=date.fromisoformat(request.form.get('end',''))
                except ValueError:raise ValueError('Enter valid Begin and End dates.')
                if end<begin:raise ValueError('End must be on or after Begin.')
                if Period.query.filter(Period.id!=(rid or 0),Period.begin<=end,Period.end>=begin).first():raise ValueError('Accounting periods cannot overlap, including closed periods.')
                data=dict(begin=begin,end=end,closed=flag('closed'))
                principal=getattr(g,'staff_principal',None)
                if principal is not None and data['closed']!=(row.closed if row else False):
                    access=app.extensions['staff_access_helpers']
                    if access['grant'](principal,'finance.approve')!=set(access['campuses']()):abort(403,'Closing or reopening a period requires Finance approval for every campus.')
                if row and row.closed and (begin!=row.begin or end!=row.end):raise ValueError('Reopen the closed period before changing its dates.')
            else:
                name=text('name')
                if Model.query.filter(Model.id!=(rid or 0),db.func.lower(Model.name)==name.lower()).first():raise ValueError('That name is already configured.')
                if kind=='groups':
                    cls=request.form.get('account_class','')
                    if cls not in CLASSES:raise ValueError('Choose a valid account class.')
                    if row and cls!=row.account_class and Account.query.filter_by(group_id=row.id).first():raise ValueError('A group with accounts cannot change account class.')
                    data=dict(name=name,account_class=cls,active=flag('active'))
                else:
                    raw=request.form.get('group_id','')
                    if not raw.isascii() or not raw.isdigit() or len(raw)>18:raise ValueError('Choose a valid account group.')
                    group=db.session.get(Group,int(raw))
                    if not group or (not group.active and (not row or row.group_id!=group.id)):raise ValueError('Choose an active account group.')
                    if row and row.group_id!=group.id and row.group.account_class!=group.account_class:raise ValueError('An account cannot move to a different account class. Create a new account instead.')
                    data=dict(name=name,group_id=group.id,inactive=flag('inactive'))
                    if not row:data['code']=next_code(group)
            new=row is None;row=row or Model(**data)
            for key,value in data.items():setattr(row,key,value)
            stamp(row,new);db.session.add(row);db.session.flush()
            db.session.add(Audit(action='Save Finance '+kind,data={'actor':actor(),'id':row.id,'before':before,'after':snapshot(row)}));commit()
            return redirect(url_for('finance.view',kind=kind,rid=row.id))
        previews={}
        if kind=='accounts' and row is None:
            for group in preview_groups():
                try:previews[group.id]=next_code(group)
                except ValueError:previews[group.id]=''
        return render_template('finance_editor.html',title=('Edit ' if row else 'Create ')+heading,kind=kind,row=row,all_groups=Group.query.order_by(Group.name).all(),code_previews=previews,**context())

    @bp.route('/<kind>/<int:rid>',methods=['GET','POST'])
    def view(kind,rid):
        heading=title(kind);row=getrow(kind,rid)
        if request.method=='POST':
            version(row)
            if request.form.get('action')!='delete' or request.form.get('confirm')!='1':raise ValueError('Confirm deletion of this unused record.')
            if kind=='groups' and Account.query.filter_by(group_id=rid).first():raise ValueError('This group has accounts. Make it inactive instead.')
            # Only master records exist in this phase. Future journal posting
            # must add references and prevent deletion of used accounts/periods.
            db.session.add(Audit(action='Delete Finance '+kind,data={'actor':actor(),'before':snapshot(row)}));db.session.delete(row);commit()
            return redirect(url_for('finance.index',kind=kind))
        return render_template('finance_view.html',title=heading,kind=kind,row=row,**context())

    @bp.get('/chart-of-accounts')
    def chart():
        groups=Group.query.order_by(Group.name).all();accounts=Account.query.order_by(Account.code).all();by_group={}
        for row in accounts:by_group.setdefault(row.group_id,[]).append(row)
        return render_template('finance_chart.html',title='Chart of Accounts',chart_groups=groups,by_group=by_group,**context())
    app.register_blueprint(bp)
