"""Reviewed fine liabilities, posted once to a later unpaid challan."""
import copy,hashlib,hmac,json
from datetime import datetime,timezone
from flask import Blueprint,abort,flash,g,redirect,render_template,request,session,url_for
from itsdangerous import BadData,URLSafeTimedSerializer
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import StaleDataError


def configure_fine_queue(app,db,Student):
    bp=Blueprint('fine_queue',__name__,url_prefix='/workspace/core/fees/pending-fines')
    ops=app.extensions['ops_models'];Bill=ops['bill'];Audit=ops['audit']
    class FineCharge(db.Model):
        id=db.Column(db.Integer,primary_key=True)
        student_id=db.Column(db.Integer,db.ForeignKey('student.id'),nullable=False,index=True)
        source=db.Column(db.String(160),nullable=False,unique=True)
        kind=db.Column(db.String(30),nullable=False)
        target_month=db.Column(db.String(7),nullable=False,index=True)
        amount=db.Column(db.Integer,nullable=False)
        data=db.Column(db.JSON,nullable=False)
        bill_id=db.Column(db.Integer,db.ForeignKey('bill.id'),index=True)
        origin_bill_id=db.Column(db.Integer,db.ForeignKey('bill.id'),index=True)
        created=db.Column(db.DateTime,nullable=False,default=lambda:datetime.now(timezone.utc))
        version=db.Column(db.Integer,nullable=False,default=1)
        __mapper_args__={'version_id_col':version}
        __table_args__={'sqlite_autoincrement':True}
    app.extensions['fine_charge_model']=FineCharge
    def actor():return dict(scope=(getattr(g,'school_identity',None) or {}).get('scope'),owner=session.get('owner_id'),csrf=session.get('record_csrf'))
    def signer():return URLSafeTimedSerializer(app.config['SECRET_KEY'],salt='schoolflow-fine-posting-v1')
    def stamp(charge):return [charge.id,charge.version,charge.student_id,charge.target_month,charge.amount,charge.bill_id,hashlib.sha256(json.dumps(charge.data,sort_keys=True).encode()).hexdigest()]
    def pending():return FineCharge.query.filter_by(bill_id=None).order_by(FineCharge.target_month,FineCharge.id).limit(101).all()
    def line(charge):
        saved=copy.deepcopy(charge.data['line'])
        saved.update(amount=charge.amount,kind='attendance_fine' if charge.kind=='attendance' else 'late_fee_forward',fine_charge_id=charge.id,fine_source=charge.source)
        return saved
    def validate(charge,bill):
        if charge.bill_id is not None:raise ValueError('A selected fine was already posted. Reload before applying.')
        pupil=db.session.get(Student,charge.student_id)
        if not pupil or pupil.status!='Active':raise ValueError('A selected student is no longer active.')
        if bill.student_id!=charge.student_id or bill.month<charge.target_month:raise ValueError('Choose this student’s challan in the target month or later.')
        if bill.frozen or bill.paid or bill.discount:raise ValueError('Only unpaid, undiscounted, unfrozen challans can receive pending fines.')
        if any(x.get('fine_charge_id')==charge.id for x in bill.lines):raise ValueError('This fine is already present on the challan.')
        if bill.total+charge.amount>99999999900:raise ValueError('The challan total would exceed the supported amount.')
    def post(charge,bill):
        validate(charge,bill);bill.lines=[*bill.lines,line(charge)];charge.bill_id=bill.id
        db.session.add(Audit(action='Post pending fine',data=dict(charge_id=charge.id,source=charge.source,student_id=charge.student_id,bill_id=bill.id,amount=charge.amount,owner_id=session.get('owner_id'))))
    def generation_token(rows):return signer().dumps(dict(actor=actor(),kind='generation',charges=[stamp(c) for c in rows]))
    def generation_rows():return pending()[:100]
    def load(raw,kind):
        if not raw or len(raw)>131072:raise ValueError('Reload and review the pending fines before applying.')
        try:payload=signer().loads(raw,max_age=900)
        except BadData:raise ValueError('The pending-fine review expired or changed. Reload it.')
        if not isinstance(payload,dict) or payload.get('actor')!=actor() or payload.get('kind')!=kind:raise ValueError('This fine review belongs to another institute or session.')
        return payload
    def for_generation(student,at,payload):
        selected=[]
        for saved in payload['charges']:
            if saved[2]!=student.id or saved[3]>at:continue
            charge=db.session.get(FineCharge,saved[0])
            if not charge or stamp(charge)!=saved:raise ValueError('A reviewed pending fine changed. Reload before generating; no challans were saved.')
            selected.append(charge)
        return selected
    @bp.before_request
    def protect():
        if request.method=='POST':
            if not request.form.get('_csrf') or not hmac.compare_digest(request.form['_csrf'],session.get('record_csrf','')):abort(400,'Reload the fine review.')
            app.extensions['admission_capacity']['lock']()
    @bp.errorhandler(ValueError)
    def invalid(error):
        db.session.rollback();return render_template('operation_error.html',title='Check pending fines',error=str(error)),422
    @bp.errorhandler(IntegrityError)
    @bp.errorhandler(StaleDataError)
    def conflict(error):
        db.session.rollback();return render_template('operation_error.html',title='Check pending fines',error='A fine or challan changed. Reload the review; no partial batch was posted.'),422
    @bp.route('',methods=['GET','POST'])
    def index():
        if request.method=='POST':
            action=request.form.get('action')
            if request.form.get('cancel_id'):
                cid=request.form['cancel_id'];reason=request.form.get('cancel_reason_'+cid,'').strip()
                if not cid.isdigit() or not 3<=len(reason)<=1000 or request.form.get('cancel_confirm_'+cid)!='1':raise ValueError('Enter a cancellation reason and confirm the selected pending fine.')
                charge=db.get_or_404(FineCharge,int(cid))
                if charge.bill_id is not None or request.form.get('cancel_version_'+cid)!=str(charge.version):raise ValueError('This fine was posted or changed. Reload before cancelling.')
                db.session.add(Audit(action='Cancel unposted fine',data=dict(charge_id=charge.id,student_id=charge.student_id,source=charge.source,kind=charge.kind,target_month=charge.target_month,amount=charge.amount,before=copy.deepcopy(charge.data),reason=reason,owner_id=session.get('owner_id'))))
                db.session.delete(charge);db.session.commit();flash('Unposted fine cancelled with an audit record. Correct the source and review again if needed.','success');return redirect(url_for('fine_queue.index'))
            if action=='preview':
                raw=request.form.getlist('ids')
                if not raw or len(raw)>100 or any(not x.isdigit() for x in raw):raise ValueError('Select 1–100 pending fines.')
                choices=[];bill_totals={}
                for cid in sorted({int(x) for x in raw}):
                    charge=db.get_or_404(FineCharge,cid);bid=request.form.get('bill_'+str(cid),'')
                    if not bid.isdigit():raise ValueError('Choose a target challan for each selected fine.')
                    bill=db.get_or_404(Bill,int(bid));validate(charge,bill)
                    bill_totals[bill.id]=bill_totals.get(bill.id,bill.total)+charge.amount
                    if bill_totals[bill.id]>99999999900:raise ValueError('The combined fine amount would exceed the supported challan total.')
                    choices.append(dict(charge=stamp(charge),bill=[bill.id,bill.version,bill.month,bill.total,bill.paid,bill.discount,bill.frozen]))
                token=signer().dumps(dict(actor=actor(),kind='post',choices=choices))
                rows=[(db.session.get(FineCharge,c['charge'][0]),db.session.get(Bill,c['bill'][0])) for c in choices]
                response=render_template('fine_queue_review.html',title='Review pending-fine posting',rows=rows,students={s.id:s for s in Student.query.filter(Student.id.in_({c.student_id for c,b in rows})).all()},token=token)
                db.session.rollback();return response
            if action!='apply':raise ValueError('Preview selected fines before posting.')
            payload=load(request.form.get('preview_token',''),'post');choices=payload.get('choices',[])
            if not choices or len(choices)>100:raise ValueError('Invalid fine review.')
            for c in choices:
                charge=db.session.get(FineCharge,c['charge'][0]);bill=db.session.get(Bill,c['bill'][0])
                if not charge or stamp(charge)!=c['charge'] or not bill or [bill.id,bill.version,bill.month,bill.total,bill.paid,bill.discount,bill.frozen]!=c['bill']:raise ValueError('A fine or challan changed. Preview the full batch again.')
            for c in choices:post(db.session.get(FineCharge,c['charge'][0]),db.session.get(Bill,c['bill'][0]))
            db.session.commit();flash('Reviewed fines posted once to the selected challans.','success');return redirect(url_for('fine_queue.index'))
        rows=pending();more=len(rows)>100;rows=rows[:100];ids={c.student_id for c in rows}
        students={s.id:s for s in Student.query.filter(Student.id.in_(ids)).all()}
        bills=Bill.query.filter(Bill.student_id.in_(ids),Bill.paid==0,Bill.discount==0,Bill.frozen==False).order_by(Bill.month,Bill.id).all()
        return render_template('fine_queue.html',title='Pending fines for later challans',rows=rows,students=students,bills=bills,more=more)
    app.extensions['fine_queue_helpers']=dict(line=line,post=post,rows=generation_rows,token=generation_token,load_generation=lambda raw:load(raw,'generation'),for_generation=for_generation,
        bill_used=lambda bid:FineCharge.query.filter((FineCharge.bill_id==bid)|(FineCharge.origin_bill_id==bid)).first() is not None,
        head_used=lambda key:any(c.data.get('line',{}).get('particular')==key for c in FineCharge.query.all()))
    app.register_blueprint(bp)
