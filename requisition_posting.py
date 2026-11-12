"""Append-only requisition advances, expense bills, returns and internal carry.

All amounts are integer paisa. A tenant write gate, optimistic request versions,
unique submission tokens and a single commit bind movements to ledger vouchers.
"""
import hashlib,hmac,io,json,secrets
from datetime import date,datetime,timezone
from flask import Blueprint,abort,flash,g,redirect,render_template,request,send_file,session,url_for
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import StaleDataError
from werkzeug.utils import secure_filename

MAX_BILL=5*1024*1024

def configure_requisition_posting(app,db,config,scope,get_req,check_version,token,digest):
    bp=Blueprint('req_posting',__name__,url_prefix='/workspace/finance/requisitions')
    H=app.extensions['ledger_helpers'];M=app.extensions['requisition_models'];Req=M['request'];Audit=app.extensions['ops_models']['audit']
    L=app.extensions['ledger_models'];Journal=L['journal'];Line=L['line'];Note=L['note'];Account=app.extensions['finance_models']['account'];Period=app.extensions['finance_models']['period']
    class Movement(db.Model):
        __tablename__='requisition_movement'
        id=db.Column(db.Integer,primary_key=True)
        req_id=db.Column(db.Integer,db.ForeignKey('purchase_requisition.id',ondelete='RESTRICT'),nullable=False,index=True)
        kind=db.Column(db.String(20),nullable=False)
        day=db.Column(db.Date,nullable=False,index=True)
        amount=db.Column(db.BigInteger,nullable=False)
        advance_used=db.Column(db.BigInteger,nullable=False,default=0)
        payable=db.Column(db.BigInteger,nullable=False,default=0)
        journal_id=db.Column(db.Integer,db.ForeignKey('finance_journal.id',ondelete='RESTRICT'),unique=True)
        token=db.Column(db.String(64),nullable=False,unique=True)
        fingerprint=db.Column(db.String(64),nullable=False)
        actor=db.Column(db.String(254),nullable=False)
        created=db.Column(db.DateTime,nullable=False,default=lambda:datetime.now(timezone.utc))
        data=db.Column(db.JSON,nullable=False)
        filename=db.Column(db.String(255))
        mime=db.Column(db.String(80))
        content=db.deferred(db.Column(db.LargeBinary))
        __table_args__=(db.CheckConstraint('amount > 0 AND advance_used >= 0 AND payable >= 0',name='requisition_movement_amounts'),)
    M['movement']=Movement
    def movements(rid,as_at=None):
        q=Movement.query.filter_by(req_id=rid)
        if as_at:q=q.filter(Movement.day<=as_at)
        return q.order_by(Movement.day,Movement.id).all()
    def balance(rid,as_at=None):
        rows=movements(rid,as_at);totals={k:sum(m.amount for m in rows if m.kind==k) for k in ('issue','bill','return','carry_in','carry_out','reimburse')}
        totals['held']=totals['issue']+totals['carry_in']-totals['return']-totals['carry_out']-sum(m.advance_used for m in rows if m.kind=='bill')
        totals['owed']=sum(m.payable for m in rows if m.kind=='bill')-totals['reimburse']
        totals['committed']=totals['issue']+totals['carry_in']+sum(m.payable for m in rows if m.kind=='bill')
        lots=[]
        for m in rows:
            if m.kind=='issue':lots.append([m.day,m.amount])
            elif m.kind=='carry_in':
                lots.extend([[date.fromisoformat(d),n] for d,n in m.data.get('lots',[[m.day.isoformat(),m.amount]])])
            else:
                consume=m.advance_used if m.kind=='bill' else m.amount if m.kind in ('return','carry_out') else 0
                lots.sort(key=lambda lot:lot[0])
                for lot in lots:
                    used=min(consume,lot[1]);lot[1]-=used;consume-=used
        totals['lots']=[(d,n) for d,n in lots if n]
        totals['oldest']=min((d for d,n in totals['lots']),default=None)
        return totals
    def open_for(key):
        # A business rule spanning campuses must not disappear under a staff
        # list filter. This returns only a boolean, never other-campus records.
        ids=db.session.execute(db.select(Req.__table__.c.id).where(Req.__table__.c.actor_key==key)).scalars().all()
        for rid in ids:
            rows=db.session.execute(db.select(Movement.__table__).where(Movement.req_id==rid)).mappings().all()
            held=sum((m['amount'] if m['kind'] in ('issue','carry_in') else -m['amount'] if m['kind'] in ('return','carry_out') else -m['advance_used'] if m['kind']=='bill' else 0) for m in rows)
            owed=sum(m['payable'] if m['kind']=='bill' else -m['amount'] if m['kind']=='reimburse' else 0 for m in rows)
            if held or owed:return True
        return False
    def accounts(cls):return [a for a in H['options']() if a.group.account_class==cls]
    def account(raw,cls):
        try:aid=int(raw)
        except (ValueError,TypeError):raise ValueError('Choose an active '+cls+' account.')
        if not 0<aid<10**18:raise ValueError('Choose a valid account.')
        a=db.session.get(Account,aid)
        if not a or a.inactive or not a.group.active or a.group.account_class!=cls:raise ValueError('Choose an active '+cls+' account.')
        return a
    def active_mapping(cfg):
        adv=account(cfg.get('advance_account'),'Assets')
        return adv
    def render(template,**kw):
        from requisitions import PAGES
        return render_template(template,requisition_pages=PAGES,campuses=scope(),**kw)
    @bp.before_request
    def protect():
        if request.method=='POST':
            if request.content_length and request.content_length>MAX_BILL+1024*1024:abort(413,'The form and bill attachment exceed 6 MB.')
            if not request.form.get('_csrf') or not hmac.compare_digest(request.form['_csrf'],session.get('record_csrf','')):abort(400,'Reload the requisition form.')
            app.extensions['admission_capacity']['lock']()
        p=getattr(g,'staff_principal',None)
        if p and request.method=='POST':
            row=get_req(request.view_args['rid']);access=app.extensions['staff_access_helpers']
            if row.campus not in access['grant'](p,'requisitions.manage'):abort(403,'Requisition management permission is required for this campus.')
            if request.view_args.get('kind') in ('issue','return','reimburse'):
                cash=account(request.form.get('account_id'),'Assets')
                if cash.name not in p.data.get('accounts',[]):abort(403,'This cash/bank account is not granted to this staff account.')
            if request.view_args.get('kind') in ('issue','reimburse') and p.data.get('two_step'):abort(403,'This staff account requires a separate payment approval. Ask the owner or a payment-authorized manager to post the approved requisition.')
    @bp.errorhandler(ValueError)
    def invalid(exc):
        db.session.rollback();return render_template('operation_error.html',title='Check requisition posting',error=str(exc)),422
    @bp.errorhandler(IntegrityError)
    @bp.errorhandler(StaleDataError)
    def conflict(exc):
        db.session.rollback();return render_template('operation_error.html',title='Check requisition posting',error='This request changed or the submission was already posted. Reload before retrying.'),422
    def upload():
        f=request.files.get('bill_file')
        if not f or not f.filename:return None
        content=f.stream.read(MAX_BILL+1)
        if not content or len(content)>MAX_BILL:raise ValueError('Attach a PDF, PNG or JPEG bill up to 5 MB.')
        if content.startswith(b'%PDF-'):mime='application/pdf';ext='.pdf'
        elif content.startswith(b'\x89PNG\r\n\x1a\n'):mime='image/png';ext='.png'
        elif content.startswith(b'\xff\xd8\xff'):mime='image/jpeg';ext='.jpg'
        else:raise ValueError('Attach a PDF, PNG or JPEG bill; the file contents must match its type.')
        name=secure_filename(f.filename)[:220] or 'bill'
        if not name.lower().endswith(ext):name+=ext
        return name,mime,content
    def validate_day(row,day):
        latest=db.session.query(func.max(Movement.day)).filter_by(req_id=row.id).scalar()
        if latest and day<latest:raise ValueError('Posting date cannot precede the last movement on this requisition.')
    def journal(row,kind,day,submission,fingerprint,lines,notes):
        periods=Period.query.filter(Period.begin<=day,Period.end>=day,Period.closed==False).all()
        if len(periods)!=1:raise ValueError('Exactly one open Accounting Period must cover this posting date.')
        if sum(d for _,d,c in lines)!=sum(c for _,d,c in lines) or len({a.id for a,d,c in lines})<2:raise ValueError('Posting needs distinct accounts and equal debit and credit.')
        who,key=H['actor']();j=Journal(token=hashlib.sha256(('req:'+submission).encode()).hexdigest(),fingerprint=fingerprint,day=day,campus=row.campus,kind='req_'+kind,period_id=periods[0].id,actor=who,actor_key=key);db.session.add(j);db.session.flush()
        db.session.add(Note(journal_id=j.id,narration=(row.number+' · '+kind+' · '+notes)[:1000]))
        for a,d,c in lines:
            if d or c:db.session.add(Line(journal_id=j.id,account_id=a.id,debit=d,credit=c,memo=(row.number+' · '+row.raised_by)[:1000],snapshot=H['snapshot'](a)))
        return j.id
    @bp.route('/<int:rid>/posting/<kind>',methods=['GET','POST'])
    def edit(rid,kind):
        if kind not in ('issue','bill','return','carry','reimburse'):abort(404)
        row=get_req(rid);cfg_row,cfg=config();b=balance(rid)
        if request.method=='GET':
            targets=[r for r in Req.query.filter(Req.campus==row.campus,Req.actor_key==row.actor_key,Req.id!=rid,Req.status=='Approved').order_by(Req.id).all() if r.id>rid]
            return render('requisition_payment.html',title={'issue':'Issue Requisition Payment','bill':'Record Expense Bill','return':'Return Unspent Money','carry':'Carry to Next Requisition','reimburse':'Reimburse Staff'}[kind],row=row,kind=kind,b=b,cfg=cfg,assets=accounts('Assets'),expenses=accounts('Expense'),targets=targets,post_token=secrets.token_urlsafe(32),today=H['today'](),history=movements(rid))
        submission=token();file=upload()
        data={k:request.form.getlist(k) for k in ('version','day','amount','account_id','expense_account','expense_amount','reference','notes','target_id','target_version')}
        fingerprint=digest([rid,kind,H['actor']()[1],data,hashlib.sha256(file[2]).hexdigest() if file else None,file[0] if file else None])
        stored_token=hashlib.sha256(submission.encode()).hexdigest();prior=Movement.query.filter_by(token=stored_token).first()
        if prior:
            if prior.fingerprint!=fingerprint:raise ValueError('This token was already used for different details.')
            return redirect(url_for('req_posting.edit',rid=rid,kind=kind))
        check_version(row)
        if row.status!='Approved':raise ValueError('Only approved requisitions can be posted.')
        try:day=date.fromisoformat(request.form.get('day',''))
        except ValueError:raise ValueError('Choose a valid posting date.')
        if day>H['today']():raise ValueError('Posting date cannot be in the future.')
        validate_day(row,day)
        notes=request.form.get('notes','').strip();reference=request.form.get('reference','').strip()
        if len(notes)>2000 or len(reference)>160:raise ValueError('Use notes up to 2,000 characters and reference up to 160.')
        if file and kind!='bill':raise ValueError('Attachments belong to an expense bill.')
        lines=[];used=0;owed=0;amount=0;target=None;metadata=dict(notes=notes,reference=reference,person=row.actor_key,campus=row.campus)
        if kind=='bill':
            if cfg['require_bill'] and not file:raise ValueError('Attach the bill before posting this expense.')
            if not reference:raise ValueError('Enter the bill or supplier reference.')
            ids=request.form.getlist('expense_account');values=request.form.getlist('expense_amount')
            if not 1<=len(ids)<=100 or len(ids)!=len(values):raise ValueError('Enter 1–100 complete expense lines.')
            for raw,value in zip(ids,values):
                if not raw and not value.strip():continue
                a=account(raw,'Expense');n=H['amount'](value)
                if not n:raise ValueError('Expense lines need positive amounts.')
                amount+=n;lines.append((a,n,0))
            if not amount or amount>row.approved-b['bill']:raise ValueError('Bills cannot exceed the remaining approved expense budget.')
            used=min(b['held'],amount);owed=amount-used
            if used:
                adv=active_mapping(cfg);lines.append((adv,0,used));metadata['advance_account']=adv.id
            if owed:
                payable=account(cfg.get('payable_account'),'Liabilities');lines.append((payable,0,owed));metadata['payable_account']=payable.id
        else:
            amount=H['amount'](request.form.get('amount'))
            if not amount:raise ValueError('Enter a positive amount.')
            if kind=='issue':
                if amount>row.approved-b['committed']:raise ValueError('Issue cannot exceed the approved amount left to fund.')
                adv=active_mapping(cfg);cash=account(request.form.get('account_id'),'Assets')
                if adv.id==cash.id:raise ValueError('Staff Advances and the cash/bank account must be different.')
                lines=[(adv,amount,0),(cash,0,amount)];metadata['advance_account']=adv.id
            elif kind=='return':
                if amount>b['held']:raise ValueError('Return cannot exceed money still held.')
                adv=active_mapping(cfg);cash=account(request.form.get('account_id'),'Assets')
                if adv.id==cash.id:raise ValueError('Choose a cash/bank account different from Staff Advances.')
                lines=[(cash,amount,0),(adv,0,amount)];metadata['advance_account']=adv.id
            elif kind=='reimburse':
                if amount>b['owed']:raise ValueError('Reimbursement cannot exceed the amount payable to this person.')
                payable=account(cfg.get('payable_account'),'Liabilities');cash=account(request.form.get('account_id'),'Assets');lines=[(payable,amount,0),(cash,0,amount)];metadata['payable_account']=payable.id
            else:
                if not cfg['carry_unspent']:raise ValueError('Carry forward is disabled in Requisition Settings.')
                if amount>b['held']:raise ValueError('Carry cannot exceed money still held.')
                try:target_id=int(request.form.get('target_id',''))
                except ValueError:raise ValueError('Choose an approved next requisition.')
                target=get_req(target_id)
                if target.id<=rid or target.actor_key!=row.actor_key or target.campus!=row.campus or target.status!='Approved':raise ValueError('Carry only to a later approved requisition for the same person and campus.')
                if request.form.get('target_version')!=str(target.version):raise ValueError('Target requisition changed. Reload its current version.')
                validate_day(target,day)
                if amount>target.approved-balance(target.id)['committed']:raise ValueError('Carry exceeds the target approved amount left to fund.')
                remaining=amount;carry_lots=[]
                for d,n in b['lots']:
                    used=min(n,remaining)
                    if used:carry_lots.append([d.isoformat(),used]);remaining-=used
                metadata['target_id']=target.id;metadata['lots']=carry_lots
                periods=Period.query.filter(Period.begin<=day,Period.end>=day,Period.closed==False).all()
                if len(periods)!=1:raise ValueError('An open Accounting Period must cover a carry date.')
        jid=journal(row,kind,day,submission,fingerprint,lines,notes) if lines else None
        m=Movement(req_id=rid,kind='carry_out' if kind=='carry' else kind,day=day,amount=amount,advance_used=used,payable=owed,journal_id=jid,token=stored_token,fingerprint=fingerprint,actor=H['actor']()[0],data=metadata)
        if file:m.filename,m.mime,m.content=file
        db.session.add(m)
        if target:
            db.session.add(Movement(req_id=target.id,kind='carry_in',day=day,amount=amount,token=hashlib.sha256((submission+':in').encode()).hexdigest(),fingerprint=fingerprint,actor=H['actor']()[0],data=dict(source_id=rid,notes=notes,campus=row.campus,person=row.actor_key,lots=metadata['lots'])))
            target.version+=1
        row.version+=1
        db.session.add(Audit(action='Post requisition '+kind,data=dict(id=rid,campus=row.campus,actor=H['actor']()[0],amount=amount,journal_id=jid,target_id=target.id if target else None)))
        db.session.commit();flash('Saved. '+('Carry moves the allocation between requests; the same person still holds the money.' if target else 'A balanced ledger voucher and requisition movement were recorded together.'),'success')
        return redirect(url_for('req_posting.edit',rid=rid,kind=kind))
    @bp.get('/attachment/<int:mid>')
    def attachment(mid):
        if not 0<mid<10**18:abort(404)
        movement=db.get_or_404(Movement,mid);get_req(movement.req_id)
        if not movement.content:abort(404)
        response=send_file(io.BytesIO(movement.content),mimetype=movement.mime,as_attachment=True,download_name=movement.filename,max_age=0)
        response.headers['X-Content-Type-Options']='nosniff';response.headers['Content-Security-Policy']="sandbox; default-src 'none'";response.headers['Cache-Control']='private, no-store'
        return response
    app.extensions['requisition_posting']=dict(balance=balance,movements=movements,open_for=open_for,accounts=accounts)
    app.register_blueprint(bp)
