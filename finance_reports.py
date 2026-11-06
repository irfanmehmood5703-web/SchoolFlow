"""Reference Journal Inquiry, General Ledger, Day Wise P&L and audited corrections."""
import hashlib,hmac,json,re,secrets
from datetime import date,datetime,time,timedelta,timezone
from decimal import Decimal
from zoneinfo import ZoneInfo
from flask import Blueprint,abort,flash,g,redirect,render_template,request,session,url_for
from sqlalchemy import func,or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload
from finance_ledger import TABS
from finance_setup import CLASSES

MENU=[('journals','Journal Inquiry'),('general','General Ledger'),('daily','Day Wise P & L (New)')]

def configure_finance_reports(app,db):
    bp=Blueprint('finance_reports',__name__,url_prefix='/workspace/finance/reports')
    H=app.extensions['ledger_helpers'];Journal=app.extensions['ledger_models']['journal'];Line=app.extensions['ledger_models']['line'];Period=app.extensions['finance_models']['period'];Account=app.extensions['finance_models']['account'];Audit=app.extensions['ops_models']['audit']
    class Change(db.Model):
        __tablename__='finance_journal_change'
        id=db.Column(db.Integer,primary_key=True)
        journal_id=db.Column(db.Integer,db.ForeignKey('finance_journal.id',ondelete='RESTRICT'),nullable=False,unique=True)
        reversal_id=db.Column(db.Integer,db.ForeignKey('finance_journal.id',ondelete='RESTRICT'),nullable=False,unique=True)
        replacement_id=db.Column(db.Integer,db.ForeignKey('finance_journal.id',ondelete='RESTRICT'),unique=True)
        actor=db.Column(db.String(254),nullable=False)
        created=db.Column(db.DateTime,nullable=False,default=lambda:datetime.now(timezone.utc))
    class Action(db.Model):
        __tablename__='finance_journal_action'
        token=db.Column(db.String(64),primary_key=True)
        digest=db.Column(db.String(64),nullable=False)
        result=db.Column(db.JSON,nullable=False)
    app.extensions['journal_change_models']=dict(change=Change,action=Action)
    def local(value):return value.replace(tzinfo=timezone.utc).astimezone(ZoneInfo('Asia/Karachi')).strftime('%Y-%m-%d %H:%M:%S')
    def render(template,**kw):return render_template(template,tabs=TABS,finance_report_menu=MENU,classes=CLASSES,campuses=H['campuses'](),finance_time=local,**kw)
    @bp.before_request
    def protect():
        if request.method=='POST':
            if not request.form.get('_csrf') or not hmac.compare_digest(request.form['_csrf'],session.get('record_csrf','')):abort(400,'Reload this Finance form.')
            app.extensions['admission_capacity']['lock']()
            p=getattr(g,'staff_principal',None)
            if p is not None and request.form.get('save_action')=='print':
                access=app.extensions['staff_access_helpers']
                if access['grant'](p,'finance.print')!=set(access['campuses']()):abort(403,'Finance print permission is required.')
    @bp.errorhandler(ValueError)
    def invalid(exc):
        db.session.rollback();return render_template('operation_error.html',title='Check Finance report',error=str(exc)),422
    @bp.errorhandler(IntegrityError)
    def conflict(exc):
        db.session.rollback();return render_template('operation_error.html',title='Check Finance report',error='This transaction changed or was already corrected. Reload before retrying.'),422
    def journal(jid):
        if not 0<jid<10**18:abort(404)
        return db.get_or_404(Journal,jid)
    def period_open(row):
        period=db.session.get(Period,row.period_id)
        if not period or period.closed or not period.begin<=row.day<=period.end:raise ValueError('Reopen the original Accounting Period before correcting or voiding this transaction.')
    def check_original(row):
        if row.kind not in ('journal','expense','income'):raise ValueError('System/reversal entries cannot be edited or deleted here.')
        if Change.query.filter_by(journal_id=row.id).first():raise ValueError('This transaction was already voided or corrected. Open its replacement instead.')
        period_open(row)
    def retry(action,ids):
        token=request.form.get('action_token','')
        if not re.fullmatch(r'[A-Za-z0-9_-]{32,64}',token):raise ValueError('Reload this action before saving.')
        payload={k:request.form.getlist(k) for k in ('day','campus','account_id','debit','credit','amount','memo','counter_account','confirm')}
        if request.form.get('narration','').strip():payload['narration']=[request.form['narration'].strip()]
        digest=hashlib.sha256(json.dumps([action,ids,H['actor']()[1],payload],sort_keys=True,separators=(',',':')).encode()).hexdigest()
        prior=db.session.get(Action,token)
        if prior and prior.digest!=digest:raise ValueError('This action token has already been used for different data.')
        return token,digest,prior
    def reverse(row,who):
        original=Line.query.filter_by(journal_id=row.id).order_by(Line.id).all()
        if not original or sum(x.debit for x in original)!=sum(x.credit for x in original):raise ValueError('An unbalanced historical transaction requires investigation before reversal.')
        reverse=Journal(token=secrets.token_urlsafe(32),fingerprint=hashlib.sha256(('reverse:'+str(row.id)).encode()).hexdigest(),day=row.day,campus=row.campus,kind='reversal',period_id=row.period_id,actor=who,actor_key=H['actor']()[1]);db.session.add(reverse);db.session.flush()
        for line in original:db.session.add(Line(journal_id=reverse.id,account_id=line.account_id,debit=line.credit,credit=line.debit,memo=('Reversal of #'+str(row.id)+' · '+line.memo)[:1000],snapshot=dict(line.snapshot)))
        return reverse
    @bp.route('/journal/<int:jid>/edit',methods=['GET','POST'])
    def correct(jid):
        source=journal(jid)
        if request.method=='POST':
            token,digest,prior=retry('edit',[jid])
            if prior:return redirect(url_for('ledger.voucher',jid=prior.result['replacement'],**({'print':'1'} if request.form.get('save_action')=='print' else {})))
            check_original(source);day,campus,period,lines=H['prepare'](source.kind,request.form);who,key=H['actor']()
            reversal=reverse(source,who)
            replacement=Journal(token=secrets.token_urlsafe(32),fingerprint=digest,day=day,campus=campus,kind=source.kind,period_id=period.id,actor=who,actor_key=key);db.session.add(replacement);db.session.flush()
            if request.form.get('narration','').strip():db.session.add(app.extensions['ledger_models']['note'](journal_id=replacement.id,narration=request.form['narration'].strip()))
            for a,d,c,m in lines:db.session.add(Line(journal_id=replacement.id,account_id=a.id,debit=d,credit=c,memo=m,snapshot=H['snapshot'](a)))
            db.session.add(Change(journal_id=jid,reversal_id=reversal.id,replacement_id=replacement.id,actor=who));db.session.add(Action(token=token,digest=digest,result={'replacement':replacement.id}))
            db.session.add(Audit(action='Correct Finance journal',data={'original':jid,'reversal':reversal.id,'replacement':replacement.id,'actor':who}));db.session.commit()
            flash('Transaction corrected with an audited reversal and replacement. Original voucher retained.','success')
            return redirect(url_for('ledger.voucher',jid=replacement.id,**({'print':'1'} if request.form.get('save_action')=='print' else {})))
        check_original(source);lines=Line.query.filter_by(journal_id=jid).order_by(Line.id).all();rows=[];counter=None
        for line in lines:
            if source.kind!='journal' and line.snapshot['account_class']=='Assets':counter=line.account_id;continue
            rows.append(dict(account_id=line.account_id,debit=f'{Decimal(line.debit)/100:.2f}' if line.debit else '',credit=f'{Decimal(line.credit)/100:.2f}' if line.credit else '',amount=f'{Decimal(line.debit+line.credit)/100:.2f}',memo=line.memo))
        return render('ledger_entry.html',title='Edit Transaction #'+str(jid),kind=source.kind,accounts=H['options'](),today=source.day.isoformat(),post_token=secrets.token_urlsafe(32),entry_campus=source.campus,entry_rows=rows,counter_account=counter,correction_source=source,entry_narration=source.note.narration if source.note else '')
    @bp.post('/journal/void')
    def void():
        raw=request.form.getlist('journal_ids')
        if not raw or len(raw)>100 or any(not re.fullmatch(r'[0-9]{1,18}',r) for r in raw):raise ValueError('Select 1–100 valid transactions.')
        ids=sorted({int(r) for r in raw});token,digest,prior=retry('void',ids)
        if prior:return redirect(url_for('finance_reports.journals'))
        if request.form.get('confirm')!='1':raise ValueError('Confirm voiding the selected transactions. Reversals preserve their accounting history.')
        originals=[journal(jid) for jid in ids]
        for row in originals:check_original(row)
        who,key=H['actor']()
        for row in originals:
            reversal=reverse(row,who);db.session.add(Change(journal_id=row.id,reversal_id=reversal.id,actor=who))
        db.session.add(Action(token=token,digest=digest,result={'voided':ids}));db.session.add(Audit(action='Void Finance journals',data={'ids':ids,'actor':who}));db.session.commit()
        flash('Selected transactions voided using balanced reversals. Their original vouchers remain in audit history.','success')
        return redirect(url_for('finance_reports.journals'))
    def range_query():
        start,end,scope,users=H['filters']()
        if request.path.endswith('/voided'):
            if not request.args.get('from'):start=db.session.query(func.min(Journal.day)).scalar() or start
            if not request.args.get('to'):end=max(end,db.session.query(func.max(Journal.day)).scalar() or end)
        q=Journal.query.filter(Journal.day>=start,Journal.day<=end)
        if scope:q=q.filter(Journal.campus.in_(scope))
        if users:q=q.filter(Journal.actor_key.in_(users))
        raw=request.args.get('trans_id','')
        if raw:q=q.filter(Journal.id==H['identity'](raw))
        raw=request.args.get('trans_date','')
        if raw:
            try:day=date.fromisoformat(raw)
            except ValueError:raise ValueError('Choose a valid transaction date.')
            q=q.filter(Journal.day==day)
        if request.args.get('created_by'):q=q.filter(Journal.actor.ilike('%'+request.args['created_by']+'%'))
        for field in ('created_at','updated_at'):
            if request.args.get(field):
                try:day=date.fromisoformat(request.args[field])
                except ValueError:raise ValueError('Choose a valid audit date.')
                try:until=day+timedelta(days=1)
                except OverflowError:raise ValueError('Audit filter date is outside the supported range.')
                column=Journal.created if field=='created_at' else func.coalesce(Change.created,Journal.created)
                lower=datetime.combine(day,time(),tzinfo=ZoneInfo('Asia/Karachi')).astimezone(timezone.utc).replace(tzinfo=None)
                upper=datetime.combine(until,time(),tzinfo=ZoneInfo('Asia/Karachi')).astimezone(timezone.utc).replace(tzinfo=None)
                q=q.filter(column>=lower,column<upper)
        if request.args.get('updated_by'):q=q.filter(func.coalesce(Change.actor,Journal.actor).ilike('%'+request.args['updated_by']+'%'))
        return start,end,scope,q
    def paging(q):
        try:page=int(request.args.get('page','1'));size=int(request.args.get('size','100'))
        except ValueError:raise ValueError('Choose valid pagination.')
        if page<1 or size not in (25,50,100):raise ValueError('Choose 25, 50 or 100 rows.')
        total=q.count();pages=max(1,(total+size-1)//size);page=min(page,pages)
        return page,size,total,pages
    def link(endpoint,**changes):
        args=request.args.to_dict(flat=False)
        for k,v in changes.items():args[k]=v
        return url_for(endpoint,**args)
    @bp.get('/journals')
    def journals():
        start,end,scope,q=range_query();q=q.outerjoin(Change,Change.journal_id==Journal.id).filter(Journal.kind!='reversal')
        state=request.args.get('state','active')
        if state=='active':q=q.filter(Change.id==None)
        elif state=='voided':q=q.filter(Change.id!=None,Change.replacement_id==None)
        elif state=='corrected':q=q.filter(Change.replacement_id!=None)
        elif state!='all':raise ValueError('Choose a valid transaction status.')
        sums=db.session.query(Line.journal_id,func.sum(Line.debit).label('amount')).group_by(Line.journal_id).subquery();q=q.join(sums,sums.c.journal_id==Journal.id)
        if request.args.get('amount'):q=q.filter(sums.c.amount==H['amount'](request.args['amount']))
        page,size,total,pages=paging(q)
        query=q.add_columns(sums.c.amount).order_by(Journal.day.desc(),Journal.id.desc())
        if request.args.get('print')!='1':query=query.offset((page-1)*size).limit(size)
        fetched=query.all()
        ids=[row.id for row,_ in fetched];changes={r.journal_id:r for r in Change.query.filter(Change.journal_id.in_(ids)).all()} if ids else {};details={}
        if ids:
            for line in Line.query.filter(Line.journal_id.in_(ids)).order_by(Line.id).all():details.setdefault(line.journal_id,[]).append(line)
        return render('journal_inquiry.html',title='Journal Inquiry',rows=fetched,details=details,changes=changes,start=start,end=end,scope=scope,state=state,page=page,size=size,total=total,pages_count=pages,action_token=secrets.token_urlsafe(32),link=lambda **kw:link('finance_reports.journals',**kw))
    @bp.get('/voided')
    @bp.get('/general')
    def general():
        start,end,scope,q=range_query();q=q.outerjoin(Change,Change.journal_id==Journal.id).join(Line,Line.journal_id==Journal.id)
        voided=request.path.endswith('/voided')
        if voided:q=q.filter(Change.id!=None,Change.replacement_id==None)
        for field in ('code','account_name','memo'):
            value=request.args.get(field,'')
            if value:
                column=Line.memo if field=='memo' else Line.snapshot['code' if field=='code' else 'name'].as_string()
                q=q.filter(db.cast(column,db.String).ilike('%'+value+'%'))
        if request.args.get('side'):
            if request.args['side'] not in ('dr','cr'):raise ValueError('Choose Dr or Cr.')
            q=q.filter(Line.debit>0 if request.args['side']=='dr' else Line.credit>0)
        if request.args.get('amount'):q=q.filter(Line.debit+Line.credit==H['amount'](request.args['amount']))
        if request.args.get('payment_id'):q=q.filter(False) # No source-payment bridge is configured.
        line_number=func.row_number().over(partition_by=Line.journal_id,order_by=Line.id)
        numbered=db.session.query(Line.id.label('id'),line_number.label('number')).subquery()
        q=q.join(numbered,numbered.c.id==Line.id)
        if request.args.get('line_item'):
            raw=request.args['line_item']
            if not re.fullmatch(r'[0-9]{1,3}',raw):raise ValueError('Choose a valid line item number.')
            q=q.filter(numbered.c.number==int(raw))
        # Select one row per line; journal header amounts must never be duplicated.
        page,size,total,pages=paging(q)
        query=q.with_entities(Line,Journal,numbered.c.number).order_by(Journal.day.desc(),Journal.id.desc(),Line.id)
        if request.args.get('print')!='1':query=query.offset((page-1)*size).limit(size)
        rows=query.all();ids=[j.id for _,j,_ in rows]
        changes={r.journal_id:r for r in Change.query.filter(Change.journal_id.in_(ids)).all()} if ids else {}
        return render('general_ledger.html',title='Voided Transactions' if voided else 'General Ledger',voided=voided,rows=rows,changes=changes,start=start,end=end,scope=scope,page=page,size=size,total=total,pages_count=pages,link=lambda **kw:(link('finance_reports.general',**kw).replace('/general','/voided') if voided else link('finance_reports.general',**kw)))
    @bp.get('/daily')
    def daily():
        start,end,scope,users=H['filters']();tab=request.args.get('tab','combine')
        if tab not in ('combine','balance','income','expense'):raise ValueError('Choose a valid daily report tab.')
        generated=request.args.get('generate')=='1' or request.args.get('print')=='1'
        opening={};closing={};snapshots={};income=[];expense=[];received={};unallocated=0
        if generated:
            before=H['scoped'](scope,users).filter(Journal.day<start)
            within=H['scoped'](scope,users).filter(Journal.day>=start,Journal.day<=end)
            past=before.order_by(Journal.day,Journal.id,Line.id).all();current=within.options(joinedload(Line.journal)).order_by(Journal.day,Journal.id,Line.id).all()
            for line in past:
                if line.snapshot['account_class']=='Assets':opening[line.account_id]=opening.get(line.account_id,0)+line.debit-line.credit;snapshots[line.account_id]=line.snapshot
            closing=dict(opening);by_journal={}
            for line in current:
                cls=line.snapshot['account_class']
                if cls=='Assets':closing[line.account_id]=closing.get(line.account_id,0)+line.debit-line.credit;snapshots[line.account_id]=line.snapshot
                if cls=='Income':income.append(line)
                if cls=='Expense':expense.append(line)
                by_journal.setdefault(line.journal_id,[]).append(line)
            for lines in by_journal.values():
                revenue=sum(l.credit-l.debit for l in lines if l.snapshot['account_class']=='Income')
                if not revenue:continue
                # Allocate only an unambiguous one-asset receipt; mixed journals
                # are reported as unallocated rather than inventing attribution.
                assets=[l for l in lines if l.snapshot['account_class']=='Assets']
                if len({l.account_id for l in assets})==1 and sum(l.debit-l.credit for l in assets)==revenue:
                    aid=assets[0].account_id;received[aid]=received.get(aid,0)+revenue;snapshots[aid]=assets[0].snapshot
                else:unallocated+=revenue
        total_income=sum(l.credit-l.debit for l in income);total_expense=sum(l.debit-l.credit for l in expense)
        balances=[dict(snapshot=snapshots[aid],opening=opening.get(aid,0),closing=closing.get(aid,0)) for aid in sorted(opening.keys()|closing.keys(),key=lambda a:snapshots[a]['code'])]
        return render('daily_profit.html',title='Day Wise P & L Statement',start=start,end=end,scope=scope,tab=tab,generated=generated,balances=balances,income=income,expense=expense,received=received,snapshots=snapshots,unallocated=unallocated,total_income=total_income,total_expense=total_expense,opening_total=sum(opening.values()),closing_total=sum(closing.values()),link=lambda **kw:link('finance_reports.daily',**kw))
    app.register_blueprint(bp)
