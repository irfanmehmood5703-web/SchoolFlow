"""School-scoped shareholder capital records with balanced journal postings."""
import csv,hashlib,hmac,io,json,re,secrets
from datetime import date,datetime,timezone
from flask import Blueprint,Response,abort,flash,g,redirect,render_template,request,session,url_for
from sqlalchemy import func,or_
from sqlalchemy.exc import IntegrityError

KINDS={'contribution':'Capital contribution','withdrawal':'Capital withdrawal','profit':'Profit payout'}

def configure_shareholder_posting(app,db):
    bp=Blueprint('shareholder_posting',__name__,url_prefix='/workspace/finance/shareholders')
    P=app.extensions['shareholder_model'];H=app.extensions['ledger_helpers'];M=app.extensions['finance_models'];Account=M['account']
    Ledger=app.extensions['ledger_models'];J=Ledger['journal'];L=Ledger['line'];Audit=app.extensions['ops_models']['audit']
    class Movement(db.Model):
        __tablename__='shareholder_movement'
        id=db.Column(db.Integer,primary_key=True)
        partner_id=db.Column(db.Integer,db.ForeignKey('finance_shareholder.id',ondelete='RESTRICT'),nullable=False,index=True)
        journal_id=db.Column(db.Integer,db.ForeignKey('finance_journal.id',ondelete='RESTRICT'),nullable=False,unique=True)
        kind=db.Column(db.String(20),nullable=False)
        amount=db.Column(db.BigInteger,nullable=False)
        day=db.Column(db.Date,nullable=False)
        campus=db.Column(db.String(160),nullable=False)
        token=db.Column(db.String(64),nullable=False,unique=True)
        fingerprint=db.Column(db.String(64),nullable=False)
        actor_key=db.Column(db.String(100),nullable=False)
        actor=db.Column(db.String(254),nullable=False)
        created=db.Column(db.DateTime,nullable=False,default=lambda:datetime.now(timezone.utc))
        reversal_of=db.Column(db.Integer,db.ForeignKey('shareholder_movement.id',ondelete='RESTRICT'),unique=True)
        data=db.Column(db.JSON,nullable=False)
        __table_args__=(db.CheckConstraint('amount > 0',name='shareholder_positive_movement'),)
    class Revision(db.Model):
        __tablename__='shareholder_revision'
        id=db.Column(db.Integer,primary_key=True)
        partner_id=db.Column(db.Integer,db.ForeignKey('finance_shareholder.id',ondelete='RESTRICT'),nullable=False,index=True)
        actor=db.Column(db.String(254),nullable=False)
        created=db.Column(db.DateTime,nullable=False,default=lambda:datetime.now(timezone.utc))
        before=db.Column(db.JSON)
        after=db.Column(db.JSON,nullable=False)
    app.extensions['shareholder_posting_models']=dict(movement=Movement,revision=Revision)

    @bp.before_request
    def protect():
        if request.method=='POST':
            if not request.form.get('_csrf') or not hmac.compare_digest(request.form['_csrf'],session.get('record_csrf','')):abort(400,'Reload this shareholder form.')
            app.extensions['admission_capacity']['lock']()
    @bp.errorhandler(ValueError)
    def invalid(exc):
        db.session.rollback();return render_template('operation_error.html',title='Check shareholder transaction',error=str(exc)),422
    @bp.errorhandler(IntegrityError)
    def conflict(exc):
        db.session.rollback();return render_template('operation_error.html',title='Check shareholder transaction',error='Another request changed this transaction. Reload before trying again.'),422

    def source_balance(account_id,campus,day):
        return int(H['scoped']([campus],[]).filter(L.account_id==account_id,J.day<=day).with_entities(func.coalesce(func.sum(L.credit-L.debit),0)).scalar())
    def cash_access(account,outgoing):
        staff=getattr(g,'staff_principal',None)
        if staff:
            if account.name not in staff.data.get('accounts',[]):abort(403,'This cash/bank account is not granted to this staff account.')
            if outgoing and staff.data.get('two_step'):abort(403,'This account requires a separate payment approval. Ask the school owner to record the approved shareholder payment.')
    def account(aid,cls):
        row=db.session.get(Account,H['identity'](aid))
        if not row or row.inactive or not row.group.active or row.group.account_class!=cls:raise ValueError('Choose an active '+cls+' account.')
        return row
    def submission(data):
        token=request.form.get('post_token','')
        if not re.fullmatch(r'[A-Za-z0-9_-]{32,64}',token):raise ValueError('Reload this transaction form.')
        digest=hashlib.sha256(json.dumps(data,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        prior=Movement.query.filter_by(token=token).first()
        if prior and (prior.fingerprint!=digest or prior.actor_key!=H['actor']()[1]):raise ValueError('This submission token was already used with different details.')
        return token,digest,prior
    def day_value():
        try:return date.fromisoformat(request.form.get('day',''))
        except ValueError:raise ValueError('Choose a valid transaction date.')
    def notes():
        memo=request.form.get('notes','').strip();reference=request.form.get('reference','').strip()
        if len(memo)>700 or len(reference)>100:raise ValueError('Use a reference up to 100 characters and notes up to 700 characters.')
        return memo,reference
    def monotonic(row,campus,day):
        latest=H['scoped']([campus],[]).filter(L.account_id==row.account_id).with_entities(func.max(J.day)).scalar() if row.account_id else None
        last=db.session.query(func.max(Movement.day)).filter_by(partner_id=row.id,campus=campus).scalar()
        if any(d and d>day for d in (latest,last)):raise ValueError('Choose a date on or after the latest shareholder/capital activity in this campus.')
    def post(row,kind,day,campus,token,digest,lines,data,reversal_of=None):
        # Reuse the canonical journal validator for dates, campuses, periods and
        # money bounds. Reversals retain retired account snapshots intentionally.
        periods=M['period'].query.filter(M['period'].begin<=day,M['period'].end>=day).all()
        if len(periods)!=1 or periods[0].closed:raise ValueError('Exactly one open Accounting Period must cover this date.')
        if campus not in H['campuses']():raise ValueError('Choose a configured campus.')
        if sum(d for _,d,c,_ in lines)!=sum(c for _,d,c,_ in lines) or len({aid for aid,_,_,_ in lines})<2:raise ValueError('The shareholder journal must balance across distinct accounts.')
        who,key=H['actor']();journal=J(token=hashlib.sha256(('shareholder:'+token).encode()).hexdigest(),fingerprint=digest,day=day,campus=campus,kind='share_'+kind,period_id=periods[0].id,actor=who,actor_key=key)
        db.session.add(journal);db.session.flush()
        narration=(data['partner_name']+' · '+kind+' · '+data.get('reference','')+' · '+data.get('notes',''))[:1000]
        db.session.add(Ledger['note'](journal_id=journal.id,narration=narration))
        for aid,debit,credit,snapshot in lines:db.session.add(L(journal_id=journal.id,account_id=aid,debit=debit,credit=credit,memo=narration,snapshot=snapshot))
        movement=Movement(partner_id=row.id,journal_id=journal.id,kind=kind,amount=sum(d for _,d,_,_ in lines),day=day,campus=campus,token=token,fingerprint=digest,actor_key=key,actor=who,reversal_of=reversal_of,data=data)
        db.session.add(movement);db.session.flush()
        if reversal_of:
            original=db.session.get(Movement,reversal_of)
            Change=app.extensions['journal_change_models']['change']
            db.session.add(Change(journal_id=original.journal_id,reversal_id=journal.id,actor=who))
        db.session.add(Audit(action='Record shareholder '+kind,data=dict(partner_id=row.id,movement_id=movement.id,journal_id=journal.id,actor=who,amount=movement.amount,reversal_of=reversal_of)))
        db.session.commit();return movement

    @bp.route('/<int:rid>/record/<kind>',methods=['GET','POST'])
    def record(rid,kind):
        if kind not in KINDS:abort(404)
        row=db.get_or_404(P,rid)
        if request.method=='POST':
            day=day_value();campus=request.form.get('campus','');memo,ref=notes();amount=H['amount'](request.form.get('amount',''))
            if amount<=0:raise ValueError('Enter an amount greater than zero.')
            payload=dict(partner=rid,kind=kind,day=day.isoformat(),campus=campus,amount=amount,cash=request.form.get('cash_account',''),distribution=request.form.get('distribution_account','') if kind=='profit' else '',reference=ref,notes=memo,version=request.form.get('version',''))
            token,digest,prior=submission(payload)
            if prior:return redirect(url_for('ledger.voucher',jid=prior.journal_id))
            if request.form.get('version')!=str(row.version):raise ValueError('This shareholder changed. Reload the form.')
            if not row.active:raise ValueError('This shareholder is a former partner. Reactivate the profile before recording new money.')
            if row.since and day<row.since:raise ValueError('The date cannot precede Partner Since.')
            if row.campus and campus!=row.campus:raise ValueError('Choose the shareholder\'s configured campus.')
            cash=account(request.form.get('cash_account',''),'Assets');cash_access(cash,kind!='contribution')
            source=account(request.form.get('distribution_account','') if kind=='profit' else row.account_id,'Equity')
            if kind=='profit' and P.query.filter_by(account_id=source.id).first():raise ValueError('Use an unallocated earnings/distribution Equity account, separate from every shareholder capital account.')
            monotonic(row,campus,day)
            source_latest=H['scoped']([campus],[]).filter(L.account_id==source.id).with_entities(func.max(J.day)).scalar()
            if source_latest and source_latest>day:raise ValueError('Choose a date on or after the latest activity on the selected Equity account.')
            campus_row=db.session.get(app.extensions['institute_setup_models']['campus'],campus)
            if campus_row and not campus_row.active:raise ValueError('Choose an active campus.')
            if kind!='contribution' and source_balance(source.id,campus,day)<amount:raise ValueError('The selected campus has insufficient recorded '+('distribution Equity' if kind=='profit' else 'shareholder capital')+' balance for this amount.')
            cash_snapshot=H['snapshot'](cash);source_snapshot=H['snapshot'](source)
            lines=[(cash.id,amount,0,cash_snapshot),(source.id,0,amount,source_snapshot)] if kind=='contribution' else [(source.id,amount,0,source_snapshot),(cash.id,0,amount,cash_snapshot)]
            data=dict(partner_name=row.name,percentage_bp=row.equity_bp,reference=ref,notes=memo,cash_account=cash.id,source_account=source.id)
            movement=post(row,kind,day,campus,token,digest,lines,data)
            flash(KINDS[kind]+' recorded with a balanced ledger voucher.','success');return redirect(url_for('ledger.voucher',jid=movement.journal_id))
        options=H['options']()
        return render_template('shareholder_movement.html',title=KINDS[kind],row=row,kind=kind,kinds=KINDS,campuses=[row.campus] if row.campus else H['campuses'](),cash_accounts=[a for a in options if a.group.account_class=='Assets'],equity_accounts=[a for a in options if a.group.account_class=='Equity' and not P.query.filter_by(account_id=a.id).first()],today=H['today'](),post_token=secrets.token_urlsafe(32))

    @bp.route('/<int:rid>/reverse/<int:mid>',methods=['GET','POST'])
    def reverse(rid,mid):
        row=db.get_or_404(P,rid);original=db.get_or_404(Movement,mid)
        if original.partner_id!=rid or original.reversal_of:abort(404)
        existing=Movement.query.filter_by(reversal_of=mid).first()
        if request.method=='POST':
            day=day_value();memo,ref=notes()
            if not memo:raise ValueError('Enter a reason for reversal.')
            if request.form.get('confirm')!='1':raise ValueError('Confirm this reversal before saving.')
            payload=dict(partner=rid,reversal_of=mid,day=day.isoformat(),notes=memo,reference=ref)
            token,digest,prior=submission(payload)
            if prior:return redirect(url_for('ledger.voucher',jid=prior.journal_id))
            if existing:raise ValueError('This transaction has already been reversed.')
            if day<original.day:raise ValueError('Reversal date cannot precede the original transaction.')
            monotonic(row,original.campus,day)
            cash=db.get_or_404(Account,original.data['cash_account']);cash_access(cash,original.kind=='contribution')
            if original.kind=='contribution' and source_balance(original.data['source_account'],original.campus,day)<original.amount:raise ValueError('This contribution cannot be reversed after its capital has been withdrawn. Review the later transactions first.')
            old=L.query.filter_by(journal_id=original.journal_id).order_by(L.id).all()
            data=dict(original.data,notes=memo,reference=ref)
            reversal=post(row,'reverse',day,original.campus,token,digest,[(line.account_id,line.credit,line.debit,line.snapshot) for line in old],data,original.id)
            flash('Reversal recorded; the original voucher remains in history.','success');return redirect(url_for('ledger.voucher',jid=reversal.journal_id))
        return render_template('shareholder_reversal.html',title='Reverse shareholder transaction',row=row,original=original,existing=existing,today=H['today'](),post_token=secrets.token_urlsafe(32),kinds=KINDS)

    def statement(row):
        start,end,scope,users=H['filters']();own=[row.campus] if row.campus else []
        movements=Movement.query.filter_by(partner_id=row.id).order_by(Movement.day,Movement.id).all()
        journal_ids=[m.journal_id for m in movements];by_journal={m.journal_id:m for m in movements};reversed_ids={m.reversal_of for m in movements if m.reversal_of}
        q=H['scoped'](own,[]).filter(J.day>=start,J.day<=end)
        conditions=[J.id.in_(journal_ids)]
        if row.account_id:conditions.append(L.account_id==row.account_id)
        lines=q.filter(or_(*conditions)).order_by(J.day,J.id,L.id).all()
        # A movement's asset and Equity lines are both in the ledger; show only
        # its Equity side here so its amount is counted once in the statement.
        lines=[l for l in lines if l.account_id==row.account_id or (l.journal_id in by_journal and l.snapshot['account_class']=='Equity')]
        opening=closing=None
        if row.account_id:
            base=H['scoped'](own,[]).filter(L.account_id==row.account_id)
            opening=int(base.filter(J.day<start).with_entities(func.coalesce(func.sum(L.credit-L.debit),0)).scalar())
            closing=int(base.filter(J.day<=end).with_entities(func.coalesce(func.sum(L.credit-L.debit),0)).scalar())
        if request.args.get('export')=='csv':
            def safe(s):
                s=str(s or '');return "'"+s if s.startswith(('=','+','-','@','\t','\r')) else s
            output=io.StringIO();writer=csv.writer(output);writer.writerow(['Date','Journal','Campus','Type','Equity debit','Equity credit','Reference','Memo','Posted by'])
            for l in lines:
                m=by_journal.get(l.journal_id);writer.writerow([l.journal.day,l.journal_id,safe(l.journal.campus),KINDS.get(m.kind,m.kind) if m else 'Journal',f'{l.debit/100:.2f}',f'{l.credit/100:.2f}',safe(m.data.get('reference','') if m else ''),safe(l.memo),safe(l.journal.actor)])
            return Response('\ufeff'+output.getvalue(),mimetype='text/csv',headers={'Content-Disposition':f'attachment; filename=shareholder-{row.id}-transactions.csv'})
        return render_template('shareholder_transactions.html',title='Shareholder Transactions',row=row,lines=lines,start=start,end=end,opening=opening,closing=closing,by_journal=by_journal,reversed_ids=reversed_ids,kinds=KINDS)
    app.extensions['shareholder_posting_helpers']=dict(statement=statement)

    @bp.get('/<int:rid>/history')
    def history(rid):
        row=db.get_or_404(P,rid);rows=Revision.query.filter_by(partner_id=rid).order_by(Revision.id.desc()).all()
        return render_template('shareholder_history.html',title='Shareholder profile history',row=row,rows=rows)
    app.register_blueprint(bp)
