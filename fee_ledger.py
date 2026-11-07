"""Opt-in cash-basis fee receipts and atomic, append-only ledger reversals."""
import hashlib,hmac,json,secrets
from flask import Blueprint,abort,flash,g,redirect,render_template,request,session,url_for
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import StaleDataError


def configure_fee_ledger(app,db,Student):
    bp=Blueprint('fee_ledger',__name__,url_prefix='/workspace/finance/fee-posting')
    F=app.extensions['finance_models'];L=app.extensions['ledger_models'];O=app.extensions['ops_models'];R=app.extensions['record_models']
    Account=F['account'];Group=F['group'];Period=F['period'];Journal=L['journal'];Line=L['line'];Receipt=O['receipt'];Audit=O['audit']
    class Config(db.Model):
        __tablename__='fee_ledger_config'
        id=db.Column(db.Integer,primary_key=True)
        enabled=db.Column(db.Boolean,nullable=False,default=False)
        income_account=db.Column(db.Integer,db.ForeignKey('finance_account.id',ondelete='RESTRICT'))
        discount_account=db.Column(db.Integer,db.ForeignKey('finance_account.id',ondelete='RESTRICT'))
        receiving=db.Column(db.JSON,nullable=False,default=dict)
        version=db.Column(db.Integer,nullable=False,default=1)
        __mapper_args__={'version_id_col':version}
    class Posting(db.Model):
        __tablename__='fee_receipt_posting'
        id=db.Column(db.Integer,primary_key=True)
        receipt_id=db.Column(db.Integer,db.ForeignKey('receipt.id',ondelete='RESTRICT'),unique=True,nullable=False)
        student_id=db.Column(db.Integer,db.ForeignKey('student.id',ondelete='RESTRICT'),nullable=False)
        campus=db.Column(db.String(160),nullable=False)
        journal_id=db.Column(db.Integer,db.ForeignKey('finance_journal.id',ondelete='RESTRICT'),nullable=False,unique=True)
        reversal_id=db.Column(db.Integer,db.ForeignKey('finance_journal.id',ondelete='RESTRICT'),unique=True)
        source=db.Column(db.JSON,nullable=False)
    app.extensions['fee_ledger_models']=dict(config=Config,posting=Posting)
    def account(raw,cls,active=True):
        if not str(raw).isdigit():raise ValueError('Choose an active '+cls+' ledger account.')
        row=db.session.get(Account,int(raw))
        if not row or row.group.account_class!=cls or (active and (row.inactive or not row.group.active)):raise ValueError('Choose an active '+cls+' ledger account.')
        return row
    def snap(a):return dict(code=a.code,name=a.name,group_id=a.group_id,group=a.group.name,account_class=a.group.account_class)
    def period(day):
        rows=Period.query.filter(Period.begin<=day,Period.end>=day).all()
        if len(rows)!=1 or rows[0].closed:raise ValueError('Fee ledger posting needs one open Accounting Period covering '+day.isoformat()+'. No payment or reversal was saved.')
        return rows[0]
    def actor():
        staff=getattr(g,'staff_principal',None)
        if staff:return staff.username,'staff:'+str(staff.id)
        identity=getattr(g,'school_identity',None) or {}
        return identity.get('email') or 'Demo visitor','owner:'+str(session['owner_id']) if session.get('owner_id') else 'demo'
    def journal(day,campus,kind,lines,receipt_id):
        if sum(d for a,d,c,s in lines)!=sum(c for a,d,c,s in lines):raise ValueError('Fee ledger journal does not balance.')
        who,key=actor();p=period(day);token=secrets.token_urlsafe(32)
        row=Journal(token=token,fingerprint=hashlib.sha256(token.encode()).hexdigest(),day=day,campus=campus,kind=kind,period_id=p.id,actor=who,actor_key=key)
        db.session.add(row);db.session.flush()
        db.session.add(L['note'](journal_id=row.id,narration='Automatic '+kind.replace('_',' ')+' for receipt #'+str(receipt_id)))
        for aid,d,c,snapshot in lines:
            if d or c:db.session.add(Line(journal_id=row.id,account_id=aid,debit=d,credit=c,memo='Fee receipt #'+str(receipt_id),snapshot=snapshot))
        return row
    def post(receipt):
        with db.session.no_autoflush:app.extensions['admission_capacity']['lock']()
        config=db.session.get(Config,1)
        if not config or not config.enabled:return None
        db.session.flush()
        prior=Posting.query.filter_by(receipt_id=receipt.id).first()
        if prior:
            if (receipt.amount,receipt.discount)!=(prior.source['amount'],prior.source['discount']):raise ValueError('A linked receipt cannot change its posted amounts.')
            return prior
        if receipt.voided or receipt.amount<0 or receipt.discount<0 or receipt.amount+receipt.discount<=0:raise ValueError('Only positive, active receipts can be posted.')
        detail=R['student'].query.filter_by(student_id=receipt.student_id).first();campus=(detail.data or {}).get('campus','') if detail else ''
        if campus not in app.extensions['ledger_helpers']['campuses']():raise ValueError('Set the student campus before automatic fee posting.')
        # No inferred line allocation: the configured income account receives
        # all fees. Bill generation itself does not recognize receivables/income.
        receiving=config.receiving.get(receipt.account)
        asset=account(receiving,'Assets') if receipt.amount else None
        discount=account(config.discount_account,'Expense') if receipt.discount else None
        income=account(config.income_account,'Income');lines=[]
        if asset:lines.append((asset.id,receipt.amount,0,snap(asset)))
        if discount:lines.append((discount.id,receipt.discount,0,snap(discount)))
        lines.append((income.id,0,receipt.amount+receipt.discount,snap(income)))
        row=journal(receipt.day,campus,'fee_receipt',lines,receipt.id)
        link=Posting(receipt_id=receipt.id,student_id=receipt.student_id,campus=campus,journal_id=row.id,source=dict(amount=receipt.amount,discount=receipt.discount,day=receipt.day.isoformat(),receiving=receipt.account,bill_id=receipt.bill_id));db.session.add(link)
        db.session.add(Audit(action='Post fee receipt to ledger',data=dict(receipt_id=receipt.id,journal_id=row.id,campus=campus)))
        return link
    def reverse(receipt):
        with db.session.no_autoflush:app.extensions['admission_capacity']['lock']()
        # Look up only the original campus before applying scoped ORM reads.
        # A pupil may have moved campuses since payment; never silently skip
        # the journal reversal because a scope filter hid its link.
        table=Posting.__table__
        source=db.session.execute(db.select(table.c.id,table.c.campus).where(table.c.receipt_id==receipt.id).with_for_update()).first()
        if source and getattr(g,'staff_principal',None) is not None and source.campus not in getattr(g,'access_campuses',set()):abort(403,'Receipt reversal requires access to the original posting campus.')
        link=db.session.get(Posting,source.id) if source else None
        if not link or link.reversal_id:return
        if (receipt.amount,receipt.discount)!=(link.source['amount'],link.source['discount']):raise ValueError('Receipt amounts changed after posting. Review its ledger source.')
        old=Line.query.filter_by(journal_id=link.journal_id).order_by(Line.id).all()
        # Reverse on the current date; original closed periods and frozen
        # history remain intact. Reuse original snapshots, even retired accounts.
        row=journal(app.extensions['ledger_helpers']['today'](),link.campus,'fee_reversal',[(line.account_id,line.credit,line.debit,line.snapshot) for line in old],receipt.id)
        link.reversal_id=row.id
        db.session.add(Audit(action='Reverse fee receipt ledger posting',data=dict(receipt_id=receipt.id,journal_id=row.id,campus=link.campus)))
    @bp.before_request
    def protect():
        if request.method=='POST':
            if not request.form.get('_csrf') or not hmac.compare_digest(request.form['_csrf'],session.get('record_csrf','')):abort(400,'Reload fee ledger settings.')
            app.extensions['admission_capacity']['lock']()
    @bp.errorhandler(ValueError)
    def invalid(error):db.session.rollback();return render_template('operation_error.html',title='Check fee ledger settings',error=str(error)),422
    @bp.errorhandler(IntegrityError)
    @bp.errorhandler(StaleDataError)
    def conflict(error):db.session.rollback();return render_template('operation_error.html',title='Check fee ledger settings',error='Concurrent settings/posting changed. Reload; no partial payment was posted.'),422
    @bp.route('',methods=['GET','POST'])
    def settings():
        row=db.session.get(Config,1)
        if request.method=='POST':
            if request.form.get('version')!=str(row.version if row else 0):raise ValueError('Settings changed. Reload before saving.')
            enabled=request.form.get('enabled')=='1';mapping={}
            names=request.form.getlist('receiving_name');ids=request.form.getlist('asset_id')
            if len(names)!=len(ids) or len(names)>100:raise ValueError('Enter complete receiving account mappings (up to 100).')
            for name,raw in zip(names,ids):
                name=name.strip()
                if not name and not raw:continue
                if not name or len(name)>160 or name.casefold() in {k.casefold() for k in mapping}:raise ValueError('Receiving account names must be distinct and at most 160 characters.')
                mapping[name]=account(raw,'Assets',active=enabled).id
            income=account(request.form.get('income_account'),'Income',active=enabled).id if enabled or request.form.get('income_account') else None
            discount=account(request.form.get('discount_account'),'Expense',active=enabled).id if enabled or request.form.get('discount_account') else None
            if enabled and not mapping:raise ValueError('Map at least one receiving account before enabling.')
            row=row or Config(id=1);db.session.add(row);row.enabled=enabled;row.receiving=mapping;row.income_account=income;row.discount_account=discount
            db.session.add(Audit(action='Configure fee ledger posting',data=dict(enabled=enabled,receiving=list(mapping),income=income,discount=discount)))
            db.session.commit();flash('Fee ledger settings saved. Earlier receipts were not backfilled.','success');return redirect(url_for('fee_ledger.settings'))
        accounts=Account.query.join(Group).order_by(Account.code).all()
        mapped=row.receiving if row else {};receipts=Receipt.query.filter_by(voided=False).count();linked=Posting.query.count()
        return render_template('fee_ledger_settings.html',title='Automatic Fee Ledger Posting',config=row,accounts=accounts,mappings=list(mapped.items())+[('',''),('','')],receipts=receipts,linked=linked)
    app.extensions['fee_ledger_helpers']=dict(post=post,reverse=reverse)
    app.register_blueprint(bp)
