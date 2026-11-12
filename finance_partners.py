"""Cash report and shareholder directory backed by institute journals."""
import hmac,re,secrets
from datetime import date,datetime,timezone
from decimal import Decimal,InvalidOperation,ROUND_HALF_UP
from flask import Blueprint,abort,flash,g,redirect,render_template,request,session,url_for
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import declared_attr
from sqlalchemy.orm.exc import StaleDataError
from finance_setup import CLASSES

CASH_TABS=('Assets','Liabilities','Equity','Expense','Income')

def configure_finance_partners(app,db):
    bp=Blueprint('finance_partners',__name__,url_prefix='/workspace/finance')
    H=app.extensions['ledger_helpers'];M=app.extensions['finance_models'];Account=M['account'];Group=M['group'];J=app.extensions['ledger_models']['journal'];L=app.extensions['ledger_models']['line'];Audit=app.extensions['ops_models']['audit']
    class Partner(db.Model):
        __tablename__='finance_shareholder'
        id=db.Column(db.Integer,primary_key=True)
        name=db.Column(db.String(160),nullable=False)
        equity_bp=db.Column(db.Integer,nullable=False)
        account_id=db.Column(db.Integer,db.ForeignKey('finance_account.id',ondelete='RESTRICT'))
        campus=db.Column(db.String(160),nullable=False,default='')
        cnic=db.Column(db.String(32),nullable=False,default='')
        contact=db.Column(db.String(80),nullable=False,default='')
        email=db.Column(db.String(254),nullable=False,default='')
        since=db.Column(db.Date)
        active=db.Column(db.Boolean,nullable=False,default=True)
        notes=db.Column(db.String(5000),nullable=False,default='')
        token=db.Column(db.String(64),nullable=False,unique=True)
        created_at=db.Column(db.DateTime,nullable=False)
        updated_at=db.Column(db.DateTime,nullable=False)
        created_by=db.Column(db.String(254),nullable=False)
        created_key=db.Column(db.String(100),nullable=False)
        updated_by=db.Column(db.String(254),nullable=False)
        version=db.Column(db.Integer,nullable=False,default=1)
        __mapper_args__={'version_id_col':version}
        __table_args__=(db.CheckConstraint('equity_bp >= 0 AND equity_bp <= 10000',name='shareholder_equity_range'),)
    app.extensions['shareholder_model']=Partner
    used=H['used_account'];H['used_account']=lambda rid:used(rid) or Partner.query.filter_by(account_id=rid).first() is not None
    @bp.before_request
    def protect():
        if request.method=='POST':
            token=request.form.get('_csrf','')
            if not token or not hmac.compare_digest(token,session.get('record_csrf','')):abort(400,'Reload this Finance form.')
            app.extensions['admission_capacity']['lock']()
    @bp.errorhandler(ValueError)
    def invalid(exc):
        db.session.rollback();return render_template('operation_error.html',title='Check Finance details',error=str(exc)),422
    @bp.errorhandler(IntegrityError)
    @bp.errorhandler(StaleDataError)
    def conflict(exc):
        db.session.rollback();return render_template('operation_error.html',title='Check Finance details',error='Another save changed these records. Reload before saving.'),422
    def render(template,**kw):return render_template(template,campuses=H['campuses'](),cash_tabs=CASH_TABS,**kw)
    def link(endpoint,**changes):
        args=request.args.to_dict(flat=False)
        for k,v in changes.items():args[k]=v
        return url_for(endpoint,**args)
    def grouped(q):
        raw=q.with_entities(L.account_id,func.sum(L.debit),func.sum(L.credit),func.max(L.id)).group_by(L.account_id).all()
        snaps={l.id:l.snapshot for l in L.query.filter(L.id.in_([r[3] for r in raw])).all()} if raw else {}
        return {aid:(snaps[last],int(d),int(c)) for aid,d,c,last in raw}
    def profit(start,end,scope):
        raw=grouped(H['scoped'](scope,[]).filter(J.day>=start,J.day<=end));income=expense=0
        for snap,d,c in raw.values():
            if snap['account_class']=='Income':income+=c-d
            if snap['account_class']=='Expense':expense+=d-c
        return income,expense
    @bp.get('/cash-report')
    def cash():
        start,end,scope,users=H['filters']();tab=request.args.get('tab','Assets')
        if tab not in CASH_TABS:raise ValueError('Choose a Cash Report section.')
        accounts=Account.query.join(Group).order_by(Group.account_class,Group.name,Account.code).all();known={a.id for a in accounts}
        selected={H['identity'](v) for v in request.args.getlist('account_id')}
        if not selected<=known:raise ValueError('Choose configured accounts.')
        base=H['scoped'](scope,users)
        if selected:base=base.filter(L.account_id.in_(selected))
        before=grouped(base.filter(J.day<start));during=grouped(base.filter(J.day>=start,J.day<=end));rows=[]
        for aid in before.keys()|during.keys():
            snap=during.get(aid,before.get(aid))[0];_,bd,bc=before.get(aid,(snap,0,0));_,d,c=during.get(aid,(snap,0,0))
            rows.append(dict(id=aid,snapshot=snap,brought_debit=bd,brought_credit=bc,debit=d,credit=c,balance=bd-bc+d-c))
        rows.sort(key=lambda r:(CASH_TABS.index(r['snapshot']['account_class']),r['snapshot']['group'],r['snapshot']['code']))
        keys=('brought_debit','brought_credit','debit','credit','balance');totals={k:sum(r[k] for r in rows) for k in keys};rollups={}
        for row in rows:
            for group in ((row['snapshot']['account_class'],row['snapshot']['group']),(row['snapshot']['account_class'],None)):
                total=rollups.setdefault(group,{k:0 for k in keys})
                for k in keys:total[k]+=row[k]
        query=request.args.get('q','').strip().casefold();section=[r for r in rows if r['snapshot']['account_class']==tab]
        filtered=[r for r in section if not query or query in (str(r['snapshot']['code'])+' '+r['snapshot']['name']+' '+r['snapshot']['group']).casefold()]
        try:page=int(request.args.get('page','1'));size=int(request.args.get('size','100'))
        except ValueError:raise ValueError('Choose valid report pagination.')
        if page<1 or size not in (25,50,100):raise ValueError('Choose 25, 50 or 100 rows.')
        count=len(filtered);pages=max(1,(count+size-1)//size);page=min(page,pages)
        display=rows if request.args.get('print')=='1' else filtered[(page-1)*size:page*size]
        return render('cash_report.html',title='Cash Report',start=start,end=end,scope=scope,users=users,user_options=db.session.query(J.actor_key,J.actor).distinct().order_by(J.actor).all(),accounts=accounts,selected=selected,rows=rows,display=display,rollups=rollups,totals=totals,keys=keys,tab=tab,count=count,page=page,pages_count=pages,size=size,link=lambda **kw:link('finance_partners.cash',**kw))
    def read_partner(existing=None):
        values={}
        for key,maximum in [('name',160),('cnic',32),('contact',80),('email',254),('notes',5000)]:
            value=request.form.get(key,'').strip()
            if len(value)>maximum or (key=='name' and not value):raise ValueError('Check '+key+' length; name is required.')
            values[key]=value
        if values['email'] and not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',values['email']):raise ValueError('Enter a valid email address.')
        try:n=Decimal(request.form.get('equity',''))
        except InvalidOperation:raise ValueError('Enter an equity percentage from 0 to 100.')
        if not n.is_finite() or not 0<=n<=100 or n*100!=(n*100).to_integral_value():raise ValueError('Equity must be 0–100 with at most two decimals.')
        values['equity_bp']=int(n*100);values['campus']=request.form.get('campus','')
        if values['campus'] and values['campus'] not in H['campuses']():raise ValueError('Choose a configured campus or All campuses.')
        raw=request.form.get('account_id','');values['account_id']=H['identity'](raw) if raw else None
        if values['account_id']:
            account=db.session.get(Account,values['account_id'])
            if not account or account.group.account_class!='Equity' or ((account.inactive or not account.group.active) and (not existing or existing.account_id!=account.id)):raise ValueError('Choose an active Equity account.')
        raw=request.form.get('since','')
        try:values['since']=date.fromisoformat(raw) if raw else None
        except ValueError:raise ValueError('Choose a valid Partner Since date.')
        if request.form.get('active','') not in ('','0','1'):raise ValueError('Choose a valid active partner status.')
        values['active']=request.form.get('active')=='1'
        return values
    def check_allocation(values,rid=None):
        others=Partner.query.filter(Partner.id!=rid).all() if rid else Partner.query.all()
        for other in others:
            overlapping=not other.campus or not values['campus'] or other.campus==values['campus']
            if values['account_id'] and other.account_id==values['account_id'] and overlapping:raise ValueError('This Equity account is already linked to an overlapping partner scope. Use a separate capital account.')
        if not values['active']:return
        for campus in H['campuses']() or ['']:
            total=sum(p.equity_bp for p in others if p.active and (not p.campus or p.campus==campus))
            if not values['campus'] or values['campus']==campus:total+=values['equity_bp']
            if total>10000:raise ValueError('Active equity exceeds 100% for '+(campus or 'the whole institute')+'.')
    @bp.route('/shareholders/new',methods=['GET','POST'])
    @bp.route('/shareholders/<int:rid>/edit',methods=['GET','POST'])
    def edit(rid=None):
        row=db.get_or_404(Partner,rid) if rid else None
        if request.method=='POST':
            if request.form.get('version')!=str(row.version if row else 0):raise ValueError('This shareholder changed. Reload before saving.')
            token=request.form.get('post_token','')
            if not re.fullmatch(r'[A-Za-z0-9_-]{32,64}',token):raise ValueError('Reload this shareholder form.')
            prior=Partner.query.filter_by(token=token).first() if not row else None
            values=read_partner(row or prior)
            if not row:
                if prior:
                    if prior.created_key!=H['actor']()[1] or any(getattr(prior,k)!=v for k,v in values.items()):raise ValueError('This submission token was already used with different details.')
                    return redirect(url_for('finance_partners.partners'))
            check_allocation(values,rid)
            if row and row.account_id and (row.account_id!=values['account_id'] or row.campus!=values['campus']) and L.query.filter_by(account_id=row.account_id).first():raise ValueError('A linked capital account or scope with posted activity cannot be replaced.')
            now=datetime.now(timezone.utc);who=H['actor']()[0]
            before={k:getattr(row,k) for k in values} if row else None
            if before and before['since']:before['since']=before['since'].isoformat()
            if not row:row=Partner(token=token,created_at=now,created_by=who,created_key=H['actor']()[1]);db.session.add(row)
            for k,v in values.items():setattr(row,k,v)
            row.updated_at=now;row.updated_by=who;db.session.flush()
            db.session.add(Audit(action='Save shareholder',data={'id':row.id,'actor':who,'before':before}));db.session.commit();flash('Shareholder saved. Profit shares are estimates using the current ownership percentages.','success')
            return redirect(url_for('finance_partners.partners'))
        accounts=H['options']();accounts=[a for a in accounts if a.group.account_class=='Equity']
        if row and row.account_id and row.account_id not in {a.id for a in accounts}:accounts.append(db.session.get(Account,row.account_id))
        return render('shareholder_form.html',title='Edit Shareholder' if row else 'Add Shareholder',row=row,accounts=accounts,post_token=secrets.token_urlsafe(32))
    @bp.get('/shareholders')
    def partners():
        start,end,scope,users=H['filters']();include_former=request.args.get('former')=='1'
        # This dashboard has no campus/user report controls in the reference.
        # Each partner's own configured scope determines their figures.
        income,expense=profit(start,end,[]);rows=[];capital_total=0
        partners=Partner.query.order_by(Partner.name,Partner.id).all()
        for p in partners:
            own=[p.campus] if p.campus else [];capital=None;credits=debits=transactions=0
            if p.account_id:
                base=H['scoped'](own,[]).filter(L.account_id==p.account_id)
                capital=int(base.filter(J.day<=end).with_entities(func.coalesce(func.sum(L.credit-L.debit),0)).scalar())
                d,c,n=base.filter(J.day>=start,J.day<=end).with_entities(func.coalesce(func.sum(L.debit),0),func.coalesce(func.sum(L.credit),0),func.count(func.distinct(J.id))).one();debits=int(d);credits=int(c);transactions=int(n)
            if not p.active and not include_former:continue
            if capital is not None:capital_total+=capital
            effective=max(start,p.since) if p.since else start;pi,pe=profit(effective,end,own) if effective<=end and p.active else (0,0)
            share=int((Decimal(pi-pe)*p.equity_bp/10000).quantize(Decimal('1'),rounding=ROUND_HALF_UP))
            rows.append(dict(partner=p,capital=capital,credits=credits,debits=debits,transactions=transactions,share=share))
        allocations=[(c,sum(p.equity_bp for p in partners if p.active and (not p.campus or p.campus==c))) for c in H['campuses']() or ['Whole institute']]
        return render('shareholders.html',title='Shareholders',start=start,end=end,scope=[],include_former=include_former,rows=rows,income=income,expense=expense,capital_total=capital_total,allocations=allocations,link=lambda **kw:link('finance_partners.partners',**kw))
    @bp.get('/shareholders/<int:rid>/transactions')
    def transactions(rid):
        row=db.get_or_404(Partner,rid);start,end,scope,users=H['filters']();lines=[]
        if row.account_id:lines=H['scoped']([row.campus] if row.campus else [],[]).filter(L.account_id==row.account_id,J.day>=start,J.day<=end).order_by(J.day,J.id,L.id).all()
        return render('shareholder_transactions.html',title='Shareholder Transactions',row=row,lines=lines,start=start,end=end)
    app.register_blueprint(bp)
