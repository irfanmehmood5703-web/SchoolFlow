"""SchoolFlow pre-test workflows. Amounts use integer paisa; no external messages are sent."""
import calendar, csv, hmac, io, json, re, secrets
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from flask import Blueprint, abort, flash, jsonify, redirect, render_template, request, session, url_for
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import StaleDataError
from module_catalog import MENUS, TITLES, SCHEMAS, STATUSES


def money(value):
    try:
        n = Decimal(str(value or 0))
        if not n.is_finite() or n < 0 or n > Decimal('999999999'):
            raise ValueError('Amount must be between 0 and 999,999,999.')
        return int((n * 100).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
    except (InvalidOperation, TypeError):
        raise ValueError('Enter a valid amount.')


def configure_operations(app, db, Student, Employee):
    bp = Blueprint('ops', __name__, url_prefix='/workspace')
    rm = app.extensions['record_models']

    class Workflow(db.Model):
        id = db.Column(db.Integer, primary_key=True)
        kind = db.Column(db.String(60), nullable=False, index=True)
        data = db.Column(db.JSON, nullable=False, default=dict)
        status = db.Column(db.String(30), nullable=False, default='Draft')
        created = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    class Bill(db.Model):
        id = db.Column(db.Integer, primary_key=True)
        student_id = db.Column(db.Integer, db.ForeignKey('student.id'), nullable=False)
        month = db.Column(db.String(7), nullable=False)
        due = db.Column(db.Date, nullable=False)
        lines = db.Column(db.JSON, nullable=False)
        paid = db.Column(db.Integer, nullable=False, default=0)
        discount = db.Column(db.Integer, nullable=False, default=0)
        frozen = db.Column(db.Boolean, nullable=False, default=False)
        source = db.Column(db.String(100), unique=True)
        notes = db.Column(db.Text, default='')
        version = db.Column(db.Integer, nullable=False, default=1)
        __mapper_args__ = {'version_id_col': version}
        @property
        def total(self): return sum(x['amount'] for x in self.lines)
        @property
        def remaining(self): return self.total - self.paid - self.discount
        @property
        def state(self): return 'Fully Paid' if self.remaining == 0 else ('Partially Paid' if self.paid else 'Unpaid')

    class Receipt(db.Model):
        id = db.Column(db.Integer, primary_key=True)
        student_id = db.Column(db.Integer, db.ForeignKey('student.id'), nullable=False)
        bill_id = db.Column(db.Integer, db.ForeignKey('bill.id'), nullable=False)
        amount = db.Column(db.Integer, nullable=False)
        discount = db.Column(db.Integer, nullable=False, default=0)
        day = db.Column(db.Date, nullable=False)
        account = db.Column(db.String(160), nullable=False)
        discount_account = db.Column(db.String(160), default='Discounts')
        notes = db.Column(db.Text, default='')
        voided = db.Column(db.Boolean, default=False, nullable=False)
        token = db.Column(db.String(100), unique=True, nullable=False)

    class Daily(db.Model):
        id = db.Column(db.Integer, primary_key=True)
        kind = db.Column(db.String(10), nullable=False)
        person_id = db.Column(db.Integer, nullable=False)
        day = db.Column(db.Date, nullable=False)
        status = db.Column(db.String(30), nullable=False)
        lectures = db.Column(db.Integer, nullable=False, default=0)
        time_in = db.Column(db.String(10), default='')
        time_out = db.Column(db.String(10), default='')
        __table_args__ = (db.UniqueConstraint('kind','person_id','day'),)

    class Score(db.Model):
        id = db.Column(db.Integer, primary_key=True)
        award_id = db.Column(db.Integer, db.ForeignKey('workflow.id'), nullable=False)
        student_id = db.Column(db.Integer, db.ForeignKey('student.id'), nullable=False)
        paper = db.Column(db.Integer, nullable=False)
        obtained = db.Column(db.Float)
        state = db.Column(db.String(10), default='')
        __table_args__ = (db.UniqueConstraint('award_id','student_id','paper'),)

    class Salary(db.Model):
        id = db.Column(db.Integer, primary_key=True)
        employee_id = db.Column(db.Integer, db.ForeignKey('employee.id'), nullable=False)
        month = db.Column(db.String(7), nullable=False)
        earnings = db.Column(db.Integer, nullable=False)
        deductions = db.Column(db.Integer, nullable=False)
        net = db.Column(db.Integer, nullable=False)
        detail = db.Column(db.JSON, nullable=False)
        paid = db.Column(db.Integer, nullable=False, default=0)
        paid_date = db.Column(db.Date)
        credit = db.Column(db.String(120), default='')
        debit = db.Column(db.String(120), default='')
        version = db.Column(db.Integer, nullable=False, default=1)
        __mapper_args__ = {'version_id_col': version}
        __table_args__ = (db.UniqueConstraint('employee_id','month'),)

    class Audit(db.Model):
        id = db.Column(db.Integer, primary_key=True)
        action = db.Column(db.String(120), nullable=False)
        data = db.Column(db.JSON, nullable=False)
        created = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    app.extensions['ops_models'] = dict(workflow=Workflow,bill=Bill,receipt=Receipt,daily=Daily,score=Score,salary=Salary,audit=Audit)
    app.jinja_env.filters['cash'] = lambda x: f'{(x or 0)/100:,.2f}'
    app.jinja_env.globals.update(zip=zip)

    def audit(action, **data): db.session.add(Audit(action=action, data=data))
    def commit():
        try: db.session.commit()
        except (IntegrityError, StaleDataError):
            db.session.rollback()
            raise ValueError('This operation was already saved or another user changed the record. Reload before retrying.')
    def day(value):
        try: return date.fromisoformat(value)
        except (ValueError, TypeError): raise ValueError('Enter a valid date.')
    def month(value):
        if not re.fullmatch(r'\d{4}-\d{2}', value or ''): raise ValueError('Enter a valid month.')
        day(value+'-01'); return value
    def details(person, kind='student'):
        key='student_id' if kind=='student' else 'employee_id'
        d=rm[kind].query.filter_by(**{key:person.id}).first()
        data=dict(d.data or {}) if d else {}
        if kind=='student' and d and d.family_id:
            family=db.session.get(rm['family'], d.family_id)
            if family: data.update(family.data, family_no=family.number)
        return data
    def choices(kind):
        if kind in ('employee','teacher','student'):
            cls=Student if kind=='student' else Employee
            return [(str(x.id),x.name) for x in cls.query.order_by(cls.name).all() if kind!='teacher' or 'teacher' in (x.role or '').lower()]
        return [(x.value,x.value) for x in rm['settings'].query.filter_by(category=kind).order_by(rm['settings'].value).all()]
    def people(kind='student', active=True):
        cls=Student if kind=='student' else Employee
        objs=cls.query.order_by(cls.id).all()
        for k in ('campus','class_name','section','academic_session'):
            v=request.values.get(k,'')
            if v: objs=[x for x in objs if (x.class_name if k=='class_name' and kind=='student' else details(x,kind).get(k))==v]
        if active: objs=[x for x in objs if x.status=='Active']
        return objs
    def selected(name='ids'):
        try: return list(dict.fromkeys(int(x) for x in request.form.getlist(name)))
        except ValueError: raise ValueError('Invalid selection.')
    def queue(subject, ids, audience='parent'):
        prefs={k: request.form.get(k)=='on' for k in ['father_contact','mother_contact','student_contact','app_sms','branded_sms','whatsapp_sms','parent_notification','teacher_notification']}
        db.session.add(Workflow(kind='message',status='Provider not configured',data=dict(subject=subject,ids=ids,audience=audience,preferences=prefs)))
    def render(name, **kw):
        return render_template(name, choices=choices, today=date.today().isoformat(), statuses=STATUSES, **kw)

    @app.context_processor
    def nav_context(): return dict(module_menus=MENUS, build_label='Pre-test • fictional records only')

    @bp.before_request
    def csrf():
        if request.method=='POST':
            token=request.form.get('_csrf','')
            if not token or not hmac.compare_digest(token,session.get('record_csrf','')): abort(400,'Form session expired. Reload the page.')

    @bp.errorhandler(ValueError)
    def invalid(exc):
        db.session.rollback()
        return render('operation_error.html',title='Please check this operation',error=str(exc)),422

    @bp.route('/<key>')
    def entry(key):
        if key in ('students','employees'): return redirect('/records/'+('student' if key=='students' else 'employee'))
        if key in ('challans','payments','inactive-fees','paid-challans','discount-challans'): return redirect(url_for('ops.fees',mode=key))
        if key=='fee-plans': return redirect(url_for('student_plans.index'))
        if key=='payment-history': return redirect(url_for('ops.history'))
        if key in ('student-fees','fee-report','daily-fees','class-fees','defaulters','family-defaulters','monthly-defaulters','fee-reminder'): return redirect(url_for('reports.fees',view=key))
        if key in ('student-attendance','staff-attendance'): return redirect(url_for('ops.take_attendance',kind='staff' if key.startswith('staff') else 'student'))
        if key in ('combined-attendance','daily-attendance','individual-attendance','attendance-summary','absentees','attendance-sheet','staff-attendance-report'): return redirect(url_for('reports.attendance',view=key))
        if key in ('salary-plans','update-salary'): return redirect(url_for('ops.plans'))
        if key in ('generate-salary','pay-salary','salary-report','lecture-report'): return redirect(url_for('ops.payroll',view=key))
        if key in ('date-sheets','awards'): return redirect(url_for('ops.examination',kind=key))
        if key=='roll-slips': return redirect(url_for('ops.rolls'))
        if key in SCHEMAS: return redirect(url_for('ops.register',kind=key))
        if key in ('sms-blaster','fee-intimation'): return redirect(url_for('ops.messages'))
        if key in ('sms-report','family-sms','notifications','staff-sms'): return redirect(url_for('ops.message_log',view=key))
        if key=='admission-approvals':
            return render('approvals.html',title=TITLES[key],key=key,rows=Student.query.filter_by(status='Waiting').all())
        if key=='salary-approvals': return redirect(url_for('ops.plans'))
        if key=='teacher-performance': return redirect(url_for('reports.teacher_performance'))
        if key=='student-360': return redirect('/records/student?status=')
        return render('reference_pending.html',title=TITLES.get(key,key),key=key)

    @bp.route('/register/<kind>',methods=['GET','POST'])
    def register(kind):
        if kind not in SCHEMAS: abort(404)
        schema=SCHEMAS[kind]
        if request.method=='POST':
            action=request.form.get('action','save')
            if action in ('approve','reject','delete'):
                if kind not in ('increments','advances','leave-approvals','lecture-register'): raise ValueError('This record type does not use approval actions.')
                rows=Workflow.query.filter(Workflow.id.in_(selected()),Workflow.kind==kind).with_for_update().all()
                if not rows: raise ValueError('Select at least one record.')
                for x in rows:
                    if x.status=='Paid': raise ValueError('Paid records cannot be changed.')
                    x.status={'approve':'Approved','reject':'Rejected','delete':'Voided'}[action]
                audit(action,kind=kind,ids=[x.id for x in rows]); commit()
            else:
                data={}
                for key,label,typ,required in schema:
                    value=request.form.get(key,'').strip()
                    if required and not value: raise ValueError(label+' is required.')
                    if len(value)>5000: raise ValueError(label+' is too long.')
                    if value and typ=='date': day(value)
                    if value and typ=='month': month(value)
                    if typ=='money': money(value)
                    if typ=='integer' and value and (not value.isdigit() or int(value)>100000): raise ValueError(label+' must be a non-negative integer.')
                    if typ in ('employee','teacher','student') and value and value not in dict(choices(typ)): raise ValueError('Choose a valid '+label+'.')
                    if '|' in typ and value not in typ.split('|'): raise ValueError('Invalid '+label+'.')
                    data[key]=bool(value) if typ=='checkbox' else value
                if data.get('from_date') and data.get('to_date') and data['from_date']>data['to_date']: raise ValueError('End date must follow start date.')
                if kind=='fee-plans' and not 1<=int(data['due_day'])<=28: raise ValueError('Due day must be between 1 and 28 for this pre-test build.')
                if kind=='advances' and (money(data['amount'])==0 or money(data['return_amount'])==0 or money(data['return_amount'])>money(data['amount'])): raise ValueError('Monthly return must be positive and no greater than the advance.')
                state='Pending' if kind in ('increments','advances','leave-approvals') else 'Active'
                if kind=='lecture-register':
                    state='Approved' if data.get('approve') else 'Pending'
                    if not int(data['lectures']): raise ValueError('Lectures must be positive.')
                obj=Workflow(kind=kind,data=data,status=state);db.session.add(obj)
                audit('Create '+kind);commit()
                flash('Record saved.','success')
            return redirect(url_for('ops.register',kind=kind))
        rows=Workflow.query.filter_by(kind=kind).filter(Workflow.status!='Voided').order_by(Workflow.id.desc()).all()
        return render('register.html',title=TITLES[kind],kind=kind,schema=schema,rows=rows)

    @bp.route('/approve-students',methods=['POST'])
    def approve_students():
        ids=selected()
        rows=Student.query.filter(Student.id.in_(ids),Student.status=='Waiting').all()
        if not rows: raise ValueError('Select a waiting student.')
        for x in rows: x.status='Active' if request.form.get('action')=='approve' else 'Inactive'
        audit('Admission approval',ids=ids);commit();return redirect(url_for('ops.entry',key='admission-approvals'))

    def filtered_bills(mode='payments'):
        rows=Bill.query.order_by(Bill.id.desc()).all()
        if mode=='inactive-fees': rows=[b for b in rows if db.session.get(Student,b.student_id).status!='Active']
        elif mode in ('payments','challans'): rows=[b for b in rows if db.session.get(Student,b.student_id).status=='Active']
        q=request.args.get('q','').lower()
        for k in ('campus','class_name','section'):
            v=request.args.get(k)
            if v: rows=[b for b in rows if (db.session.get(Student,b.student_id).class_name if k=='class_name' else details(db.session.get(Student,b.student_id)).get(k))==v]
        if q: rows=[b for b in rows if q in str(b.id) or q in db.session.get(Student,b.student_id).name.lower()]
        return rows

    @bp.route('/fees/<mode>')
    def fees(mode):
        rows=filtered_bills(mode)
        receipts=Receipt.query.filter_by(voided=False).order_by(Receipt.id.desc()).all() if mode in ('paid-challans','discount-challans') else []
        if mode=='discount-challans': receipts=[r for r in receipts if r.discount]
        return render('fees.html',title={'inactive-fees':'Inactive Student Fee','paid-challans':'Paid Challans','discount-challans':'Challan Discounts'}.get(mode,'Pay or Print Fee Challans'),rows=rows,mode=mode,receipts=receipts,student=lambda id:db.session.get(Student,id),details=details)

    @bp.route('/generate-challans',methods=['GET','POST'])
    def generate_challans():
        plans=Workflow.query.filter_by(kind='fee-plans',status='Active').all()
        if request.method=='POST':
            m=month(request.form.get('month'));p=db.get_or_404(Workflow,int(request.form.get('plan_id','0')))
            if p.kind!='fee-plans' or p.status!='Active': raise ValueError('Choose an active fee plan.')
            amount=money(p.data['amount']);ids=selected('student_ids')
            if not ids: raise ValueError('Select students.')
            created=0
            for id in ids:
                s=db.get_or_404(Student,id)
                assigned=app.extensions.get('student_fee_plan_model')
                if assigned and assigned.query.filter_by(student_id=id).first(): raise ValueError('This student has an assigned fee plan. Use Generate from Student Fee Plans to apply the saved discounts.')
                source=f'plan:{p.id}:student:{id}:month:{m}'
                if Bill.query.filter_by(source=source).first(): continue
                db.session.add(Bill(student_id=id,month=m,due=day(m+'-'+str(p.data['due_day']).zfill(2)),lines=[{'particular':p.data['particular'],'amount':amount}],source=source));created+=1
            audit('Generate challans',count=created,month=m);commit();flash(f'{created} challans generated; duplicates skipped.','success')
            return redirect(url_for('ops.fees',mode='payments'))
        return render('generate_fees.html',title='Generate Fee Challans',plans=plans,students=people(active=False))

    @bp.route('/pay',methods=['GET','POST'])
    def pay():
        sid=request.values.get('student_id')
        bill_id=request.values.get('bill_id')
        mode=request.values.get('mode','current')
        s=db.get_or_404(Student,int(sid or '0'))
        rows=Bill.query.filter_by(student_id=s.id).order_by(Bill.month,Bill.id).all()
        if mode=='current': rows=[b for b in rows if str(b.id)==bill_id]
        rows=[b for b in rows if b.remaining>0]
        if request.method=='POST':
            token=request.form.get('token','')
            if not re.fullmatch(r'[a-zA-Z0-9_-]{20,100}',token): raise ValueError('Reload this payment form.')
            if Receipt.query.filter(Receipt.token.like(token+':%')).first(): raise ValueError('This payment was already submitted.')
            paid_day=day(request.form.get('paid_date'))
            account=request.form.get('account','').strip()
            if not account: raise ValueError('Receiving account is required.')
            count=0
            locked=Bill.query.filter(Bill.id.in_([b.id for b in rows])).with_for_update().all()
            for b in locked:
                amount=money(request.form.get('amount_'+str(b.id)))
                discount=money(request.form.get('discount_'+str(b.id)))
                if not amount and not discount: continue
                if b.frozen: raise ValueError('Unfreeze this challan before changing it.')
                if amount+discount>b.remaining: raise ValueError('Payment and discount cannot exceed the remaining amount.')
                b.paid+=amount;b.discount+=discount
                db.session.add(Receipt(student_id=s.id,bill_id=b.id,amount=amount,discount=discount,day=paid_day,account=account,discount_account=request.form.get('discount_account','Discounts'),notes=request.form.get('notes','')[:5000],token=token+':'+str(b.id)))
                count+=1
            if not count: raise ValueError('Enter a payment or discount amount.')
            if request.form.get('action')=='send': queue('Fee receipt',[s.id])
            audit('Fee payment',student=s.id,count=count);commit();flash('Payment saved. Requested messages are recorded, but no provider is connected.','success')
            return redirect(url_for('ops.history',student_id=s.id,detail='1'))
        return render('pay.html',title='Pay all dues' if mode=='all' else 'Pay this challan',student=s,rows=rows,token=secrets.token_urlsafe(24),mode=mode)

    @bp.route('/fee-action',methods=['POST'])
    def fee_action():
        action=request.form.get('action');ids=selected()
        rows=Bill.query.filter(Bill.id.in_(ids)).with_for_update().all()
        if not rows: raise ValueError('Select at least one challan.')
        if action in ('horizontal','vertical','family'):
            return render('challan_print.html',title='Family Challans' if action=='family' else 'Fee Challans',rows=rows,layout=action,student=lambda id:db.session.get(Student,id),details=details,copies=['Student','Bank','Office'],settings=request.form)
        if action=='freeze' or action=='unfreeze':
            for b in rows: b.frozen=action=='freeze'
            audit(action,ids=ids);commit();return redirect(url_for('ops.fees',mode='payments'))
        if action=='fine': return render('reference_pending.html',title='Late fee preview',key='fine-rule',reason='No late-fee rule has been configured. No fine has been added. The exact fine formula needs verification.')
        if action=='delete':
            if any(b.paid or b.discount or b.frozen for b in rows): raise ValueError('Paid, discounted or frozen challans cannot be deleted. Reverse receipts first.')
            if request.form.get('confirm')!='yes': raise ValueError('Tick the confirmation box before deleting selected unpaid challans.')
            for b in rows: db.session.delete(b)
            audit('Delete unpaid challans',ids=ids);commit();return redirect(url_for('ops.fees',mode='payments'))
        raise ValueError('Choose an available action.')

    @bp.route('/reverse-receipts',methods=['POST'])
    def reverse_receipts():
        if request.form.get('confirm')!='yes': raise ValueError('Confirm the receipt reversal.')
        rows=Receipt.query.filter(Receipt.id.in_(selected()),Receipt.voided==False).with_for_update().all()
        if not rows: raise ValueError('Select receipts.')
        for r in rows:
            b=db.session.execute(db.select(Bill).where(Bill.id==r.bill_id).with_for_update()).scalar_one()
            if b.frozen: raise ValueError('Unfreeze challan before reversing its receipt.')
            b.paid-=r.amount;b.discount-=r.discount;r.voided=True
        audit('Reverse receipts',ids=[r.id for r in rows]);commit();return redirect(url_for('ops.fees',mode='paid-challans'))

    @bp.route('/history')
    def history():
        start=request.args.get('from','');end=request.args.get('to','')
        if start: month(start)
        if end: month(end)
        if start and end and start>end: raise ValueError('From month must precede To month.')
        rows=Bill.query.order_by(Bill.month,Bill.id).all()
        if start: rows=[b for b in rows if b.month>=start]
        if end: rows=[b for b in rows if b.month<=end]
        sid=request.args.get('student_id','');family=request.args.get('family','')
        if sid: rows=[b for b in rows if b.student_id==int(sid)]
        if family: rows=[b for b in rows if details(db.session.get(Student,b.student_id)).get('family_no','Individual '+str(b.student_id))==family]
        summaries={}
        for b in rows:
            s=db.session.get(Student,b.student_id);d=details(s)
            item=summaries.setdefault(s.id,dict(student=s,data=d,payable=0,paid=0,discount=0,remaining=0))
            for k in ('paid','discount','remaining'): item[k]+=getattr(b,k)
            item['payable']+=b.total
        view=request.args.get('view','payment-history');defaulters=request.args.get('defaulters') or 'defaulters' in view or view=='fee-reminder'
        if defaulters: summaries={id:v for id,v in summaries.items() if v['remaining']>0}
        q=request.args.get('q','').lower()
        if q: summaries={id:v for id,v in summaries.items() if q in (v['student'].name+' '+(v['student'].father or '')+' '+v['data'].get('family_no','')).lower()}
        rows=[b for b in rows if b.student_id in summaries]
        families={}
        for item in summaries.values():
            key=item['data'].get('family_no') or 'Individual '+str(item['student'].id)
            group=families.setdefault(key,dict(students=[],payable=0,paid=0,discount=0,remaining=0))
            group['students'].append(item)
            for k in ('payable','paid','discount','remaining'): group[k]+=item[k]
        if request.args.get('export')=='csv':
            return csv_response(['SID','Student','Payable','Discount','Paid','Remaining'],[[id,v['student'].name,*[f'{v[k]/100:.2f}' for k in ('payable','discount','paid','remaining')]] for id,v in summaries.items()],'payment-history')
        return render('history.html',title='Family Payment Statement' if family else TITLES.get(view,'Payment History'),view=view,rows=rows,summaries=summaries,families=families,detail=bool(request.args.get('detail') or family),student=lambda id:db.session.get(Student,id),details=details,receipts=lambda id:Receipt.query.filter_by(bill_id=id,voided=False).order_by(Receipt.day).all())

    @bp.route('/attendance/<kind>',methods=['GET','POST'])
    def take_attendance(kind):
        if kind not in ('student','staff'): abort(404)
        d=day(request.values.get('day',date.today().isoformat()));people_kind='student' if kind=='student' else 'employee'
        objs=people(people_kind)
        if request.method=='POST':
            count=0
            for p in objs:
                status=request.form.get('status_'+str(p.id))
                if not status: continue
                if status not in STATUSES: raise ValueError('Invalid attendance status.')
                row=Daily.query.filter_by(kind=kind,person_id=p.id,day=d).first()
                if not row: row=Daily(kind=kind,person_id=p.id,day=d);db.session.add(row)
                row.status=status
                val=request.form.get('lectures_'+str(p.id),'0')
                if not val.isdigit() or int(val)>1000: raise ValueError('Invalid lecture count.')
                row.lectures=int(val)
                for k in ('time_in','time_out'):
                    val=request.form.get(k+'_'+str(p.id),'')
                    if val and not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d',val): raise ValueError('Enter valid times.')
                    setattr(row,k,val)
                count+=1
            if request.form.get('send'): queue('Attendance',[p.id for p in objs],audience=kind)
            audit('Save attendance',kind=kind,day=str(d),count=count);commit();flash(f'{count} attendance records saved.','success')
            return redirect(url_for('ops.take_attendance',kind=kind,day=d.isoformat()))
        existing={r.person_id:r for r in Daily.query.filter_by(kind=kind,day=d).all()}
        return render('take_attendance.html',title='Staff Attendance' if kind=='staff' else 'Student Attendance',kind=kind,people=objs,existing=existing,day=d,details=lambda p:details(p,people_kind))

    @bp.route('/attendance-report')
    def attendance_report():
        view=request.args.get('view','attendance-summary');kind='staff' if view=='staff-attendance-report' else 'student'
        start=day(request.args.get('from',date.today().replace(day=1).isoformat()));end=day(request.args.get('to',date.today().isoformat()))
        if start>end: raise ValueError('Invalid date range.')
        cls=Student if kind=='student' else Employee
        rows=Daily.query.filter(Daily.kind==kind,Daily.day>=start,Daily.day<=end).order_by(Daily.day.desc(),Daily.person_id).all()
        if view=='absentees': rows=[r for r in rows if r.status=='Absent']
        if request.args.get('person_id'): rows=[r for r in rows if str(r.person_id)==request.args['person_id']]
        if request.args.get('export'): return csv_response(['Date','Name','Status','Lectures','Time In','Time Out'],[[r.day,db.session.get(cls,r.person_id).name,r.status,r.lectures,r.time_in,r.time_out] for r in rows],'attendance')
        return render('attendance_report.html',title=TITLES.get(view,'Attendance Report'),rows=rows,person=lambda id:db.session.get(cls,id),summary=Counter(r.status for r in rows),kind=kind)

    @bp.route('/examination/<kind>',methods=['GET','POST'])
    def examination(kind):
        if kind not in ('date-sheets','awards'): abort(404)
        if request.method=='POST':
            name=request.form.get('name','').strip()
            if not name: raise ValueError('Name is required.')
            if any(x.data.get('name')==name for x in Workflow.query.filter_by(kind=kind).all()): raise ValueError('Name must be unique.')
            papers=[]
            subjects=request.form.getlist('subject');dates=request.form.getlist('exam_date');types=request.form.getlist('test_type');totals=request.form.getlist('total');teachers=request.form.getlist('teacher')
            for i,subject in enumerate(subjects):
                if not subject: raise ValueError('Subject is required on every row.')
                if i>=len(dates) or i>=len(types): raise ValueError('Every paper needs an exam date and test type.')
                d=day(dates[i]);typ=types[i]
                if typ not in ('Written','Oral','Practical'): raise ValueError('Select a valid test type.')
                t=totals[i] if i<len(totals) else '100'
                try: total=float(t)
                except ValueError: raise ValueError('Total marks must be numeric.')
                if not 0<total<=10000: raise ValueError('Total marks must be positive and at most 10,000.')
                teacher=teachers[i] if i<len(teachers) else ''
                if teacher and teacher not in dict(choices('teacher')): raise ValueError('Only designations containing Teacher can receive award lists.')
                papers.append(dict(subject=subject,date=d.isoformat(),type=typ,total=total,teacher=teacher,time=(request.form.getlist('exam_time')+['']*len(subjects))[i] if request.form.get('include_time') else '',syllabus=(request.form.getlist('syllabus')+['']*len(subjects))[i] if request.form.get('include_syllabus') else ''))
            if not papers: raise ValueError('Add at least one subject.')
            data={k:request.form.get(k,'').strip()[:1000] for k in ('name','print_heading','campus','class_name','section','gender','group_name','academic_session','return_date','sort_order','student_filter')}
            data.update(papers=papers,recheck=bool(request.form.get('recheck')))
            if data.get('return_date'): day(data['return_date'])
            obj=Workflow(kind=kind,data=data,status='Active');db.session.add(obj);audit('Create '+kind);commit()
            return redirect(url_for('ops.marks',award_id=obj.id)) if kind=='awards' else redirect(url_for('ops.examination',kind=kind))
        return render('examination.html',title='Create Award List' if kind=='awards' else 'Create Date Sheet',kind=kind,rows=Workflow.query.filter_by(kind=kind).order_by(Workflow.id.desc()).all())

    def award_students(award):
        objs=Student.query.filter_by(status='Active').all()
        for k in ('class_name','campus','section','gender','group_name','academic_session'):
            value=award.data.get(k)
            if value: objs=[s for s in objs if (s.class_name if k=='class_name' else details(s).get(k))==value]
        return objs

    @bp.route('/marks/<int:award_id>',methods=['GET','POST'])
    def marks(award_id):
        award=db.get_or_404(Workflow,award_id)
        if award.kind!='awards': abort(404)
        students=award_students(award);papers=award.data['papers']
        if request.method=='POST':
            for s in students:
                for i,p in enumerate(papers):
                    value=request.form.get(f'mark_{s.id}_{i}','').strip();state=request.form.get(f'state_{s.id}_{i}','')
                    if state not in ('','A','L'): raise ValueError('Invalid paper attendance.')
                    try: n=float(value) if value else None
                    except ValueError: raise ValueError('Marks must be numeric.')
                    if n is not None and (not 0<=n<=p['total']): raise ValueError('Obtained marks must be within total marks.')
                    row=Score.query.filter_by(award_id=award.id,student_id=s.id,paper=i).first()
                    if not row: row=Score(award_id=award.id,student_id=s.id,paper=i);db.session.add(row)
                    row.obtained=None if state else n;row.state=state
            if request.form.get('action')=='send': queue('Exam marks',selected('student_ids'))
            audit('Update marks',award=award.id);commit();flash('Marks saved.','success');return redirect(url_for('ops.marks',award_id=award.id))
        scores={(x.student_id,x.paper):x for x in Score.query.filter_by(award_id=award.id).all()}
        counts=Counter(('Absent' if x.state=='A' else 'Leave' if x.state=='L' else 'Present') for x in scores.values() if x.state or x.obtained is not None)
        return render('marks.html',title='Update Marks',award=award,students=students,papers=papers,scores=scores,counts=counts)

    @bp.route('/rolls',methods=['GET','POST'])
    def rolls():
        if request.method=='POST':
            ids=selected('student_ids')
            if not ids: raise ValueError('Select students.')
            if request.form.get('action')=='assign':
                start=request.form.get('start','1')
                if not start.isdigit() or int(start)<1: raise ValueError('Roll start must be positive.')
                for i,id in enumerate(ids):
                    d=rm['student'].query.filter_by(student_id=id).first()
                    if not d: d=rm['student'](student_id=id,data={});db.session.add(d)
                    d.data={**d.data,'exam_roll_no':str(int(start)+i),'exam_hall':request.form.get('hall',''),'exam_class':request.form.get('exam_class',''),'exam_section':request.form.get('exam_section','')}
                audit('Assign exam rolls/hall',ids=ids);commit();flash('Exam rolls and hall saved.','success')
            else:
                students=[db.get_or_404(Student,id) for id in ids]
                return render('roll_print.html',title=request.form.get('slip_name','Roll Number Slip'),students=students,details=details,exam_date=request.form.get('exam_date'),exam_from=request.form.get('exam_from'),exam_to=request.form.get('exam_to'))
        return render('rolls.html',title='Roll Number Slip',students=people(),details=details)

    @bp.route('/salary-plans',methods=['GET','POST'])
    def plans():
        deduction_types=['Absent','Late','Leave','Short Leave','Death Leave','Paper Leave']
        edit=request.values.get('edit','');obj=db.session.get(Workflow,int(edit)) if edit else None
        if obj and obj.kind!='salary-plans': abort(404)
        if request.method=='POST':
            if request.form.get('action') in ('approve','reject'):
                rows=Workflow.query.filter(Workflow.id.in_(selected()),Workflow.kind=='salary-plans').with_for_update().all()
                if not rows: raise ValueError('Select salary plans.')
                for p in rows: p.status='Approved' if request.form['action']=='approve' else 'Rejected'
                audit('Salary plan '+request.form['action'],ids=[p.id for p in rows]);commit();return redirect(url_for('ops.plans'))
            employee_id=int(request.form.get('employee_id','0'));db.get_or_404(Employee,employee_id)
            data=dict(employee_id=str(employee_id))
            for k in ['basic','security_return','security_payment','incentive_per_lecture','annual_increment','bonus_amount']:
                data[k]=money(request.form.get(k,'0'))
            for k in ['lecture_wise','lecture_incentive','all_present_bonus','sandwich_leave','include_plan_earnings']:
                data[k]=bool(request.form.get(k))
            data['increment_month']=request.form.get('increment_month','')
            data['increment_type']=request.form.get('increment_type','Abs')
            data['rules']=[]
            for i,status in enumerate(deduction_types):
                allowed=request.form.get('allowed_'+str(i),'0');jump=request.form.get('jump_'+str(i),'0');limit=request.form.get('limit_'+str(i),'0')
                if any(not x.isdigit() for x in [allowed,jump,limit]): raise ValueError('Allowed, jump step and max limit must be non-negative whole numbers.')
                typ=request.form.get('type_'+str(i),'Abs');frequency=request.form.get('frequency_'+str(i),'Recursive')
                if typ not in ('Abs','Percent') or frequency not in ('Recursive','Once'): raise ValueError('Invalid deduction setting.')
                deduction=money(request.form.get('deduction_'+str(i),'0'))
                if typ=='Percent' and deduction>10000: raise ValueError('Percentage cannot exceed 100.')
                data['rules'].append(dict(status=status,allowed=int(allowed),type=typ,amount=deduction,frequency=frequency,jump=int(jump),limit=int(limit)))
            if obj: obj.data=data;obj.status='Pending'
            else: db.session.add(Workflow(kind='salary-plans',data=data,status='Pending'))
            audit('Save salary plan',employee=employee_id);commit();flash('Salary plan saved for approval.','success');return redirect(url_for('ops.plans'))
        return render('salary_plans.html',title='Create / Update Salary Plan',rows=Workflow.query.filter_by(kind='salary-plans').order_by(Workflow.id.desc()).all(),employee=lambda id:db.session.get(Employee,int(id)),data=obj.data if obj else {},edit=edit,deduction_types=deduction_types)

    def lecture_amount(entry,month_value):
        if entry.data.get('rate_override'): return money(entry.data['rate_override'])*int(entry.data['lectures'])
        rates=[r for r in Workflow.query.filter_by(kind='lecture-rates',status='Active').all() if r.data['employee_id']==entry.data['employee_id'] and r.data['starts']<=month_value and r.data['status']=='Active' and all(not r.data.get(k) or r.data[k]==entry.data.get(k) for k in ('class_name','section','subject'))]
        rates.sort(key=lambda r:(sum(bool(r.data.get(k)) for k in ('class_name','section','subject')),r.data['starts'],r.id),reverse=True)
        if not rates: raise ValueError('No matching lecture rate for a selected approved lecture.')
        return money(rates[0].data['amount'])*int(entry.data['lectures'])

    @bp.route('/payroll',methods=['GET','POST'])
    def payroll():
        today=date.today();previous=today.replace(day=1).toordinal()-1;default_month=date.fromordinal(previous).strftime('%Y-%m')
        m=month(request.values.get('month',default_month));view=request.values.get('view','generate-salary')
        if request.method=='POST':
            action=request.form.get('action')
            if action=='generate':
                if m>=today.strftime('%Y-%m'): raise ValueError('Pre-test payroll generates completed previous months only.')
                if request.form.get('prorated'): raise ValueError('Proration rules require a verified worked example; no salary was generated.')
                plans_list=Workflow.query.filter_by(kind='salary-plans',status='Approved').order_by(Workflow.id.desc()).all();seen=set();count=0
                chosen=selected('employee_ids')
                if not chosen: raise ValueError('Select employees.')
                for p in plans_list:
                    eid=int(p.data['employee_id'])
                    if eid in seen or eid not in chosen: continue
                    seen.add(eid)
                    if Salary.query.filter_by(employee_id=eid,month=m).first(): continue
                    data=p.data
                    if data.get('sandwich_leave'): raise ValueError('Sandwich-leave calculation requires a verified holiday/workday rule. No payroll was saved.')
                    if any(r.get('jump') or r.get('limit') for r in data['rules']): raise ValueError('Jump-step/max-limit deduction rules require verification. No payroll was saved.')
                    if data.get('annual_increment'): raise ValueError('Annual increment posting needs a verified reference rule. No payroll was saved.')
                    attendance=Daily.query.filter(Daily.kind=='staff',Daily.person_id==eid,Daily.day>=day(m+'-01'),Daily.day<=day(m+'-'+str(calendar.monthrange(int(m[:4]),int(m[5:]))[1]))).all()
                    counts=Counter(r.status for r in attendance);deductions=0;breakdown=[]
                    base=data['basic'];days=calendar.monthrange(int(m[:4]),int(m[5:]))[1]
                    if request.form.get('attendance_based'):
                        for rule in data['rules']:
                            n=max(0,counts[rule['status']]-rule['allowed']);events=min(1,n) if rule['frequency']=='Once' else n
                            amount=rule['amount']*events if rule['type']=='Abs' else int((Decimal(base)*rule['amount']*events/10000/days).quantize(Decimal('1'),rounding=ROUND_HALF_UP))
                            deductions+=amount;breakdown.append(dict(status=rule['status'],count=counts[rule['status']],amount=amount))
                    lecture_rows=[r for r in Workflow.query.filter_by(kind='lecture-register',status='Approved').all() if int(r.data['employee_id'])==eid and r.data['date'][:7]==m]
                    lecture_pay=sum(lecture_amount(r,m) for r in lecture_rows) if data.get('lecture_wise') else 0
                    earnings=(base+data['security_return'] if not data.get('lecture_wise') or data.get('include_plan_earnings') else 0)+lecture_pay
                    if data.get('lecture_incentive'): earnings+=data['incentive_per_lecture']*sum(r.lectures for r in attendance)
                    if data.get('all_present_bonus') and data.get('bonus_amount'): raise ValueError('All-present bonus eligibility requires an attendance-calendar rule. No payroll was saved.')
                    advance_deduction=0
                    for a in Workflow.query.filter_by(kind='advances',status='Approved').all():
                        if int(a.data['employee_id'])!=eid or a.data['date'][:7]>m: continue
                        reserved=sum(s.detail.get('advances',{}).get(str(a.id),0) for s in Salary.query.filter_by(employee_id=eid).all())
                        value=min(money(a.data['return_amount']),max(0,money(a.data['amount'])-reserved))
                        advance_deduction+=value
                    advance_map={}
                    for a in Workflow.query.filter_by(kind='advances',status='Approved').all():
                        if int(a.data['employee_id'])==eid and a.data['date'][:7]<=m:
                            reserved=sum(s.detail.get('advances',{}).get(str(a.id),0) for s in Salary.query.filter_by(employee_id=eid).all())
                            advance_map[str(a.id)]=min(money(a.data['return_amount']),max(0,money(a.data['amount'])-reserved))
                    deductions+=data['security_payment']+advance_deduction
                    if deductions>earnings: raise ValueError('Deductions exceed earnings; review the salary plan.')
                    snapshot=dict(plan=data,attendance=breakdown,lectures=[r.id for r in lecture_rows] if data.get('lecture_wise') else [],lecture_pay=lecture_pay,advances=advance_map,basic=base)
                    db.session.add(Salary(employee_id=eid,month=m,earnings=earnings,deductions=deductions,net=earnings-deductions,detail=snapshot));count+=1
                if not seen: raise ValueError('Selected employees have no approved salary plans.')
                audit('Generate salary',month=m,count=count);commit();flash(f'{count} salaries generated. Existing employee/month salaries skipped.','success')
            elif action in ('pay','send','unpay','delete'):
                ids=selected();rows=Salary.query.filter(Salary.id.in_(ids)).with_for_update().all()
                if not rows: raise ValueError('Select salary rows.')
                for s in rows:
                    lecture_status='Approved'
                    if action in ('pay','send'):
                        if not request.form.get('credit') or not request.form.get('debit'): raise ValueError('Credit and debit accounts are required.')
                        s.paid=s.net;s.paid_date=day(request.form.get('paid_date'));s.credit=request.form['credit'][:120];s.debit=request.form['debit'][:120];lecture_status='Paid'
                    elif action=='unpay': s.paid=0;s.paid_date=None
                    elif action=='delete':
                        if s.paid: raise ValueError('Unpay salary before deletion.')
                        if request.form.get('confirm')!='yes': raise ValueError('Confirm deletion of selected unpaid salaries.')
                        db.session.delete(s)
                    for id in s.detail.get('lectures',[]):
                        r=db.session.get(Workflow,id)
                        if r: r.status=lecture_status
                if action=='send': queue('Salary paid',[s.employee_id for s in rows],audience='teacher')
                audit('Salary '+action,ids=ids);commit()
            elif action in ('slip','signature','report','bank'):
                rows=Salary.query.filter(Salary.id.in_(selected())).all()
                if not rows: raise ValueError('Select salaries to print.')
                return render('salary_print.html',title={'slip':'Salary Slip','signature':'Salary Signature','report':'Salary Report','bank':'Bank Salary Sheet'}[action],rows=rows,employee=lambda id:db.session.get(Employee,id),layout=action)
            else: raise ValueError('Invalid salary action.')
            return redirect(url_for('ops.payroll',view=view,month=m))
        rows=Salary.query.filter_by(month=m).order_by(Salary.id.desc()).all()
        return render('payroll.html',title=TITLES.get(view,'Pay / Print Salary'),view=view,month=m,rows=rows,employees=Employee.query.filter_by(status='Active').all(),employee=lambda id:db.session.get(Employee,id))

    @bp.route('/lecture-import',methods=['POST'])
    def lecture_import():
        m=month(request.form.get('month'));count=0
        plans_list=Workflow.query.filter_by(kind='salary-plans',status='Approved').all()
        eligible={int(p.data['employee_id']) for p in plans_list if p.data.get('lecture_wise')}
        existing={(int(r.data['employee_id']),r.data['date']) for r in Workflow.query.filter_by(kind='lecture-register').filter(Workflow.status!='Voided').all()}
        for row in Daily.query.filter_by(kind='staff').all():
            if row.person_id not in eligible or str(row.day)[:7]!=m or not row.lectures or (row.person_id,str(row.day)) in existing: continue
            db.session.add(Workflow(kind='lecture-register',status='Pending',data=dict(employee_id=str(row.person_id),date=str(row.day),lectures=str(row.lectures),class_name='',section='',subject='',rate_override='',note='Imported from attendance',consecutive=False)))
            existing.add((row.person_id,str(row.day)));count+=1
        audit('Import lectures',month=m,count=count);commit();flash(f'{count} lecture entries imported awaiting approval.','success');return redirect(url_for('ops.register',kind='lecture-register'))

    @bp.route('/messages',methods=['GET','POST'])
    def messages():
        if request.method=='POST':
            body=request.form.get('message','').strip()
            if not body: raise ValueError('Message is required.')
            ids=selected('student_ids')
            if not ids: raise ValueError('Select recipients.')
            if any(not db.session.get(Student,id) for id in ids): raise ValueError('Invalid recipient.')
            queue(body[:5000],ids);commit();flash('Request recorded: provider not configured. No message was sent.','info');return redirect(url_for('ops.message_log'))
        return render('messages.html',title='SMS Blaster / Fee Intimation',students=people(active=False))

    @bp.route('/message-log')
    def message_log():
        return render('message_log.html',title='Communication Requests',rows=Workflow.query.filter_by(kind='message').order_by(Workflow.id.desc()).all())

    def csv_response(headers,rows,name):
        stream=io.StringIO();writer=csv.writer(stream);writer.writerow(headers)
        for row in rows:
            writer.writerow(["'"+str(x) if str(x).lstrip().startswith(('=','+','-','@')) else str(x) for x in row])
        response=app.response_class('\ufeff'+stream.getvalue(),mimetype='text/csv');response.headers['Content-Disposition']='attachment; filename="schoolflow-'+name+'.csv"';return response

    @bp.route('/installment/<int:bill_id>',methods=['GET','POST'])
    def installment(bill_id):
        b=db.get_or_404(Bill,bill_id)
        if request.method=='POST':
            if b.frozen or b.paid or b.discount: raise ValueError('Only unpaid, undiscounted, unfrozen challans can be split in this pre-test build.')
            m=month(request.form.get('month'));due=day(request.form.get('due'))
            lines=[];left=[]
            for i,line in enumerate(b.lines):
                value=money(request.form.get('amount_'+str(i)))
                if value>line['amount']: raise ValueError('Installment cannot exceed the particular amount.')
                if value: lines.append(dict(particular=line['particular'],amount=value))
                if line['amount']-value: left.append(dict(particular=line['particular'],amount=line['amount']-value))
            if not lines: raise ValueError('Enter an installment amount.')
            b.lines=left
            db.session.add(Bill(student_id=b.student_id,month=m,due=due,lines=lines,notes=request.form.get('notes','')[:5000],source='installment:'+str(b.id)+':'+secrets.token_urlsafe(12)))
            audit('Create installment',bill=b.id,amount=sum(x['amount'] for x in lines));commit();flash('Installment created. Total debt is unchanged.','success');return redirect(url_for('ops.fees',mode='payments'))
        return render('installment.html',title='Create Installment',bill=b,student=db.session.get(Student,b.student_id))

    @bp.route('/direct-payment',methods=['GET','POST'])
    @bp.route('/family-payment',methods=['GET','POST'])
    def batch_payment():
        family_mode=request.path.endswith('family-payment');rows=[]
        query=request.values.get('number','').strip();lookup=request.values.get('lookup','sid')
        if query:
            if family_mode:
                ids=[p.id for p in Student.query.all() if str(details(p).get('family_no',''))==query]
                rows=Bill.query.filter(Bill.student_id.in_(ids)).order_by(Bill.month,Bill.id).all()
            elif lookup=='challan':
                if not query.isdigit(): raise ValueError('Enter a numeric challan number.')
                b=db.session.get(Bill,int(query));rows=[b] if b else []
            else:
                students=[p for p in Student.query.all() if str(p.id)==query] if lookup=='sid' else [p for p in Student.query.all() if str(details(p).get('roll_no',''))==query]
                rows=Bill.query.filter(Bill.student_id.in_([p.id for p in students])).order_by(Bill.month,Bill.id).all()
            rows=[b for b in rows if b.remaining>0]
        if request.method=='POST':
            token=request.form.get('token','')
            if not re.fullmatch(r'[a-zA-Z0-9_-]{20,100}',token): raise ValueError('Reload payment form.')
            if Receipt.query.filter(Receipt.token.like(token+':%')).first(): raise ValueError('Already submitted.')
            d=day(request.form.get('paid_date'));account=request.form.get('account','').strip()
            if not account: raise ValueError('Receiving account is required.')
            saved=[]
            for b in Bill.query.filter(Bill.id.in_([b.id for b in rows])).with_for_update().all():
                value=money(request.form.get('amount_'+str(b.id)))
                if not value: continue
                if b.frozen or value>b.remaining: raise ValueError('Unfreeze challans and enter amounts no greater than the balance.')
                b.paid+=value;db.session.add(Receipt(student_id=b.student_id,bill_id=b.id,amount=value,discount=0,day=d,account=account,token=token+':'+str(b.id)));saved.append(b.student_id)
            if not saved: raise ValueError('Enter at least one payment amount.')
            if request.form.get('action')=='send': queue('Fee receipt',list(set(saved)))
            audit('Family payment' if family_mode else 'Direct payment',students=saved);commit();flash('Payments saved.','success');return redirect(url_for('ops.history'))
        return render('batch_payment.html',title='Family-wise Payment' if family_mode else 'Direct Payment',family_mode=family_mode,number=query,lookup=lookup,rows=rows,student=lambda id:db.session.get(Student,id),token=secrets.token_urlsafe(24))

    @bp.route('/setup-demo',methods=['POST'])
    def setup_demo():
        from record_schema import DEMO_CHOICES
        for category,values in DEMO_CHOICES.items():
            for value in values:
                if not rm['settings'].query.filter_by(category=category,value=value,class_name='').first():
                    db.session.add(rm['settings'](category=category,value=value,class_name=''))
        for value in ['Math','English','Science']:
            if not rm['settings'].query.filter_by(category='subject',value=value,class_name='Demo Class').first():
                db.session.add(rm['settings'](category='subject',value=value,class_name='Demo Class'))
        commit();flash('Fictional test dropdown choices configured. You can now add students and employees.','success')
        return redirect(url_for('records.new_record',kind='student'))

    @bp.route('/legacy-data')
    def legacy_data():
        from app import Attendance,ExamResult
        return render('legacy_data.html',title='Starter Attendance / Exam Records',attendance=Attendance.query.order_by(Attendance.id.desc()).all(),results=ExamResult.query.order_by(ExamResult.id.desc()).all())

    @bp.route('/readiness')
    def readiness(): return render('readiness.html',title='Pre-test Build Status')

    def dashboard_data():
        students=Student.query.all();employees=Employee.query.all();bills=Bill.query.all();receipts=Receipt.query.filter_by(voided=False).all();today=date.today();m=today.strftime('%Y-%m')
        present=Daily.query.filter_by(kind='student',day=today,status='Present').count();marked=Daily.query.filter_by(kind='student',day=today).count()
        scores=Score.query.filter(Score.obtained!=None).all();average=round(sum(s.obtained/db.session.get(Workflow,s.award_id).data['papers'][s.paper]['total']*100 for s in scores)/len(scores),1) if scores else 0
        return dict(students=len(students),active=sum(s.status=='Active' for s in students),employees=len(employees),active_employees=sum(s.status=='Active' for s in employees),present=present,marked=marked,attendance=Counter(x.status for x in Daily.query.filter_by(kind='student',day=today).all()),collected=sum(r.amount for r in receipts),this_month=sum(r.amount for r in receipts if str(r.day)[:7]==m),due=sum(b.remaining for b in bills),discount=sum(r.discount for r in receipts),unpaid=sum(b.remaining>0 for b in bills),defaulters=len({b.student_id for b in bills if b.remaining>0}),pending=Workflow.query.filter_by(status='Pending').count(),average=average,queries=Workflow.query.filter_by(kind='queries').count(),staff_counts=Counter(x.status for x in Daily.query.filter(Daily.kind=='staff',Daily.day>=today.replace(day=1)).all()),classes=Counter(s.class_name or 'Unassigned' for s in students if s.status=='Active'),months=[(f'{today.year}-{i:02d}',sum(b.total for b in bills if b.month==f'{today.year}-{i:02d}'),sum(r.amount for r in receipts if db.session.get(Bill,r.bill_id).month==f'{today.year}-{i:02d}')) for i in range(1,today.month+1)])

    @bp.route('/dashboard')
    def dashboard(): return render('dashboard.html',title='Dashboard',stats=dashboard_data())

    @app.route('/healthz')
    def health():
        db.session.execute(db.text('SELECT 1'));return jsonify(status='ok',build='schoolflow-pretest-v3')

    @app.route('/api/v1/summary')
    def summary_api():
        key=app.config.get('SCHOOLFLOW_API_TOKEN')
        if not key: return jsonify(error='API access is not configured'),503
        if not hmac.compare_digest(request.headers.get('Authorization',''),'Bearer '+key): abort(401)
        # Owner-only aggregate foundation. No unrestricted pupil/employee endpoint.
        return jsonify(dashboard_data())

    app.register_blueprint(bp)
    app.extensions['operation_helpers']=dict(details=details,dashboard=dashboard_data)
