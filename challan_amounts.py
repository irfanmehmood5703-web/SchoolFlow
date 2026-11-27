"""Reviewed fee-head adjustments on saved challans; receipts and plans stay separate."""
import copy,csv,hashlib,io,json,re,secrets
from datetime import date,datetime,timezone
from decimal import Decimal,ROUND_HALF_UP
from zoneinfo import ZoneInfo
from flask import Blueprint,abort,flash,g,jsonify,render_template,request,session,url_for
from itsdangerous import BadData,SignatureExpired,URLSafeTimedSerializer
from sqlalchemy.exc import IntegrityError,OperationalError
from sqlalchemy.orm.exc import StaleDataError
from werkzeug.exceptions import HTTPException
from operations import money
from school_clock import school_today
from workspace_actor import actor,csrf,scopes,stamp

LIMIT=99999999900
PROTECTED={'late_fee','late_fee_forward','attendance_fine'}

def adjusted_lines(lines,head,direction,change_by,value,request_id):
    """Pure calculation, integer paisa and half-up percentage rounding."""
    result=copy.deepcopy(lines)
    if not isinstance(result,list) or any(not isinstance(x,dict) or not isinstance(x.get('amount'),int) or x['amount']<0 for x in result):
        raise ValueError('This challan has invalid saved charges. Review it before changing amounts.')
    indexes=[i for i,x in enumerate(result) if x.get('particular')==head['key']]
    if any(result[i].get('kind') in PROTECTED or result[i].get('fine_charge_id') or result[i].get('arrears_key') or result[i].get('billing_rule',{}).get('timing')=='fine' for i in indexes):
        raise ValueError('Linked fines and opening arrears must be changed through their original workflow.')
    before=sum(result[i]['amount'] for i in indexes)
    delta=value if change_by=='absolute' else int((Decimal(before)*Decimal(value)/10000).quantize(Decimal('1'),rounding=ROUND_HALF_UP))
    if not delta:raise ValueError('This head has no charge to change by that percentage. Use an absolute amount to add a new charge.')
    if direction=='decrease':delta=-delta
    if before+delta<0 or before+delta>LIMIT:raise ValueError('The selected fee head cannot become negative or exceed the supported amount.')
    def change(i,part):
        line=result[i];old=line['amount']
        line.setdefault('before_manual_changes',{k:copy.deepcopy(line[k]) for k in ('amount','actual','plan_discount') if k in line})
        # The challan's gross amount changes explicitly; the dated student plan
        # and original concession stay intact. Preserve the original basis too.
        if isinstance(line.get('actual'),int) and isinstance(line.get('plan_discount'),int) and line['actual']-line['plan_discount']==old:
            line['actual']+=part
        line['amount']=old+part
        line['manual_adjustment_paisa']=line.get('manual_adjustment_paisa',0)+part
        line['last_amount_change']=request_id
    if delta>0:
        if indexes:change(indexes[0],delta)
        else:result.append(dict(particular=head['key'],display_name=head['label'],amount=delta,kind='manual_amount',before_manual_changes={'amount':0},manual_adjustment_paisa=delta,last_amount_change=request_id))
    else:
        left=-delta
        for i in reversed(indexes):
            part=min(left,result[i]['amount'])
            if part:change(i,-part);left-=part
            if not left:break
    return result,before,before+delta,delta


