"""Generation-time fee cohorts and transactionally retained challan change history.

No historical class/campus or per-head receipt allocation is guessed for old data.
Mapper hooks use the tenant transaction connection; a rollback removes its audit too.
"""
import csv,io,json
from collections import defaultdict
from datetime import date,datetime,timedelta,timezone
from zoneinfo import ZoneInfo
from flask import Blueprint,abort,g,has_request_context,render_template,request,session,url_for
from sqlalchemy import event,select
from finance_ledger import TABS

KINDS=('Amount increased','Amount decreased','Payment voided','Discount voided','Generated challan deleted')

def configure_finance_audit(app,db,Student):
    bp=Blueprint('finance_audit',__name__,url_prefix='/workspace/finance/audit')
    ops=app.extensions['ops_models'];Bill=ops['bill'];Receipt=ops['receipt'];Workflow=ops['workflow'];Detail=app.extensions['record_models']['student']
    class Cohort(db.Model):
        __tablename__='finance_bill_cohort'
        id=db.Column(db.Integer,primary_key=True)
        bill_id=db.Column(db.Integer,nullable=False,index=True)
        active=db.Column(db.Boolean,nullable=False,default=True)
        at_generation=db.Column(db.Boolean,nullable=False)
        created=db.Column(db.DateTime,nullable=False)
        data=db.Column(db.JSON,nullable=False)
    class FeeEvent(db.Model):
        __tablename__='finance_fee_event'
        id=db.Column(db.Integer,primary_key=True)
        bill_id=db.Column(db.Integer,nullable=False,index=True)
        kind=db.Column(db.String(50),nullable=False,index=True)
        actor=db.Column(db.String(254),nullable=False)
        created=db.Column(db.DateTime,nullable=False,index=True)
        data=db.Column(db.JSON,nullable=False)
    app.extensions['finance_audit_models']=dict(cohort=Cohort,event=FeeEvent)
    def actor():
        if not has_request_context():return 'System'
        p=getattr(g,'staff_principal',None)
        return p.username if p else (getattr(g,'school_identity',None) or {}).get('email') or ('Demo visitor' if session.get('demo') else 'School owner')
    def stamp():return datetime.now(timezone.utc)
    def cohort_data(conn,bill):
        student=conn.execute(select(Student.__table__).where(Student.id==bill.student_id)).mappings().first()
        detail=conn.execute(select(Detail.data).where(Detail.student_id==bill.student_id)).scalar() or {}
        return dict(sid=bill.student_id,student=student['name'] if student else '',father=student['father'] if student else '',admission_no=student['admission_no'] if student else '',class_name=student['class_name'] if student else '',campus=detail.get('campus',''),section=detail.get('section',''),academic_session=detail.get('academic_session',''),roll_no=detail.get('roll_no',''))
    def snapshot(conn,bill,generation=False):
        row=conn.execute(select(Cohort.__table__).where(Cohort.bill_id==bill.id,Cohort.active==True)).mappings().first()
        if row:return dict(row)
        data=cohort_data(conn,bill);now=stamp()
        result=conn.execute(Cohort.__table__.insert().values(bill_id=bill.id,active=True,at_generation=generation,created=now,data=data))
        return dict(id=result.inserted_primary_key[0],bill_id=bill.id,active=True,at_generation=generation,created=now,data=data)
    def bill_data(bill):
        return dict(bill_id=bill.id,sid=bill.student_id,month=bill.month,due=bill.due.isoformat(),amount=sum(x['amount'] for x in bill.lines),paid=bill.paid or 0,discount=bill.discount or 0,lines=bill.lines,status=bill.state)
    def add_event(conn,bill,kind,extra=None):
        cohort=snapshot(conn,bill);data=bill_data(bill);data.update(cohort=cohort['data'],at_generation=cohort['at_generation']);data.update(extra or {})
        conn.execute(FeeEvent.__table__.insert().values(bill_id=bill.id,kind=kind,actor=actor(),created=stamp(),data=data))
    @event.listens_for(Bill,'after_insert')
    def generated(mapper,conn,bill):snapshot(conn,bill,True)
    @event.listens_for(Bill,'before_update')
    def changed(mapper,conn,bill):
        old=conn.execute(select(Bill.__table__).where(Bill.id==bill.id)).mappings().one()
        before=sum(x['amount'] for x in old['lines']);after=bill.total
        if before!=after:add_event(conn,bill,'Amount increased' if after>before else 'Amount decreased',dict(before_amount=before,delta=after-before,before_lines=old['lines']))
    @event.listens_for(Bill,'before_delete')
    def deleted(mapper,conn,bill):
        add_event(conn,bill,'Generated challan deleted')
        conn.execute(Cohort.__table__.update().where(Cohort.bill_id==bill.id,Cohort.active==True).values(active=False))
    @event.listens_for(Receipt,'before_update')
    def receipt_changed(mapper,conn,receipt):
        old=conn.execute(select(Receipt.__table__).where(Receipt.id==receipt.id)).mappings().one()
        if receipt.voided and not old['voided']:
            # Bill rows may flush before or after this mapper; capture receipt
            # amounts separately rather than claiming a flush-order balance.
            bill=db.session.get(Bill,receipt.bill_id)
            if bill:
                if receipt.amount:add_event(conn,bill,'Payment voided',dict(receipt_id=receipt.id,receipt_day=receipt.day.isoformat(),receipt_amount=receipt.amount,notes=receipt.notes))
                if receipt.discount:add_event(conn,bill,'Discount voided',dict(receipt_id=receipt.id,receipt_day=receipt.day.isoformat(),receipt_amount=receipt.discount,notes=receipt.notes))
    def csv_text(value):
        value=str(value)
        return "'"+value if value.lstrip().startswith(('=','+','-','@','\t','\r')) else value
    def local(value):return value.replace(tzinfo=timezone.utc).astimezone(ZoneInfo('Asia/Karachi')).strftime('%Y-%m-%d %H:%M:%S')
    def bounds():
        today=app.extensions['ledger_helpers']['today']()
        try:a=date.fromisoformat(request.args.get('from',today.replace(day=1).isoformat()));b=date.fromisoformat(request.args.get('to',today.isoformat()))
        except ValueError:raise ValueError('Choose valid From and To dates.')
        if b<a:raise ValueError('To must be on or after From.')
        return a,b
    def link(**changes):
        args=request.args.to_dict();args.update(changes);return url_for(request.endpoint,**args)
    def page(rows):
        try:p=int(request.args.get('page','1'))
        except ValueError:raise ValueError('Choose a valid page.')
        if p<1:raise ValueError('Choose a positive page.')
        count=len(rows);pages=max(1,(count+99)//100);p=min(p,pages)
        return (rows if request.args.get('print')=='1' or request.args.get('export') else rows[(p-1)*100:p*100]),p,pages,count
    @bp.errorhandler(ValueError)
    def invalid(error):return render_template('operation_error.html',title='Check Finance report',error=str(error)),422
    def cohort_match(c,ignore_class=False):
        for key in ('campus','class_name','section','academic_session'):
            if ignore_class and key!='campus':continue
            value=request.args.get(key,'')
            if value and (not c or not c.at_generation or c.data.get(key)!=value):return False
        return True
    @bp.get('/fees')
    def fees():
        start,end=bounds();tab=request.args.get('tab','summary')
        if tab not in ('summary','students'):raise ValueError('Choose Summary or Student ledger.')
        if request.args.get('basis','month')!='month':raise ValueError('Choose Fee month as the date basis.')
        bills=Bill.query.filter(Bill.month>=start.strftime('%Y-%m'),Bill.month<=end.strftime('%Y-%m')).order_by(Bill.month,Bill.id).all()
        cohorts={c.bill_id:c for c in Cohort.query.filter_by(active=True).all()};students={s.id:s for s in Student.query.all()}
        details={d.student_id:d.data for d in Detail.query.all()};receipts=defaultdict(list)
        for r in Receipt.query.filter_by(voided=False).all():receipts[r.bill_id].append(r)
        pending=defaultdict(int)
        for w in Workflow.query.filter_by(kind='staff-payment-approval',status='Pending').all():
            form=w.data.get('form',{})
            for b in w.data.get('bills',[]):
                from operations import money
                pending[b['id']]+=money(form.get('amount_'+str(b['id']),'0'))
        def row(b):
            c=cohorts.get(b.id);s=students.get(b.student_id);frozen=c.data if c and c.at_generation else {}
            return dict(bill=b,cohort=frozen,verified=bool(frozen),student=s,detail=details.get(b.student_id,{}),cleared=sum(r.amount for r in receipts[b.id]),pending=pending[b.id],fine=sum(x['amount'] for x in b.lines if x.get('kind') in ('late_fee','late_fee_forward','attendance_fine') or x.get('fine') or 'fine' in str(x.get('particular','')).lower()),moved=bool(s and frozen and (s.class_name!=frozen.get('class_name') or details.get(s.id,{}).get('campus','')!=frozen.get('campus'))))
        state=request.args.get('state','');status=request.args.get('status','')
        if state not in ('','Unpaid','Partially Paid','Fully Paid'):raise ValueError('Choose a valid payment state.')
        selected=[row(b) for b in bills if cohort_match(cohorts.get(b.id)) and (not state or b.state==state) and (not status or students.get(b.student_id) and students[b.student_id].status==status) and (request.args.get('installments','1')=='1' or not (b.source or '').startswith('installment:'))]
        totals=dict(payable=sum(r['bill'].total for r in selected),paid=sum(r['bill'].paid for r in selected),cleared=sum(r['cleared'] for r in selected),pending=sum(r['pending'] for r in selected),discount=sum(r['bill'].discount for r in selected),remaining=sum(r['bill'].remaining for r in selected),count=len(selected),receipt_count=sum(len(receipts[r['bill'].id]) for r in selected))
        totals['collected']=totals['cleared']+totals['pending'];totals['recovery']=round(100*totals['collected']/totals['payable'],1) if totals['payable'] else 0
        groups={};heads={};unallocated_paid=0;unallocated_discount=0
        for r in selected:
            b=r['bill'];group=groups.setdefault(b.month,dict(students=set(),count=0,payable=0,fine=0,discount=0,cleared=0,pending=0,paid=0,remaining=0));group['students'].add(b.student_id);group['count']+=1
            for key,value in dict(payable=b.total,fine=r['fine'],discount=b.discount,cleared=r['cleared'],pending=r['pending'],paid=r['cleared']+r['pending'],remaining=b.remaining).items():group[key]+=value
            named={str(x.get('display_name') or x.get('particular') or 'Unnamed fee head') for x in b.lines}
            for line in b.lines:
                name=str(line.get('display_name') or line.get('particular') or 'Unnamed fee head');h=heads.setdefault(name,dict(billed=0,paid=0,discount=0,unallocated=False));h['billed']+=line['amount']
            if len(named)==1:
                h=heads[next(iter(named))];h['paid']+=b.paid;h['discount']+=b.discount
            else:
                unallocated_paid+=b.paid;unallocated_discount+=b.discount
                for name in named:heads[name]['unallocated']=True
        options={key:sorted({c.data.get(key,'') for c in cohorts.values() if c.at_generation and c.data.get(key)}) for key in ('campus','class_name','section','academic_session')}
        search=request.args.get('search','').strip().casefold();listed=selected
        if search:listed=[r for r in listed if search in ' '.join(str(v) for v in (r['bill'].student_id,r['student'].name if r['student'] else r['cohort'].get('student',''),r['student'].admission_no if r['student'] else '',r['detail'].get('roll_no',''))).casefold()]
        drill=None;drill_receipts=[]
        if request.args.get('sid'):
            try:sid=int(request.args['sid'])
            except ValueError:raise ValueError('Choose a valid SID.')
            if sid not in {r['bill'].student_id for r in selected}:abort(404)
            drill=[row(b) for b in bills if b.student_id==sid and cohort_match(cohorts.get(b.id),True)]
            ids={r['bill'].id for r in drill};drill_receipts=Receipt.query.filter(Receipt.bill_id.in_(ids)).order_by(Receipt.day,Receipt.id).all()
        if request.args.get('export'):
            if request.args['export']!='csv':raise ValueError('Choose CSV export.')
            out=io.StringIO();writer=csv.writer(out)
            if tab=='summary':
                writer.writerow(['Month','Students','Challans','Payable','Fine','Discount','Paid cleared','Awaiting approval','Paid total','Remaining posted'])
                for month,r in groups.items():writer.writerow([month,len(r['students']),r['count']]+[f'{r[k]/100:.2f}' for k in ('payable','fine','discount','cleared','pending','paid','remaining')])
            else:
                writer.writerow(['SID','Challan','Fee month','Student','Class as billed','Campus as billed','Payable','Cleared','Awaiting approval','Discount','Remaining'])
                for r in listed:
                    b=r['bill'];writer.writerow([b.student_id,b.id,b.month]+[csv_text(v) for v in (r['student'].name if r['student'] else r['cohort'].get('student',''),r['cohort'].get('class_name','Historical cohort unavailable'),r['cohort'].get('campus','Historical cohort unavailable'))]+[f'{v/100:.2f}' for v in (b.total,r['cleared'],r['pending'],b.discount,b.remaining)])
            return app.response_class('\ufeff'+out.getvalue(),mimetype='text/csv',headers={'Content-Disposition':'attachment; filename=fee-audit.csv'})
        listed,p,pages,count=page(listed)
        return render_template('fee_audit.html',title='Fee Audit Report',start=start,end=end,tab=tab,rows=listed,totals=totals,groups=groups,heads=heads,unallocated_paid=unallocated_paid,unallocated_discount=unallocated_discount,options=options,statuses=sorted({s.status for s in students.values()}),unknown=sum(not r['verified'] for r in selected),page=p,pages=pages,count=count,link=link,drill=drill,drill_receipts=drill_receipts)
    @bp.get('/challans/voided')
    def challans():
        start,end=bounds();zone=ZoneInfo('Asia/Karachi')
        if end==date.max:raise ValueError('Choose an end date before year 9999 ends.')
        q=FeeEvent.query.filter(FeeEvent.created>=datetime.combine(start,datetime.min.time(),tzinfo=zone).astimezone(timezone.utc).replace(tzinfo=None),FeeEvent.created<datetime.combine(end+timedelta(days=1),datetime.min.time(),tzinfo=zone).astimezone(timezone.utc).replace(tzinfo=None))
        kind=request.args.get('kind','')
        if kind and kind not in KINDS:raise ValueError('Choose a valid event type.')
        if kind:q=q.filter_by(kind=kind)
        rows=q.order_by(FeeEvent.created.desc(),FeeEvent.id.desc()).all()
        for key in ('campus','class_name','section','academic_session'):
            if request.args.get(key):rows=[r for r in rows if r.data['cohort'].get(key)==request.args[key]]
        if request.args.get('sid'):
            if not request.args['sid'].isdigit() or len(request.args['sid'])>18:raise ValueError('Enter an exact SID.')
            rows=[r for r in rows if r.data['sid']==int(request.args['sid'])]
        if request.args.get('student'):rows=[r for r in rows if request.args['student'].casefold() in r.data['cohort'].get('student','').casefold()]
        all_cohorts=Cohort.query.all();options={key:sorted({c.data.get(key,'') for c in all_cohorts if c.data.get(key)}) for key in ('campus','class_name','section','academic_session')}
        rows,p,pages,count=page(rows)
        return render_template('voided_challans.html',title='Voided Challan Transactions',start=start,end=end,rows=rows,kinds=KINDS,options=options,page=p,pages=pages,count=count,link=link,local=local)
    app.register_blueprint(bp)
