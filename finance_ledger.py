"""Balanced, append-only manual journals and reports over posted journal lines."""
import hashlib,hmac,json,re,secrets
from datetime import date,datetime,timezone
from decimal import Decimal,InvalidOperation
from zoneinfo import ZoneInfo
from flask import Blueprint,abort,flash,g,redirect,render_template,request,session,url_for
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from finance_setup import CLASSES

TABS=[('ledger','Ledger'),('journal','Journal Entry'),('expense','Add Expense'),('income','Add Other Income'),('inquiry','GL Inquiry'),('trial','Trial Balance'),('profit','P & L Statement'),('balance','Balance Sheet')]

def configure_ledger(app,db):
    bp=Blueprint('ledger',__name__,url_prefix='/workspace/finance/ledger')
    masters=app.extensions['finance_models'];Account=masters['account'];Group=masters['group'];Period=masters['period'];Settings=app.extensions['record_models']['settings'];Audit=app.extensions['ops_models']['audit']
    class Journal(db.Model):
        __tablename__='finance_journal'
        id=db.Column(db.Integer,primary_key=True)
        token=db.Column(db.String(64),unique=True,nullable=False)
        fingerprint=db.Column(db.String(64),nullable=False)
        day=db.Column(db.Date,nullable=False,index=True)
        campus=db.Column(db.String(160),nullable=False,index=True)
        kind=db.Column(db.String(20),nullable=False)
        period_id=db.Column(db.Integer,db.ForeignKey('finance_period.id',ondelete='RESTRICT'),nullable=False)
        actor=db.Column(db.String(254),nullable=False)
        actor_key=db.Column(db.String(80),nullable=False)
        created=db.Column(db.DateTime,nullable=False,default=lambda:datetime.now(timezone.utc))
    class Line(db.Model):
        __tablename__='finance_journal_line'
        id=db.Column(db.Integer,primary_key=True)
        journal_id=db.Column(db.Integer,db.ForeignKey('finance_journal.id',ondelete='RESTRICT'),nullable=False,index=True)
        account_id=db.Column(db.Integer,db.ForeignKey('finance_account.id',ondelete='RESTRICT'),nullable=False,index=True)
        debit=db.Column(db.BigInteger,nullable=False,default=0)
        credit=db.Column(db.BigInteger,nullable=False,default=0)
        memo=db.Column(db.String(1000),nullable=False,default='')
        snapshot=db.Column(db.JSON,nullable=False)
        journal=db.relationship(Journal)
        __table_args__=(db.CheckConstraint('(debit > 0 AND credit = 0) OR (credit > 0 AND debit = 0)',name='finance_one_positive_side'),)
    app.extensions['ledger_models']=dict(journal=Journal,line=Line)
    app.extensions['ledger_helpers']=dict(used_period=lambda rid:Journal.query.filter_by(period_id=rid).first() is not None,used_account=lambda rid:Line.query.filter_by(account_id=rid).first() is not None)
    def actor():
        p=getattr(g,'staff_principal',None)
        if p:return p.username,'staff:'+str(p.id)
        identity=getattr(g,'school_identity',None) or {}
        return identity.get('email') or 'Demo visitor',('owner:'+str(session['owner_id']) if session.get('owner_id') else 'demo')
    def campuses():return sorted({r.value for r in Settings.query.filter_by(category='campus').all()})
    def today():return datetime.now(ZoneInfo('Asia/Karachi')).date()
    def amount(raw):
        try:n=Decimal(str(raw or '0'))
        except InvalidOperation:raise ValueError('Enter a valid amount.')
        if not n.is_finite() or not 0<=n<=999999999 or n*100!=(n*100).to_integral_value():raise ValueError('Amounts must be non-negative with at most two decimal places, up to 999,999,999.')
        return int(n*100)
    def identity(raw):
        if not re.fullmatch(r'[0-9]{1,18}',str(raw)):raise ValueError('Choose a valid account.')
        return int(raw)
    def selected(raw,expected=None):
        account=db.session.get(Account,identity(raw))
        if not account or account.inactive or not account.group.active:raise ValueError('Choose an active account and group.')
        if expected and account.group.account_class!=expected:raise ValueError('Choose an '+expected+' account for this row.')
        return account
    def account_snapshot(a):return dict(code=a.code,name=a.name,group_id=a.group_id,group=a.group.name,account_class=a.group.account_class)
    def options():return Account.query.join(Group).filter(Account.inactive==False,Group.active==True).order_by(Group.account_class,Group.name,Account.code).all()
    def render(template,**kwargs):return render_template(template,tabs=TABS,classes=CLASSES,campuses=campuses(),**kwargs)
    @bp.before_request
    def protect():
        if request.method=='POST':
            if not request.form.get('_csrf') or not hmac.compare_digest(request.form['_csrf'],session.get('record_csrf','')):abort(400,'Reload this Finance form.')
            app.extensions['admission_capacity']['lock']()
            principal=getattr(g,'staff_principal',None)
            if principal is not None and request.form.get('save_action')=='print':
                access=app.extensions['staff_access_helpers']
                if access['grant'](principal,'finance.print')!=set(access['campuses']()):abort(403,'Save & Print requires Finance print permission for every campus.')
    @bp.errorhandler(ValueError)
    def invalid(error):
        db.session.rollback();return render_template('operation_error.html',title='Check journal entry',error=str(error)),422
    @bp.errorhandler(IntegrityError)
    def conflict(error):
        db.session.rollback();return render_template('operation_error.html',title='Check journal entry',error='Another request changed this posting. Reload the saved journals before retrying.'),422

    def prepare(kind,form):
        try:day=date.fromisoformat(form.get('day',''))
        except ValueError:raise ValueError('Choose a valid transaction date.')
        campus=form.get('campus','')
        if campus not in campuses():raise ValueError('Choose a configured campus.')
        campus_row=db.session.get(app.extensions['institute_setup_models']['campus'],campus)
        if campus_row and not campus_row.active:raise ValueError('Choose an active campus.')
        periods=Period.query.filter(Period.begin<=day,Period.end>=day).all()
        if len(periods)!=1 or periods[0].closed:raise ValueError('The transaction needs exactly one open Accounting Period covering its date.')
        ids=form.getlist('account_id');memos=form.getlist('memo')
        if not 1<=len(ids)<=100 or len(memos)!=len(ids):raise ValueError('Enter between 1 and 100 complete rows.')
        lines=[]
        if kind=='journal':
            dr=form.getlist('debit');cr=form.getlist('credit')
            if len(dr)!=len(ids) or len(cr)!=len(ids):raise ValueError('Debit and credit rows are incomplete.')
            for raw,d,c,memo in zip(ids,dr,cr,memos):
                if not raw and not d.strip() and not c.strip() and not memo.strip():continue
                a=selected(raw);debit=amount(d);credit=amount(c)
                if (debit>0)==(credit>0):raise ValueError('Each journal row must have either a positive debit or a positive credit.')
                lines.append((a,debit,credit,memo.strip()))
        else:
            amounts=form.getlist('amount')
            if len(amounts)!=len(ids):raise ValueError('Amount rows are incomplete.')
            counter=selected(form.get('counter_account',''),'Assets')
            for raw,value,memo in zip(ids,amounts,memos):
                if not raw and not value.strip() and not memo.strip():continue
                a=selected(raw,'Expense' if kind=='expense' else 'Income');n=amount(value)
                if not n:raise ValueError('Enter a positive amount for every populated row.')
                lines.append((a,n if kind=='expense' else 0,n if kind=='income' else 0,memo.strip()))
            total=sum(d+c for _,d,c,_ in lines)
            if total:lines.append((counter,total if kind=='income' else 0,total if kind=='expense' else 0,'Expense payment' if kind=='expense' else 'Income receipt'))
        if len(lines)<2 or len({a.id for a,_,_,_ in lines})<2:raise ValueError('Use at least two distinct accounts in a balanced journal.')
        if any(len(memo)>1000 for _,_,_,memo in lines):raise ValueError('Each memo must be at most 1,000 characters.')
        if sum(d for _,d,_,_ in lines)!=sum(c for _,_,c,_ in lines):raise ValueError('Total debit must equal total credit.')
        return day,campus,periods[0],lines

    @bp.route('/entry/<kind>',methods=['GET','POST'])
    def entry(kind):
        if kind not in ('journal','expense','income'):abort(404)
        title=dict(journal='Journal Entry',expense='Add Expense',income='Add Other Income')[kind]
        if request.method=='GET':return render('ledger_entry.html',title=title,kind=kind,accounts=options(),today=today().isoformat(),post_token=secrets.token_urlsafe(32))
        token=request.form.get('post_token','')
        if not re.fullmatch(r'[A-Za-z0-9_-]{32,64}',token):raise ValueError('Reload the entry form before saving.')
        who,who_key=actor()
        # Include actor and original row text in the retry fingerprint. A replay
        # can be returned even after its account/period is later retired/closed.
        payload={key:request.form.getlist(key) for key in ('day','campus','account_id','debit','credit','amount','memo','counter_account')}
        digest=hashlib.sha256(json.dumps([kind,who_key,payload],sort_keys=True,separators=(',',':')).encode()).hexdigest()
        prior=Journal.query.filter_by(token=token).first()
        if prior:
            if prior.fingerprint!=digest:raise ValueError('This submission token was already used for a different entry. Reload the form.')
            return redirect(url_for('ledger.voucher',jid=prior.id,**({'print':'1'} if request.form.get('save_action')=='print' else {})))
        day,campus,period,lines=prepare(kind,request.form)
        journal=Journal(token=token,fingerprint=digest,day=day,campus=campus,kind=kind,period_id=period.id,actor=who,actor_key=who_key);db.session.add(journal);db.session.flush()
        for a,d,c,m in lines:db.session.add(Line(journal_id=journal.id,account_id=a.id,debit=d,credit=c,memo=m,snapshot=account_snapshot(a)))
        db.session.add(Audit(action='Post Finance journal',data={'journal_id':journal.id,'kind':kind,'campus':campus,'day':day.isoformat(),'actor':who,'total':sum(d for _,d,_,_ in lines)}));db.session.commit()
        flash('Balanced journal saved. Posted entries retain their account names and amounts.','success')
        return redirect(url_for('ledger.voucher',jid=journal.id,**({'print':'1'} if request.form.get('save_action')=='print' else {})))

    @bp.get('/voucher/<int:jid>')
    def voucher(jid):
        if not 0<jid<10**18:abort(404)
        journal=db.get_or_404(Journal,jid);lines=Line.query.filter_by(journal_id=jid).order_by(Line.id).all()
        changes=app.extensions.get('journal_change_models',{});Change=changes.get('change')
        change=Change.query.filter_by(journal_id=jid).first() if Change else None
        return render('ledger_voucher.html',title='Journal Voucher',journal=journal,lines=lines,total=sum(x.debit for x in lines),change=change)

    def filters():
        try:start=date.fromisoformat(request.args.get('from',today().replace(day=1).isoformat()));end=date.fromisoformat(request.args.get('to',today().isoformat()))
        except ValueError:raise ValueError('Choose valid From and To dates.')
        if end<start:raise ValueError('To date must be on or after From date.')
        scope=list(dict.fromkeys(request.args.getlist('campus')))
        if any(c not in campuses() for c in scope):raise ValueError('Choose configured campuses.')
        users=list(dict.fromkeys(request.args.getlist('user')))
        known={key for key, in db.session.query(Journal.actor_key).distinct().all()}
        if any(u not in known for u in users):raise ValueError('Choose a user shown in the report.')
        return start,end,scope,users
    def scoped(scope,users):
        q=Line.query.join(Journal)
        if scope:q=q.filter(Journal.campus.in_(scope))
        if users:q=q.filter(Journal.actor_key.in_(users))
        return q
    def group_rows(q):
        # Group on immutable classification/name snapshots, not the current
        # account directory. Historical reclassification cannot rewrite reports.
        raw=q.with_entities(Line.account_id,func.sum(Line.debit),func.sum(Line.credit),func.max(Line.id)).group_by(Line.account_id).all()
        latest={line.id:line.snapshot for line in Line.query.filter(Line.id.in_([r[3] for r in raw])).all()} if raw else {}
        return [(a,latest[last],d,c) for a,d,c,last in raw]
    @bp.get('')
    @bp.get('/report/<mode>')
    def report(mode='ledger'):
        if mode not in ('ledger','inquiry','trial','profit','balance'):abort(404)
        start,end,scope,users=filters();base=scoped(scope,users)
        rows=[];opening=0;ending=0;debit=0;credit=0;selected_account=None;totals={};report_rows=[];sections={};rollups={}
        if mode in ('ledger','inquiry'):
            raw=request.args.get('account_id','')
            q=base.filter(Journal.day>=start,Journal.day<=end)
            if raw:
                selected_account=db.session.get(Account,identity(raw))
                if selected_account is None:raise ValueError('Choose a configured account.')
                q=q.filter(Line.account_id==selected_account.id)
                opening=base.filter(Journal.day<start,Line.account_id==selected_account.id).with_entities(func.coalesce(func.sum(Line.debit-Line.credit),0)).scalar()
            elif mode=='inquiry':q=q.filter(False)
            raw_rows=q.order_by(Journal.day,Journal.id,Line.id).all();ending=opening
            for line in raw_rows:
                ending+=line.debit-line.credit;debit+=line.debit;credit+=line.credit;rows.append(dict(line=line,balance=ending))
        elif mode=='trial':
            before={};during={}
            for a,snap,d,c in group_rows(base.filter(Journal.day<start)):before[a]=(snap,int(d),int(c))
            for a,snap,d,c in group_rows(base.filter(Journal.day>=start,Journal.day<=end)):during[a]=(snap,int(d),int(c))
            for key in before.keys()|during.keys():
                snap=during.get(key,before.get(key))[0];_,bd,bc=before.get(key,(snap,0,0));_,d,c=during.get(key,(snap,0,0));net=bd-bc+d-c
                report_rows.append(dict(snapshot=snap,brought_debit=bd,brought_credit=bc,debit=d,credit=c,balance_debit=max(net,0),balance_credit=max(-net,0)))
            report_rows.sort(key=lambda r:(CLASSES.index(r['snapshot']['account_class']),r['snapshot']['group'],r['snapshot']['code']))
            totals={k:sum(r[k] for r in report_rows) for k in ('brought_debit','brought_credit','debit','credit','balance_debit','balance_credit')}
            for r in report_rows:
                for key in ((r['snapshot']['account_class'],r['snapshot']['group']),(r['snapshot']['account_class'],None)):
                    total=rollups.setdefault(key,{k:0 for k in totals})
                    for k in totals:total[k]+=r[k]
        else:
            q=base.filter(Journal.day<=end)
            if mode=='profit':q=q.filter(Journal.day>=start)
            income=expense=0
            for aid,snap,d,c in group_rows(q):
                cls=snap['account_class'];d=int(d);c=int(c)
                if cls=='Income':income+=c-d
                if cls=='Expense':expense+=d-c
                if (mode=='profit' and cls in ('Income','Expense')) or (mode=='balance' and cls in ('Assets','Liabilities','Equity')):
                    value=(d-c) if cls in ('Assets','Expense') else (c-d)
                    sections.setdefault(cls,[]).append(dict(snapshot=snap,amount=value))
            if mode=='profit':totals=dict(income=income,expense=expense,profit=income-expense)
            else:
                assets=sum(r['amount'] for r in sections.get('Assets',[]));liabilities=sum(r['amount'] for r in sections.get('Liabilities',[]));equity=sum(r['amount'] for r in sections.get('Equity',[]));profit=income-expense
                totals=dict(assets=assets,liabilities=liabilities,capital=equity,profit=profit,equity=equity+profit,difference=assets-liabilities-equity-profit)
        names=dict(TABS);query=request.args.get('q','').strip().casefold();tab=request.args.get('tab','Income' if mode=='profit' else 'Assets')
        if mode=='profit' and tab not in ('Income','Expense'):raise ValueError('Choose Income or Expense.')
        if mode=='balance' and tab not in ('Assets','Liabilities','Equity'):raise ValueError('Choose Assets, Liabilities or Equity.')
        for items in sections.values():items.sort(key=lambda r:(r['snapshot']['group'],r['snapshot']['code']))
        selected_rows=sections.get(tab,[])
        group_totals={}
        for item in selected_rows:group_totals[item['snapshot']['group']]=group_totals.get(item['snapshot']['group'],0)+item['amount']
        display=[r for r in selected_rows if not query or query in (r['snapshot']['group']+' '+r['snapshot']['name']).casefold()]
        try:page=int(request.args.get('page','1'));size=int(request.args.get('size','100'))
        except ValueError:raise ValueError('Choose valid report pagination.')
        if page<1 or size not in (25,50,100):raise ValueError('Choose 25, 50 or 100 rows.')
        count=len(display);pages=max(1,(count+size-1)//size);page=min(page,pages)
        if request.args.get('print')=='1':display=selected_rows
        else:display=display[(page-1)*size:page*size]
        def link(**changes):
            args=request.args.to_dict(flat=False)
            for k,v in changes.items():args[k]=v
            args.pop('mode',None)
            return url_for('ledger.report',mode=mode,**args)
        return render('ledger_report.html',title=names[mode],mode=mode,start=start,end=end,scope=scope,users=users,user_options=db.session.query(Journal.actor_key,Journal.actor).distinct().order_by(Journal.actor).all(),accounts=Account.query.order_by(Account.code).all(),selected_account=selected_account,rows=rows,opening=opening,ending=ending,debit=debit,credit=credit,report_rows=report_rows,totals=totals,rollups=rollups,sections=sections,tab=tab,display=display,group_totals=group_totals,count=count,page=page,pages_count=pages,size=size,link=link)
    app.extensions['ledger_helpers'].update(actor=actor,prepare=prepare,options=options,snapshot=account_snapshot,campuses=campuses,today=today,filters=filters,scoped=scoped,amount=amount,identity=identity)
    app.register_blueprint(bp)
