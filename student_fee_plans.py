"""Student-specific fee plans with server-side money validation and dated snapshots."""
import hmac, re
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from flask import Blueprint, abort, flash, redirect, render_template, request, session, url_for
from sqlalchemy import String,cast,and_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import StaleDataError
from operations import money

PARTICULARS = ('Admission Fee','Tuition Fee','Annual Charges','Tie and Badge Amount','File Charges','Books Payment','Badge Amount','Registration Fee')

def configure_student_fee_plans(app, db, Student):
    bp = Blueprint('student_plans', __name__, url_prefix='/workspace/student-fee-plans')
    models=app.extensions['ops_models']; Workflow=models['workflow']; Bill=models['bill']; Audit=models['audit']
    details=app.extensions['operation_helpers']['details']; rm=app.extensions['record_models']

    class StudentFeePlan(db.Model):
        id=db.Column(db.Integer,primary_key=True)
        student_id=db.Column(db.Integer,db.ForeignKey('student.id'),nullable=False,index=True)
        effective=db.Column(db.String(7),nullable=False)
        data=db.Column(db.JSON,nullable=False)
        version=db.Column(db.Integer,nullable=False,default=1)
        __table_args__=(db.UniqueConstraint('student_id','effective'),)
        __mapper_args__={'version_id_col':version}
    class FeeArrearsClaim(db.Model):
        id=db.Column(db.Integer,primary_key=True)
        student_id=db.Column(db.Integer,db.ForeignKey('student.id'),nullable=False)
        particular=db.Column(db.String(200),nullable=False)
        bill_id=db.Column(db.Integer,db.ForeignKey('bill.id'),nullable=False)
        bill=db.relationship(Bill,backref=db.backref('assigned_arrears_claims',cascade='all, delete-orphan'))
        __table_args__=(db.UniqueConstraint('student_id','particular'),)
    app.extensions['student_fee_plan_model']=StudentFeePlan
    app.extensions['fee_arrears_claim_model']=FeeArrearsClaim

    def current(sid, at=None):
        q=StudentFeePlan.query.filter_by(student_id=sid)
        if at: q=q.filter(StudentFeePlan.effective<=at)
        return q.order_by(StudentFeePlan.effective.desc()).first()
    def month(v):
        if not re.fullmatch(r'\d{4}-\d{2}',v or ''): raise ValueError('Enter a valid month.')
        try: date.fromisoformat(v+'-01')
        except ValueError: raise ValueError('Enter a valid month.')
        return v
    def templates(s):
        d=details(s); result={}
        for w in Workflow.query.filter_by(kind='fee-plans',status='Active').order_by(Workflow.id).all():
            data=w.data
            if data.get('campus') and data['campus']!=d.get('campus'): continue
            if data.get('class_name') and data['class_name']!=s.class_name: continue
            result.setdefault(data['name'],[]).append(w)
        return result
    def rows_for(s,name):
        group=templates(s).get(name)
        if not group: raise ValueError('Choose a configured fee schedule for this campus and class.')
        amounts={}
        for w in group:
            key=w.data['particular'].strip()
            if key in amounts: raise ValueError('This schedule has duplicate fee particulars. Correct the fee schedule first.')
            amounts[key]=money(w.data['amount'])
        keys=list(PARTICULARS)+[k for k in amounts if k not in PARTICULARS]
        return [dict(particular=k,actual=amounts.get(k,0),discount=0,arrears=0) for k in keys]
    def totals(lines): return {k:sum(x[k] for x in lines) for k in ('actual','discount','arrears','net')}
    def render(template,**kw): return render_template(template,**kw)
    def commit():
        try: db.session.commit()
        except (IntegrityError,StaleDataError):
            db.session.rollback();raise ValueError('This plan changed while you were editing. Reload before saving again.')
    @bp.before_request
    def csrf():
        if request.method=='POST':
            token=request.form.get('_csrf',''); expected=session.get('record_csrf','')
            if not token or not expected or not hmac.compare_digest(token,expected): abort(400)
    @bp.errorhandler(ValueError)
    def error(exc):
        db.session.rollback();return render('operation_error.html',title='Check fee plan',error=str(exc)),422

    @bp.get('')
    def index():
        mode=request.args.get('mode','create')
        if mode not in ('create','update'):raise ValueError('Choose Create or Update fee plans.')
        try:page=max(1,int(request.args.get('page','1')));size=int(request.args.get('size','25'))
        except ValueError:raise ValueError('Choose valid fee-plan pagination.')
        if size not in (25,50,100):raise ValueError('Choose 25, 50 or 100 rows.')
        campus=request.args.get('campus','');class_name=request.args.get('class_name','');q=request.args.get('q','').strip().lower()
        Details=rm['student']
        latest=db.session.query(StudentFeePlan.student_id,db.func.max(StudentFeePlan.effective).label('effective')).group_by(StudentFeePlan.student_id).subquery()
        scoped=Student.query.outerjoin(Details,Details.student_id==Student.id).outerjoin(latest,latest.c.student_id==Student.id).filter(Student.status=='Active')
        if campus:scoped=scoped.filter(Details.data['campus'].as_string()==campus)
        if class_name:scoped=scoped.filter(Student.class_name==class_name)
        count=scoped.count();with_plan=scoped.filter(latest.c.student_id!=None).count()
        matching=scoped.filter(latest.c.student_id!=None if mode=='update' else latest.c.student_id==None)
        if q:
            text=db.func.lower(db.func.coalesce(Student.name,'')+' '+db.func.coalesce(Student.father,'')+' '+Student.admission_no+' '+cast(Student.id,String)+' '+db.func.coalesce(Student.phone,''))
            matching=matching.filter(text.contains(q,autoescape=True))
        total=matching.count();pages=max(1,(total+size-1)//size);page=min(page,pages)
        students=matching.order_by(Student.id).offset((page-1)*size).limit(size).all()
        raw=app.extensions['record_helpers']['raw_many']('student',students)
        plans={plan.student_id:plan for plan in StudentFeePlan.query.join(latest,and_(StudentFeePlan.student_id==latest.c.student_id,StudentFeePlan.effective==latest.c.effective)).filter(StudentFeePlan.student_id.in_([s.id for s in students])).all()} if students else {}
        rows=[(s,raw[s.id],plans.get(s.id)) for s in students]
        campuses=[row[0] for row in db.session.query(Details.data['campus'].as_string()).join(Student,Student.id==Details.student_id).filter(Student.status=='Active').distinct().order_by(Details.data['campus'].as_string()).all() if row[0]]
        classes=[row[0] for row in db.session.query(Student.class_name).filter(Student.status=='Active').distinct().order_by(Student.class_name).all() if row[0]]
        return render('student_fee_plan_list.html',title='Manage Fee Plans',rows=rows,mode=mode,with_plan=with_plan,without_plan=count-with_plan,campuses=campuses,classes=classes,page=page,pages=pages,total=total,size=size)

    @bp.route('/<int:sid>/edit',methods=['GET','POST'])
    def edit(sid):
        s=db.get_or_404(Student,sid); latest=current(sid); names=templates(s)
        name=request.values.get('schedule') or (latest.data.get('schedule') if latest else details(s).get('fee_plan')) or next(iter(names),'')
        if request.method=='POST':
            if s.status!='Active': raise ValueError('Fee plans can only be assigned to active students.')
            origin=f'{latest.id}:{latest.version}' if latest else 'new'
            if request.form.get('origin')!=origin: raise ValueError('The student plan changed. Reload before saving.')
            effective=month(request.form.get('effective'))
            if latest and effective<latest.effective: raise ValueError('Choose the latest effective month or a later month. Historical plans are read-only.')
            try: pct=Decimal(request.form.get('percentage','0'))
            except InvalidOperation: raise ValueError('Enter a valid percentage.')
            if not pct.is_finite() or pct<0 or pct>Decimal('999999999'): raise ValueError('Enter a non-negative percentage up to 999,999,999.')
            year=request.form.get('year','').strip()
            if year and (not year.isdigit() or not 1900<=int(year)<=9999): raise ValueError('Enter a valid fee plan year.')
            target=StudentFeePlan.query.filter_by(student_id=sid,effective=effective).first()
            # Reuse a saved snapshot only if its schedule is unchanged; a changed schedule loads configured amounts.
            lines=[dict(x) for x in latest.data['lines']] if latest and name==latest.data['schedule'] else rows_for(s,name)
            for i,line in enumerate(lines):
                if f'discount_{i}' not in request.form or f'arrears_{i}' not in request.form: raise ValueError('The fee rows are incomplete. Reload the form.')
                line['discount']=money(request.form.get(f'discount_{i}'))
                line['arrears']=money(request.form.get(f'arrears_{i}'))
                # Editing the same effective month reapplies its percentage to the original
                # base, rather than compounding on every Save. A later month starts
                # from the latest plan's resulting fee, allowing yearly compounding.
                same_period=latest and effective==latest.effective and name==latest.data['schedule']
                base_actual=line.get('base_actual',line['actual']) if same_period else line['actual']
                if line['discount']>base_actual: raise ValueError('Discount cannot exceed the fee before increment: '+line['particular'])
                base_net=base_actual-line['discount']
                increment=int((Decimal(base_net)*pct/100).quantize(Decimal('1'),rounding=ROUND_HALF_UP))
                if base_actual+increment>99999999900: raise ValueError('Fee after increment exceeds the supported amount.')
                line.update(base_actual=base_actual,base_net=base_net,increment=increment,actual=base_actual+increment,net=base_net+increment)
            reason=request.form.get('reason','').strip(); notes=request.form.get('notes','').strip()
            if len(reason)>200 or len(notes)>5000: raise ValueError('Discount reason or notes are too long.')
            data=dict(schedule=name,lines=lines,percentage=str(pct),year=year,reason=reason,notes=notes)
            old=dict(target.data) if target else None
            if target: target.data=data
            else: target=StudentFeePlan(student_id=sid,effective=effective,data=data);db.session.add(target)
            db.session.add(Audit(action='Save student fee plan',data=dict(student_id=sid,effective=effective,before=old,after=data)))
            commit();flash('Student fee plan saved. Existing challans retain their saved amounts.','success')
            return redirect(url_for('student_plans.view',sid=sid,plan_id=target.id))
        if latest and name==latest.data['schedule']: lines=latest.data['lines']
        else: lines=rows_for(s,name) if name in names else []
        return render('student_fee_plan_edit.html',title='Update Fee Plan' if latest else 'Create Fee Plan',s=s,d=details(s),plan=latest,lines=lines,names=names,name=name,origin=f'{latest.id}:{latest.version}' if latest else 'new',today=date.today().isoformat(),total=totals([dict(x,net=x['actual']-x['discount']) for x in lines]))

    @bp.get('/<int:sid>')
    def view(sid):
        s=db.get_or_404(Student,sid); p=current(sid)
        if request.args.get('plan_id'):
            try: pid=int(request.args['plan_id'])
            except ValueError: abort(404)
            p=db.get_or_404(StudentFeePlan,pid)
            if p.student_id!=sid: abort(404)
        if not p: return redirect(url_for('student_plans.edit',sid=sid))
        photo=rm['file'].query.filter_by(owner_kind='student',owner_id=sid,photo=True).first()
        return render('student_fee_plan_view.html',title='Student Fee Plan',s=s,d=details(s),plan=p,photo=photo,total=totals(p.data['lines']),history=StudentFeePlan.query.filter_by(student_id=sid).order_by(StudentFeePlan.effective.desc()).all())

    @bp.route('/generate',methods=['GET','POST'])
    def generate():
        students=Student.query.filter_by(status='Active').order_by(Student.name).all()
        all_heads=sorted({x['particular'] for p in StudentFeePlan.query.all() for x in p.data['lines'] if x['net'] or x['arrears']})
        if request.method=='POST':
            at=month(request.form.get('month'))
            try: due=date.fromisoformat(request.form.get('due',''))
            except ValueError: raise ValueError('Choose a valid due date.')
            try: ids=list(dict.fromkeys(int(x) for x in request.form.getlist('student_ids')))
            except ValueError: raise ValueError('Invalid student selection.')
            heads=set(request.form.getlist('particular'))
            if not ids or not heads or not heads<=set(all_heads): raise ValueError('Select students and the fee particulars to charge for this run.')
            count=0
            for sid in ids:
                s=db.get_or_404(Student,sid);p=current(sid,at)
                if s.status!='Active' or not p: raise ValueError('Each selected student must be active with a plan effective by the challan month.')
                source=f'assigned:student:{sid}:month:{at}'
                if Bill.query.filter_by(source=source).first(): continue
                # An earlier manually generated bill requires review, not a second monthly bill.
                if Bill.query.filter_by(student_id=sid,month=at).first(): raise ValueError('A challan already exists for a selected student in this month. Review it before generating another.')
                used={line.get('arrears_key') for bill in Bill.query.filter_by(student_id=sid).all() for line in bill.lines}
                lines=[]; claim_heads=[]
                for x in p.data['lines']:
                    if x['particular'] not in heads: continue
                    if x['net']: lines.append(dict(particular=x['particular'],amount=x['net'],actual=x['actual'],plan_discount=x['discount'],plan_id=p.id))
                    key=f"student:{sid}:particular:{x['particular']}"
                    if request.form.get('include_arrears')=='on' and x['arrears'] and key not in used and not FeeArrearsClaim.query.filter_by(student_id=sid,particular=x['particular']).first():
                        lines.append(dict(particular=x['particular']+' — First Time Arrears',amount=x['arrears'],arrears_key=key,plan_id=p.id));claim_heads.append(x['particular'])
                if not lines: raise ValueError('The selected particulars have no amount to charge for a student.')
                bill=Bill(student_id=sid,month=at,due=due,lines=lines,source=source);db.session.add(bill)
                for head in claim_heads: db.session.add(FeeArrearsClaim(student_id=sid,particular=head,bill=bill))
                count+=1
            db.session.add(Audit(action='Generate assigned fee challans',data=dict(month=at,count=count,particulars=sorted(heads))))
            commit();flash(f'{count} challans generated; already generated student/month combinations skipped.','success')
            return redirect(url_for('ops.fees',mode='payments'))
        return render('student_fee_plan_generate.html',title='Generate from Student Fee Plans',students=[s for s in students if current(s.id)],heads=all_heads,today=date.today().isoformat())
    app.register_blueprint(bp)