def configure_challan_amounts(app,db,Student):
    bp=Blueprint('challan_amounts',__name__,url_prefix='/workspace/fees/add-amount')
    O=app.extensions['ops_models'];Bill=O['bill'];Receipt=O['receipt'];Audit=O['audit'];R=app.extensions['record_models'];Detail=R['student']
    Cohort=app.extensions['finance_audit_models']['cohort']
    class Change(db.Model):
        __tablename__='challan_amount_change'
        id=db.Column(db.String(32),primary_key=True)
        actor=db.Column(db.String(80),nullable=False)
        actor_label=db.Column(db.String(160),nullable=False)
        operation=db.Column(db.JSON,nullable=False)
        created=db.Column(db.DateTime,nullable=False,default=lambda:datetime.now(timezone.utc))
    class ChangeLine(db.Model):
        __tablename__='challan_amount_change_line'
        id=db.Column(db.Integer,primary_key=True)
        change_id=db.Column(db.String(32),db.ForeignKey('challan_amount_change.id'),nullable=False,index=True)
        # No FK to Bill: deletion audit must survive a later unpaid-bill delete.
        bill_id=db.Column(db.Integer,nullable=False,index=True)
        cohort_id=db.Column(db.Integer,nullable=False,index=True)
        student_id=db.Column(db.Integer,nullable=False)
        campus=db.Column(db.String(160),nullable=False)
        before=db.Column(db.JSON,nullable=False)
        after=db.Column(db.JSON,nullable=False)
    app.extensions['challan_amount_models']=dict(change=Change,line=ChangeLine)
    def binding():
        who=actor(app);return [who['key'],who['school_id'],(getattr(g,'school_identity',None) or {}).get('scope') or who['school_code']]
    def serializer():return URLSafeTimedSerializer(app.secret_key,salt='schoolflow-challan-amount-review-v1')
    def options(key):
        rows=R['settings'].query.filter_by(category=key).order_by(R['settings'].value).all()
        allowed=scopes(app,'fees.view') if key=='campus' else None
        return [r.value for r in rows if allowed is None or r.value in allowed]
    def heads():return {h['key']:h for h in app.extensions['fee_setup_helpers']['heads']() if h['timing']!='fine'}
    def selected():
        raw=request.form.getlist('ids')
        if not raw or len(raw)>100 or any(not re.fullmatch(r'[1-9][0-9]{0,11}',v) for v in raw):raise ValueError('Select 1–100 challans on this page.')
        ids=sorted({int(v) for v in raw})
        if len(ids)!=len(raw):raise ValueError('Select each challan only once.')
        return ids
    def parse():
        key=request.form.get('head','');direction=request.form.get('direction','');mode=request.form.get('change_by','')
        value=request.form.get('amount','').strip();note=request.form.get('note','').strip()
        if direction not in ('increase','decrease') or mode not in ('absolute','percentage'):raise ValueError('Choose Increase/Decrease and Absolute/Percentage.')
        if not re.fullmatch(r'\d{1,9}(?:\.\d{1,2})?',value):raise ValueError('Enter a positive amount with at most two decimal places.')
        n=money(value)
        if not n:raise ValueError('The change must be greater than zero.')
        if mode=='percentage' and (n>1000000 or (direction=='decrease' and n>10000)):raise ValueError('A decrease cannot exceed 100%; an increase cannot exceed 10,000%.')
        if len(note)>500:raise ValueError('Keep the reason within 500 characters.')
        return dict(head=key,direction=direction,change_by=mode,value=n,note=note)
    def describe(bills,permission):
        students={s.id:s for s in Student.query.filter(Student.id.in_({b.student_id for b in bills})).all()}
        data=app.extensions['record_helpers']['raw_many']('student',list(students.values()))
        allowed=scopes(app,permission);result={}
        for b in bills:
            s=students.get(b.student_id);d=data.get(b.student_id,{})
            if s is None or (allowed is not None and d.get('campus','') not in allowed):abort(404,'A selected challan is outside your access or no longer exists.')
            result[b.id]=dict(name=s.name,sid=s.id,father=s.father or '',campus=d.get('campus',''),class_name=s.class_name or '',section=d.get('section',''),roll_no=d.get('roll_no',''),family_no=d.get('family_no',''))
        return result
    def load(ids,lock=False):
        q=Bill.query.filter(Bill.id.in_(ids)).order_by(Bill.id)
        if lock:q=q.populate_existing().with_for_update(of=Bill)
        bills=q.all()
        if len(bills)!=len(ids):abort(404,'A selected challan is outside your access or no longer exists.')
        return bills,describe(bills,'fees.adjust')
    def snapshot(b):return dict(id=b.id,student_id=b.student_id,month=b.month,due=b.due.isoformat(),total=b.total,paid=b.paid,discount=b.discount,remaining=b.remaining,status=b.state,version=b.version,lines=copy.deepcopy(b.lines))
    def bill_stamp(b,who):
        cohort=Cohort.query.filter_by(bill_id=b.id,active=True).order_by(Cohort.id.desc()).first()
        raw=json.dumps(dict(source=b.source,cohort_id=cohort.id if cohort else None,financial=snapshot(b),student=who,frozen=b.frozen),sort_keys=True,separators=(',',':'))
        return hashlib.sha256(raw.encode()).hexdigest()
    def calculate(bills,people,operation,nonce):
        head=heads().get(operation['head'])
        if not head:raise ValueError('Choose a configured fee head. Fine-policy heads use their own workflow.')
        rows=[]
        for b in bills:
            if b.frozen:raise ValueError('Challan #'+str(b.id)+' is frozen. Unfreeze it before changing charges.')
            lines,old,new,delta=adjusted_lines(b.lines,head,operation['direction'],operation['change_by'],operation['value'],nonce)
            total=sum(x['amount'] for x in lines)
            if min(b.paid,b.discount,b.remaining)<0:raise ValueError('The saved paid/discount balance needs review before changing this challan.')
            if total>LIMIT:raise ValueError('The new challan total exceeds the supported amount.')
            if total<b.paid+b.discount:raise ValueError('The new total cannot be below the already received amount plus discount. No challans were changed.')
            rows.append(dict(bill=b,student=people[b.id],before=snapshot(b),lines=lines,head_before=old,head_after=new,delta=delta,total_after=total,remaining_after=total-b.paid-b.discount))
        return head,rows
    @bp.before_request
    def protect():
        if request.content_length and request.content_length>131072:abort(413,'This batch is too large.')
        csrf()
    @bp.errorhandler(ValueError)
    def invalid(exc):
        db.session.rollback()
        if request.method=='POST':return jsonify(error=str(exc)),422
        return render_template('operation_error.html',title='Check challan amount',error=str(exc)),422
    @bp.errorhandler(HTTPException)
    def http_error(exc):
        db.session.rollback()
        if request.method=='POST':return jsonify(error=exc.description),exc.code
        return render_template('operation_error.html',title='Check challan amount',error=exc.description),exc.code
    @bp.errorhandler(IntegrityError)
    @bp.errorhandler(StaleDataError)
    @bp.errorhandler(OperationalError)
    def concurrent(exc):
        db.session.rollback();return jsonify(error='Another operation changed this batch. Preview again; no partial adjustment was saved.'),409
    @bp.get('')
    def index():
        at=school_today().strftime('%Y-%m');start=request.args.get('from',at);end=request.args.get('to',at)
        if not re.fullmatch(r'\d{4}-(?:0[1-9]|1[0-2])',start) or not re.fullmatch(r'\d{4}-(?:0[1-9]|1[0-2])',end):raise ValueError('Choose valid From and To months.')
        try:date.fromisoformat(start+'-01');date.fromisoformat(end+'-01')
        except ValueError:raise ValueError('Choose valid calendar months.')
        distance=(int(end[:4])-int(start[:4]))*12+int(end[5:])-int(start[5:])
        if distance<0 or distance>11:raise ValueError('Choose a range of up to 12 months, with To on or after From.')
        Family=R['family']
        q=Bill.query.join(Student,Student.id==Bill.student_id).outerjoin(Detail,Detail.student_id==Student.id).outerjoin(Family,Family.id==Detail.family_id).filter(Bill.month>=start,Bill.month<=end)
        students=app.extensions['record_helpers']['filter_students'](include_search=False).with_entities(Student.id)
        q=q.filter(Bill.student_id.in_(students))
        search=request.args.get('q','').strip()[:160]
        if search:q=q.filter(db.or_(Student.name.contains(search,autoescape=True),Student.father.contains(search,autoescape=True),Student.admission_no.contains(search,autoescape=True),Family.number.contains(search,autoescape=True),Detail.data['roll_no'].as_string().contains(search,autoescape=True),db.or_(Bill.id==int(search),Student.id==int(search)) if search.isdigit() and len(search)<=12 else db.false()))
        order=request.args.get('sort','latest')
        if order not in ('latest','name','month'):raise ValueError('Choose a valid sort order.')
        q=q.order_by(Student.name,Bill.id) if order=='name' else q.order_by(Bill.month,Bill.id) if order=='month' else q.order_by(Bill.id.desc())
        bills=q.all();state=request.args.get('status','')
        if state not in ('','Unpaid','Partially Paid','Fully Paid'):raise ValueError('Choose a valid challan status.')
        if state:bills=[b for b in bills if b.state==state]
        people=describe(bills,'fees.export' if request.args.get('export') else 'fees.view')
        if request.args.get('export'):
            if request.args['export']!='csv':raise ValueError('Choose CSV export.')
            out=io.StringIO(newline='');w=csv.writer(out);w.writerow(['Challan','SID','Student','Campus','Class','Section','Month','Payable','Discount','Paid','Remaining','Status'])
            def safe(v):
                v=str(v);return "'"+v if v.lstrip().startswith(('=','+','-','@','\t','\r')) else v
            for b in bills:
                s=people[b.id];w.writerow([safe(v) for v in [b.id,s['sid'],s['name'],s['campus'],s['class_name'],s['section'],b.month,*[f'{n/100:.2f}' for n in (b.total,b.discount,b.paid,b.remaining)],b.state]])
            return app.response_class('\ufeff'+out.getvalue(),mimetype='text/csv',headers={'Content-Disposition':'attachment; filename="generated-challans.csv"'})
        try:page=int(request.args.get('page','1'));size=int(request.args.get('size','50'))
        except ValueError:raise ValueError('Choose valid pagination.')
        if page<1 or size not in (25,50,100):raise ValueError('Choose 25, 50 or 100 rows per page.')
        total=len(bills);pages=max(1,(total+size-1)//size);page=min(page,pages);bills=bills[(page-1)*size:page*size]
        latest={}
        for bid,day in db.session.query(Receipt.bill_id,db.func.max(Receipt.day)).filter(Receipt.voided==False,Receipt.bill_id.in_([b.id for b in bills])).group_by(Receipt.bill_id).all():latest[bid]=day
        def link(**kw):
            args=request.args.to_dict();args.update(kw);return url_for('challan_amounts.index',**args)
        return render_template('challan_amounts.html',title='Add Amount in Generated Challans',bills=bills,people=people,latest=latest,heads=list(heads().values()),start=start,end=end,total=total,page=page,pages=pages,size=size,options=options,filter_choices=app.extensions['record_helpers']['choices'](),link=link,adjust_scopes=scopes(app,'fees.adjust'),pending_key='sf-challan-adjust-'+hashlib.sha256(json.dumps(binding()).encode()).hexdigest()[:24])
    @bp.post('/preview')
    def preview():
        operation=parse();ids=selected();bills,people=load(ids);nonce=secrets.token_hex(16);who=actor(app)
        head,rows=calculate(bills,people,operation,nonce)
        payload=dict(nonce=nonce,actor=who['key'],binding=binding(),permission_stamp=stamp(app),operation=operation,head=[head['key'],head['version'],head['label'],head['timing']],bills=[[b.id,bill_stamp(b,people[b.id])] for b in bills])
        token=serializer().dumps(payload)
        return jsonify(review_token=token,html=render_template('challan_amount_preview.html',rows=rows,head=head),count=len(rows))
    @bp.post('/apply')
    def apply():
        try:payload,issued=serializer().loads(request.form.get('review_token',''),max_age=86400,return_timestamp=True)
        except SignatureExpired:abort(409,'This review expired. Preview again.')
        except BadData:abort(400,'This review is invalid. Preview again.')
        who=actor(app);operation=parse();ids=selected()
        if payload.get('actor')!=who['key'] or payload.get('binding')!=binding() or payload.get('permission_stamp')!=stamp(app):abort(403,'Your account or permissions changed. Preview again.')
        if operation!=payload.get('operation') or ids!=[r[0] for r in payload.get('bills',[])]:abort(409,'The selected challans or entered details changed. Preview again.')
        bills,people=load(ids,True)
        saved=db.session.get(Change,payload['nonce'])
        if saved:
            if saved.actor!=who['key'] or saved.operation!=operation:abort(409,'This review was already used for another operation.')
            flash('This reviewed change was already saved. No duplicate amount was added.','success')
            return jsonify(message='This reviewed change was already saved. No duplicate amount was added.',already_saved=True)
        if (datetime.now(timezone.utc)-issued).total_seconds()>600:abort(409,'This review expired. Check challan History, then preview again.')
        if payload['bills']!=[[b.id,bill_stamp(b,people[b.id])] for b in bills]:abort(409,'A challan, payment or student changed after review. Preview the complete batch again.')
        head,rows=calculate(bills,people,operation,payload['nonce'])
        if payload.get('head')!=[head['key'],head['version'],head['label'],head['timing']]:abort(409,'The fee head changed after review. Preview again.')
        if payload['permission_stamp']!=stamp(app):abort(403)
        change=Change(id=payload['nonce'],actor=who['key'],actor_label=who['label'],operation=operation);db.session.add(change)
        for row in rows:row['bill'].lines=row['lines']
        db.session.flush()
        for row in rows:
            b=row['bill'];cohort=Cohort.query.filter_by(bill_id=b.id,active=True).order_by(Cohort.id.desc()).first()
            if cohort is None:raise ValueError('The challan audit identity is missing. No adjustment was saved.')
            db.session.add(ChangeLine(change_id=change.id,bill_id=b.id,cohort_id=cohort.id,student_id=b.student_id,campus=row['student']['campus'],before=row['before'],after=snapshot(b)))
        db.session.add(Audit(action='Change generated challan amount',data=dict(request_id=change.id,operation=operation,bill_ids=ids,campuses=sorted({p['campus'] for p in people.values()}),owner_id=session.get('owner_id'),staff_id=session.get('staff_id'))))
        db.session.commit()
        flash('Reviewed amount changes saved. Previous payments and fee plans were retained.','success')
        return jsonify(message='Reviewed amounts saved in '+str(len(rows))+' challan(s). Existing payments and fee plans were retained.',already_saved=False)
    @bp.get('/<int:bill_id>/history')
    def history(bill_id):
        bill=db.get_or_404(Bill,bill_id);people=describe([bill],'fees.view')
        cohort=Cohort.query.filter_by(bill_id=bill.id,active=True).order_by(Cohort.id.desc()).first()
        rows=[]
        if cohort:
            rows=db.session.query(ChangeLine,Change).join(Change,Change.id==ChangeLine.change_id).filter(ChangeLine.bill_id==bill.id,ChangeLine.cohort_id==cohort.id).order_by(Change.created.desc(),ChangeLine.id.desc()).all()
        return render_template('challan_amount_history.html',title='Challan amount history',bill=bill,student=people[bill.id],rows=rows,local=lambda dt:dt.replace(tzinfo=timezone.utc).astimezone(ZoneInfo('Asia/Karachi')).strftime('%Y-%m-%d %H:%M'))
    app.register_blueprint(bp)
