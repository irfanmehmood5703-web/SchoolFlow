"""Scoped requisition authorisation and unified-ledger posting workflows."""
import hashlib,hmac,json,re,secrets
from datetime import date,datetime,timezone
from decimal import Decimal,InvalidOperation,ROUND_HALF_UP
from flask import Blueprint,abort,flash,g,redirect,render_template,request,session,url_for
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import StaleDataError

CATEGORIES=('Procurement / Supplies','Maintenance & Repairs','Utilities & Bills','Travel & Conveyance','Events & Functions','Salary Advance')
STATES=('Awaiting approval','Approved','Rejected','Cancelled')
PAGES=(('mine','My Requisitions'),('approvals','Requisition Approvals'),('issue','Issue Requisition Payment'),('settle','Settle Requisition'),('reports','Requisition Reports'),('settings','Requisition Settings'))
DEFAULTS=dict(prefix='REQ',settle_days=15,overdue_days=30,block_open=False,carry_unspent=True,require_bill=True,advance_account=None,pay_account=None,payable_account=None)

def configure_requisitions(app,db):
    bp=Blueprint('requisitions',__name__,url_prefix='/workspace/finance/requisitions');H=app.extensions['ledger_helpers'];Audit=app.extensions['ops_models']['audit']
    class Config(db.Model):
        __tablename__='requisition_config'
        id=db.Column(db.Integer,primary_key=True)
        data=db.Column(db.JSON,nullable=False,default=dict)
        version=db.Column(db.Integer,nullable=False,default=1)
        __mapper_args__={'version_id_col':version}
    class Req(db.Model):
        __tablename__='purchase_requisition'
        id=db.Column(db.Integer,primary_key=True)
        number=db.Column(db.String(40),unique=True,nullable=False)
        campus=db.Column(db.String(160),nullable=False,index=True)
        actor_key=db.Column(db.String(100),nullable=False,index=True)
        raised_by=db.Column(db.String(254),nullable=False)
        raised=db.Column(db.DateTime,nullable=False,default=lambda:datetime.now(timezone.utc))
        category=db.Column(db.String(80),nullable=False)
        needed=db.Column(db.Date)
        purpose=db.Column(db.String(2000),nullable=False)
        items=db.Column(db.JSON,nullable=False)
        estimated=db.Column(db.BigInteger,nullable=False)
        approved=db.Column(db.BigInteger,nullable=False,default=0)
        status=db.Column(db.String(30),nullable=False,default='Awaiting approval',index=True)
        remarks=db.Column(db.String(2000),nullable=False,default='')
        decided_by=db.Column(db.String(254))
        decided=db.Column(db.DateTime)
        token=db.Column(db.String(64),nullable=False,unique=True)
        fingerprint=db.Column(db.String(64),nullable=False)
        version=db.Column(db.Integer,nullable=False,default=1)
        __mapper_args__={'version_id_col':version}
        __table_args__=(db.CheckConstraint('estimated > 0 AND approved >= 0 AND approved <= estimated',name='requisition_amounts'),)
    class Action(db.Model):
        __tablename__='requisition_action'
        token=db.Column(db.String(64),primary_key=True)
        fingerprint=db.Column(db.String(64),nullable=False)
        req_id=db.Column(db.Integer,db.ForeignKey('purchase_requisition.id',ondelete='RESTRICT'),nullable=False)
    app.extensions['requisition_models']=dict(config=Config,request=Req,action=Action)
    def config():
        row=db.session.get(Config,1);return row,{**DEFAULTS,**(row.data if row else {})}
    def scope():
        p=getattr(g,'staff_principal',None)
        return sorted(g.access_campuses) if p else H['campuses']()
    def render(template,**kw):return render_template(template,requisition_pages=PAGES,categories=CATEGORIES,states=STATES,campuses=scope(),**kw)
    @bp.before_request
    def protect():
        if request.method=='POST':
            if not request.form.get('_csrf') or not hmac.compare_digest(request.form['_csrf'],session.get('record_csrf','')):abort(400,'Reload this requisition form.')
            app.extensions['admission_capacity']['lock']()
    @bp.errorhandler(ValueError)
    def invalid(exc):
        db.session.rollback();return render_template('operation_error.html',title='Check requisition',error=str(exc)),422
    @bp.errorhandler(IntegrityError)
    @bp.errorhandler(StaleDataError)
    def conflict(exc):
        db.session.rollback();return render_template('operation_error.html',title='Check requisition',error='This record changed or the action was already submitted. Reload before retrying.'),422
    def digest(data):return hashlib.sha256(json.dumps(data,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    def token():
        value=request.form.get('post_token','')
        if not re.fullmatch(r'[A-Za-z0-9_-]{32,64}',value):raise ValueError('Reload this form before submitting.')
        return value
    def get_req(rid,owned=False):
        if not 0<rid<10**18:abort(404)
        row=Req.query.filter_by(id=rid).first()
        if not row or row.campus not in scope() or (owned and row.actor_key!=H['actor']()[1]):abort(404)
        return row
    def check_version(row):
        if request.form.get('version')!=str(row.version):raise ValueError('This requisition changed. Reload before deciding.')
    def items():
        names=request.form.getlist('item');quantities=request.form.getlist('qty');prices=request.form.getlist('unit_price')
        if not 1<=len(names)<=100 or not len(names)==len(quantities)==len(prices):raise ValueError('Enter 1–100 complete items.')
        result=[]
        for label,quantity,price in zip(names,quantities,prices):
            if not label.strip() and not price.strip():continue
            label=label.strip()
            if not label or len(label)>500:raise ValueError('Each item needs a description up to 500 characters.')
            if not re.fullmatch(r'[0-9]{1,5}(?:\.[0-9]{1,3})?',quantity):raise ValueError('Enter quantity as an ordinary number with at most three decimal places.')
            if not re.fullmatch(r'[0-9]{1,9}(?:\.[0-9]{1,2})?',price):raise ValueError('Enter unit price as an ordinary amount with at most two decimal places.')
            try:q=Decimal(quantity)
            except InvalidOperation:raise ValueError('Enter a valid item quantity.')
            if not q.is_finite() or not 0<q<=99999 or q*1000!=(q*1000).to_integral_value():raise ValueError('Quantity must be positive, up to 99,999, with at most three decimal places.')
            unit=H['amount'](price)
            if not unit:raise ValueError('Enter a positive unit price.')
            amount=int((q*unit).quantize(Decimal('1'),rounding=ROUND_HALF_UP))
            if amount<=0:raise ValueError('Item amount must be at least one paisa.')
            result.append(dict(item=label,qty=str(q),unit_price=unit,amount=amount))
        total=sum(i['amount'] for i in result)
        if not result or total>99999999900:raise ValueError('Enter valid items totalling at most 999,999,999.')
        return result,total
    @bp.route('/mine',methods=['GET','POST'])
    def mine():
        who,key=H['actor']();cfg_row,cfg=config()
        if request.method=='POST':
            submission=token();data={k:request.form.getlist(k) for k in ('campus','category','needed','purpose','item','qty','unit_price')};fingerprint=digest([key,data])
            prior=Req.query.filter_by(token=submission).first()
            if prior:
                if prior.fingerprint!=fingerprint:raise ValueError('This submission token was already used for different details.')
                return redirect(url_for('requisitions.detail',rid=prior.id))
            campus=request.form.get('campus','');category=request.form.get('category','');purpose=request.form.get('purpose','').strip()
            if campus not in scope():raise ValueError('Choose a granted campus.')
            if category not in CATEGORIES:raise ValueError('Choose a listed category.')
            if not purpose or len(purpose)>2000:raise ValueError('Describe what this requisition is for, up to 2,000 characters.')
            raw=request.form.get('needed','')
            try:needed=date.fromisoformat(raw) if raw else None
            except ValueError:raise ValueError('Choose a valid Needed by date.')
            if cfg['block_open'] and app.extensions['requisition_posting']['open_for'](key):raise ValueError('Settle the existing held advance or staff payable before raising another requisition.')
            lines,total=items()
            # No advance can be issued before New Ledger exists. An approved,
            # unissued request is not falsely treated as staff holding money.
            # The institute write gate serializes this tenant-wide sequence.
            # Core table access avoids filtering the sequence to a staff campus.
            rid=int(db.session.execute(db.select(func.max(Req.__table__.c.id))).scalar() or 0)+1
            row=Req(id=rid,number=cfg['prefix']+'-'+str(rid).zfill(6),campus=campus,actor_key=key,raised_by=who,category=category,needed=needed,purpose=purpose,items=lines,estimated=total,token=submission,fingerprint=fingerprint);db.session.add(row);db.session.flush()
            db.session.add(Audit(action='Raise requisition',data=dict(id=row.id,number=row.number,campus=campus,actor=who,estimated=total)));db.session.commit();flash('Requisition sent for approval. No money has been issued.','success')
            return redirect(url_for('requisitions.detail',rid=row.id))
        status=request.args.get('status','All')
        if status!='All' and status not in STATES:raise ValueError('Choose a valid status.')
        q=Req.query.filter_by(actor_key=key).filter(Req.campus.in_(scope()))
        if status!='All':q=q.filter_by(status=status)
        return render('requisition_mine.html',title='My Requisitions',rows=q.order_by(Req.raised.desc(),Req.id.desc()).limit(500).all(),status=status,post_token=secrets.token_urlsafe(32))
    @bp.get('/<int:rid>')
    def detail(rid):
        row=get_req(rid,owned=True);return render('requisition_detail.html',title=row.number,row=row,post_token=secrets.token_urlsafe(32))
    @bp.post('/<int:rid>/cancel')
    def cancel(rid):
        row=get_req(rid,owned=True);check_version(row)
        if row.status!='Awaiting approval':raise ValueError('Only a request awaiting approval can be cancelled here.')
        row.status='Cancelled';db.session.add(Audit(action='Cancel requisition',data=dict(id=rid,campus=row.campus,actor=H['actor']()[0])));db.session.commit();return redirect(url_for('requisitions.mine'))
    @bp.get('/approvals')
    def approvals():
        rows=Req.query.filter(Req.campus.in_(scope()),Req.status=='Awaiting approval').order_by(Req.raised,Req.id).limit(500).all()
        return render('requisition_approvals.html',title='Requisition Approvals',rows=rows,post_token=lambda:secrets.token_urlsafe(32))
    @bp.post('/<int:rid>/decide')
    def decide(rid):
        row=get_req(rid);submission=token();decision=request.form.get('decision','');remarks=request.form.get('remarks','').strip();raw=request.form.get('approved','');fingerprint=digest([rid,H['actor']()[1],decision,remarks,raw])
        prior=db.session.get(Action,submission)
        if prior:
            if prior.fingerprint!=fingerprint:raise ValueError('This decision token was already used for different data.')
            return redirect(url_for('requisitions.approvals'))
        check_version(row)
        if row.status!='Awaiting approval':raise ValueError('This request has already been decided or cancelled.')
        if decision not in ('Approved','Rejected') or len(remarks)>2000:raise ValueError('Choose Approve/Reject and remarks up to 2,000 characters.')
        approved=H['amount'](raw) if decision=='Approved' else 0
        if decision=='Approved' and not 0<approved<=row.estimated:raise ValueError('Approved amount must be positive and cannot exceed the request estimate.')
        if decision=='Rejected' and not remarks:raise ValueError('Enter a reason for rejection.')
        row.status=decision;row.approved=approved;row.remarks=remarks;row.decided_by=H['actor']()[0];row.decided=datetime.now(timezone.utc)
        db.session.add(Action(token=submission,fingerprint=fingerprint,req_id=rid));db.session.add(Audit(action='Decide requisition',data=dict(id=rid,campus=row.campus,actor=row.decided_by,decision=decision,approved=approved)));db.session.commit();return redirect(url_for('requisitions.approvals'))
    @bp.route('/settings',methods=['GET','POST'])
    def settings():
        row,cfg=config()
        if request.method=='POST':
            if request.form.get('version')!=str(row.version if row else 0):raise ValueError('These settings changed. Reload before saving.')
            accounts=app.extensions['finance_models']['account'];mapping={}
            for key,cls in [('advance_account','Assets'),('pay_account','Assets'),('payable_account','Liabilities')]:
                raw=request.form.get(key,'')
                try:aid=int(raw) if raw else None
                except ValueError:raise ValueError('Choose a configured account.')
                if aid is not None and not 0<aid<10**18:raise ValueError('Choose a valid account.')
                a=db.session.get(accounts,aid) if aid else None
                if aid and (not a or a.inactive or not a.group.active or a.group.account_class!=cls):raise ValueError('Choose an active '+cls+' account for '+key.replace('_',' ')+'.')
                mapping[key]=aid
            if mapping['advance_account'] and mapping['advance_account']==mapping['pay_account']:raise ValueError('Staff Advances must differ from the cash/bank account.')
            balances=[app.extensions['requisition_posting']['balance'](r.id) for r in Req.query.all()]
            if mapping['advance_account']!=cfg['advance_account'] and any(b['held'] for b in balances):raise ValueError('Settle held advances before changing the Staff Advances mapping.')
            if mapping['payable_account']!=cfg['payable_account'] and any(b['owed'] for b in balances):raise ValueError('Reimburse outstanding staff payables before changing that mapping.')
            prefix=request.form.get('prefix','').strip().upper()
            if not re.fullmatch(r'[A-Z0-9][A-Z0-9-]{0,11}',prefix):raise ValueError('Use a requisition prefix of 1–12 letters, digits or hyphens.')
            try:settle=int(request.form.get('settle_days',''));overdue=int(request.form.get('overdue_days',''))
            except ValueError:raise ValueError('Enter whole numbers for the day rules.')
            if not 1<=settle<=overdue<=3650:raise ValueError('Settle within must be 1–3,650 days; overdue must be at least that many days.')
            cfg=dict(DEFAULTS,**mapping,prefix=prefix,settle_days=settle,overdue_days=overdue,**{k:request.form.get(k)=='1' for k in ('block_open','carry_unspent','require_bill')})
            if not row:row=Config(id=1,data=cfg);db.session.add(row)
            else:row.data=cfg
            db.session.add(Audit(action='Save requisition settings',data=dict(actor=H['actor']()[0],settings=cfg)));db.session.commit();flash('Requisition rules and ledger account mappings saved.','success');return redirect(url_for('requisitions.settings'))
        return render('requisition_settings.html',title='Requisition Settings',cfg=cfg,row=row,accounts=app.extensions['ledger_helpers']['options']())
    @bp.get('/issue')
    def issue():return posting_list('issue')
    @bp.get('/settle')
    def settle():return posting_list('settle')
    def posting_list(mode):
        rows=Req.query.filter(Req.campus.in_(scope()),Req.status=='Approved').order_by(Req.id).all()
        balances={r.id:app.extensions['requisition_posting']['balance'](r.id) for r in rows};_,cfg=config()
        return render('requisition_posting.html',title='Issue Requisition Payment' if mode=='issue' else 'Settle Requisition',mode=mode,rows=rows,balances=balances,cfg=cfg,today=H['today']())
    @bp.post('/<int:rid>/issue')
    @bp.post('/<int:rid>/settle')
    def blocked_posting(rid):
        get_req(rid);raise ValueError('Open the current Issue Payment or Record Expense Bill form and submit its version and posting token. No posting was made from this old form.')
    @bp.get('/reports')
    def reports():
        tab=request.args.get('tab','ageing')
        if tab not in ('ageing','register'):raise ValueError('Choose Advance Ageing or Requisition Register.')
        raw=request.args.get('as_at',H['today']().isoformat())
        try:as_at=date.fromisoformat(raw)
        except ValueError:raise ValueError('Choose a valid As at date.')
        rows=Req.query.filter(Req.campus.in_(scope())).order_by(Req.id.desc()).all()
        helper=app.extensions['requisition_posting']
        rows=[r for r in rows if r.raised.date()<=as_at or helper['movements'](r.id,as_at)]
        balances={r.id:helper['balance'](r.id,as_at) for r in rows}
        buckets=[0,0,0,0];people={};open_rows=[]
        for r in rows:
            b=balances[r.id]
            if not b['held']:continue
            person=people.setdefault(r.actor_key,dict(name=r.raised_by,buckets=[0,0,0,0],total=0,oldest=None))
            for lot_day,n in b['lots']:
                days=max(0,(as_at-lot_day).days);i=0 if days<=7 else 1 if days<=15 else 2 if days<=30 else 3
                buckets[i]+=n;person['buckets'][i]+=n;person['total']+=n
                person['oldest']=min(person['oldest'] or lot_day,lot_day)
                open_rows.append(dict(row=r,day=lot_day,days=days,held=n))
        Line=app.extensions['ledger_models']['line'];Journal=app.extensions['ledger_models']['journal'];Movement=app.extensions['requisition_models']['movement'];_,cfg=config()
        account_ids={m.data.get('advance_account') for m in Movement.query.all() if m.data.get('advance_account')}
        if cfg['advance_account']:account_ids.add(cfg['advance_account'])
        book=db.session.query(func.coalesce(func.sum(Line.debit-Line.credit),0)).join(Journal).filter(Line.account_id.in_(account_ids),Journal.campus.in_(scope()),Journal.day<=as_at).scalar() if account_ids else None
        return render('requisition_reports.html',title='Requisition Reports',tab=tab,as_at=as_at,rows=rows,balances=balances,buckets=buckets,people=people,open_rows=open_rows,book=book,held=sum(b['held'] for b in balances.values()))
    app.register_blueprint(bp)
    from requisition_posting import configure_requisition_posting
    configure_requisition_posting(app,db,config,scope,get_req,check_version,token,digest)
