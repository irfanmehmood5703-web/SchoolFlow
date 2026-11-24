"""SchoolFlow pre-test workflows. Amounts use integer paisa; no external messages are sent."""
import calendar, csv, hmac, io, json, re, secrets, hashlib
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from school_clock import school_today
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from flask import Blueprint, abort, flash, g, jsonify, redirect, render_template, request, session, url_for, has_request_context, send_file, make_response
from sqlalchemy import case
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import StaleDataError
from student_performance_schema import PERFORMANCE_CATEGORIES
from payroll_calendar import joining_pay, all_present_bonus
from module_catalog import MENUS, TITLES, SCHEMAS, STATUSES
from itsdangerous import BadData,URLSafeTimedSerializer
from exam_enrollment import enrolled
from payroll_rules import parse_rule,deduction,JUMP_MODES,CAP_MODES


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

    class QualitativeScore(db.Model):
        id = db.Column(db.Integer, primary_key=True)
        award_id = db.Column(db.Integer, db.ForeignKey('workflow.id'), nullable=False)
        student_id = db.Column(db.Integer, db.ForeignKey('student.id'), nullable=False)
        paper = db.Column(db.Integer, nullable=False)
        value = db.Column(db.String(60))
        state = db.Column(db.String(2), default='')
        remarks = db.Column(db.String(1000), default='')
        version = db.Column(db.Integer, nullable=False, default=1)
        __mapper_args__ = {'version_id_col': version}
        __table_args__ = (db.UniqueConstraint('award_id','student_id','paper'),)

    class ExamMarksSave(db.Model):
        nonce=db.Column(db.String(32),primary_key=True)
        award_id=db.Column(db.Integer,db.ForeignKey('workflow.id'),nullable=False)
        created=db.Column(db.DateTime,nullable=False,default=lambda:datetime.now(timezone.utc))

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

    class SalaryIncrementRequest(db.Model):
        token=db.Column(db.String(100),primary_key=True)
        workflow_id=db.Column(db.Integer,db.ForeignKey('workflow.id'),nullable=False,unique=True)

    app.extensions['ops_models'] = dict(workflow=Workflow,bill=Bill,receipt=Receipt,daily=Daily,score=Score,qualitative=QualitativeScore,salary=Salary,audit=Audit)
    app.extensions['exam_marks_save_model']=ExamMarksSave
    app.extensions['salary_increment_request_model']=SalaryIncrementRequest
    app.jinja_env.filters['cash'] = lambda x: f'{(x or 0)/100:,.2f}'.rstrip('0').rstrip('.')
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
        # Scope-sensitive, request-local only: saved rows reuse the same choices
        # rather than reloading every employee/catalog for every cell.
        allowed=getattr(g,'access_campuses',None) if has_request_context() else None
        key=(kind,None if allowed is None else tuple(sorted(allowed)))
        cache=request.environ.setdefault('schoolflow.choice_cache',{}) if has_request_context() else {}
        if key in cache:return list(cache[key])
        if kind in ('employee','teacher','student'):
            cls=Student if kind=='student' else Employee
            values=[(str(x.id),x.name) for x in cls.query.order_by(cls.name).all() if kind!='teacher' or 'teacher' in (x.role or '').lower()]
        else:
            values=[(x.value,x.value) for x in rm['settings'].query.filter_by(category=kind).order_by(rm['settings'].value).all()]
            if kind=='subject' and app.extensions.get('school_settings_helpers'):
                order={r.name:i for i,r in enumerate(app.extensions['school_settings_helpers']['items']('subject'))}
                values.sort(key=lambda item:(order.get(item[0],1000000),item[0]))
        cache[key]=tuple(values)
        return values
    def people(kind='student', active=True):
        cls=Student if kind=='student' else Employee
        detail=rm['student' if kind=='student' else 'employee']
        owner=detail.student_id if kind=='student' else detail.employee_id
        query=cls.query.outerjoin(detail,owner==cls.id)
        if active:query=query.filter(cls.status=='Active')
        for key in ('campus','class_name','section','academic_session'):
            value=request.values.get(key,'')
            if value:
                column=Student.class_name if key=='class_name' and kind=='student' else detail.data[key].as_string()
                query=query.filter(column==value)
        return query.order_by(cls.id).all()
    def selected(name='ids'):
        try: return list(dict.fromkeys(int(x) for x in request.form.getlist(name)))
        except ValueError: raise ValueError('Invalid selection.')
    def queue(subject, ids, audience='parent', event=None, context=None):
        prefs={k: request.form.get(k)=='on' for k in ['father_contact','mother_contact','student_contact','app_sms','branded_sms','whatsapp_sms','parent_notification','teacher_notification']}
        snapshots=app.extensions['school_settings_helpers']['message_snapshots'](subject,ids,audience,event=event,context=context)
        school_identity=getattr(g,'school_identity',None) or {}
        profile_model=app.extensions.get('school_profile_model')
        profile=db.session.get(profile_model,1) if profile_model else None
        school_name=str(((profile.data or {}).get('name') if profile else '') or school_identity.get('name') or '').strip()
        if school_name:
            for item in snapshots:
                item['text']=re.sub(r'\\{\\s*school_name\\s*\\}',lambda match:school_name,str(item.get('text') or ''),flags=re.IGNORECASE)
                if item.get('unresolved'):
                    item['unresolved']=[tag for tag in item['unresolved'] if str(tag).strip('{} ').lower()!='school_name']
        db.session.add(Workflow(kind='message',status='Provider not configured',data=dict(subject=subject,ids=ids,audience=audience,preferences=prefs,messages=snapshots)))
    def render(name, **kw):
        return render_template(name, choices=choices, today=school_today().isoformat(), statuses=app.extensions.get('attendance_control_helpers',{}).get('statuses',lambda k:STATUSES)(kw.get('kind','student')), **kw)

    @app.context_processor
    def nav_context():
        # Only open, dated admission inquiries need reminders; the school's
        # scoped Workflow query prevents mixing one institute with another.
        due_queries=[]
        if session.get('school_code') or session.get('institute_code') or session.get('owner_id') or session.get('staff_id'):
            today=school_today().isoformat()
            due_queries=[w for w in Workflow.query.filter_by(kind='queries').all()
                         if w.status not in ('Voided','Converted','Closed')
                         and (w.data or {}).get('follow_up')
                         and (w.data or {})['follow_up']<=today]
        return dict(module_menus=MENUS,menu_url=menu_url,
                    admission_followup_due=due_queries,
                    build_label='Pre-test • fictional records only')

    @bp.before_request
    def csrf():
        if request.method=='POST':
            token=request.form.get('_csrf','')
            if not token or not hmac.compare_digest(token,session.get('record_csrf','')): abort(400,'Form session expired. Reload the page.')
            if request.endpoint in ('ops.pay','ops.batch_payment','ops.reverse_receipts'):app.extensions['admission_capacity']['lock']()

    @bp.errorhandler(ValueError)
    def invalid(exc):
        db.session.rollback()
        return render('operation_error.html',title='Please check this operation',error=str(exc)),422

    def menu_url(key):
        if key in ('general-library','general-leaves','general-feedback'):return url_for('general_portal.index',section=key.removeprefix('general-'))
        if key in ('app-links','widgets'):return url_for('general_tools.app_links' if key=='app-links' else 'general_tools.widgets')
        if key=='parents-app':return url_for('parents.analytics')
        if key=='ptm-events':return url_for('ptm.events')
        if key in ('student-notices','student-diary'):return url_for('student_extras.index',kind='notices' if key=='student-notices' else 'diary')
        if key=='finance-fee-audit':return url_for('finance_audit.fees')
        if key=='finance-voided-challans':return url_for('finance_audit.challans')
        if key=='finance-voided':return url_for('finance_reports.general').replace('/general','/voided')
        if key=='finance-snapshots':return url_for('daily_snapshots.index')
        if key.startswith('req-'):return url_for('requisitions.'+key.removeprefix('req-'))
        if key.startswith('ledger-'):
            mode=key.removeprefix('ledger-')
            return url_for('ledger.entry',kind=mode) if mode in ('journal','expense','income') else url_for('ledger.report',mode='ledger' if mode=='home' else mode)
        if key in ('finance-cash','finance-shareholders'):
            return url_for('finance_partners.cash' if key=='finance-cash' else 'finance_partners.partners')
        if key in ('finance-journal-inquiry','finance-general-ledger','finance-daily-profit'):
            return url_for('finance_reports.'+{'finance-journal-inquiry':'journals','finance-general-ledger':'general','finance-daily-profit':'daily'}[key])
        if key.startswith('finance-'):
            return url_for('finance.chart') if key=='finance-chart' else url_for('finance.index',kind=key.removeprefix('finance-'))
        if key in ('students','employees'): return url_for('records.record_list',kind='student' if key=='students' else 'employee')
        if key in ('challans','payments','inactive-fees','paid-challans','discount-challans'): return url_for('ops.fees',mode=key)
        if key=='certificates': return url_for('certificates.index')
        if key=='fee-plans': return url_for('student_plans.index')
        if key=='payment-history': return url_for('ops.history')
        if key in ('student-fees','fee-report','daily-fees','class-fees','defaulters','family-defaulters','monthly-defaulters','fee-reminder','fee-sheet'): return url_for('reports.fees',view=key)
        if key in ('student-attendance','staff-attendance'): return url_for('ops.take_attendance',kind='staff' if key.startswith('staff') else 'student')
        if key in ('combined-attendance','daily-attendance','individual-attendance','attendance-summary','absentees','attendance-sheet','staff-attendance-report'): return url_for('reports.attendance',view=key)
        if key in ('salary-plans','update-salary'): return url_for('ops.plans')
        if key=='lecture-delivery': return url_for('hrm_reports.lecture_delivery')
        if key in ('salary-report','lecture-report'): return url_for('hrm_reports.report',view=key)
        if key in ('generate-salary','pay-salary'): return url_for('ops.payroll',view=key)
        if key in ('date-sheets','awards'): return url_for('ops.examination',kind=key)
        if key=='roll-slips': return url_for('ops.rolls')
        if key=='shifts':return url_for('school_settings.assign_shifts')
        if key in SCHEMAS: return url_for('ops.register',kind=key)
        if key=='sms-blaster': return url_for('ops.messages')
        if key=='fee-intimation': return url_for('ops.fee_intimation')
        if key in ('sms-report','family-sms','notifications','staff-sms'): return url_for('ops.message_log',view=key)
        if key=='admission-approvals':
            return url_for('admission_limits.approvals')
        if key=='salary-approvals': return url_for('ops.plans')
        if key=='teacher-performance': return url_for('reports.teacher_performance')
        if key=='student-360': return url_for('student_overview.index')
        return url_for('ops.entry',key=key)

    app.extensions['workspace_menu_url'] = menu_url

    @bp.route('/<key>')
    def entry(key):
        target=menu_url(key)
        if target!=url_for('ops.entry',key=key):return redirect(target)
        return render('reference_pending.html',title=TITLES.get(key,key),key=key)

    @bp.route('/register/<kind>',methods=['GET','POST'])
    def register(kind):
        if kind not in SCHEMAS: abort(404)
        if kind=='fee-plans':
            if request.method=='POST':raise ValueError('Configure fee schedules in Core Settings → Fee Settings.')
            return redirect(url_for('fee_setup.schedules'))
        if kind=='shifts':return redirect(url_for('school_settings.assign_shifts'),code=307 if request.method=='POST' else 302)
        schema=SCHEMAS[kind]
        query_extra_fields=('mother_name','mother_phone','guardian_name','guardian_relation','alternate_phone','gender','date_of_birth','address','previous_school','visitor_name','source','remarks','section','session')
        def query_extras():
            extras={}
            for key in query_extra_fields:
                value=request.form.get(key,'').strip()
                if len(value)>500:raise ValueError('Inquiry detail is too long.')
                if key=='date_of_birth' and value:day(value)
                extras[key]=value
            return extras
        if kind=='queries' and request.method=='POST' and request.form.get('action')=='prepare_admission':
            row=Workflow.query.filter_by(id=request.form.get('query_id',type=int),kind='queries').with_for_update().first_or_404()
            if row.status in ('Voided','Closed'):raise ValueError('This inquiry is not eligible for admission.')
            if row.data.get('student_id'):raise ValueError('This inquiry is already linked to a student.')
            if not row.data.get('name') or not row.data.get('phone'):raise ValueError('Complete student name and guardian contact first.')
            note=request.form.get('admission_note','').strip()
            if len(note)>1000:raise ValueError('Admission note is too long.')
            admission_date=day(request.form.get('admission_date',''))
            data=dict(row.data or {})
            data['admission_prepared_date']=admission_date.isoformat()
            data['admission_note']=note
            data['admission_prepared']=True
            row.data=data
            audit('Prepare admission from inquiry',query_id=row.id,date=admission_date.isoformat())
            commit()
            flash('Inquiry marked ready. Complete the official student admission form to create the student safely.','success')
            return redirect(url_for('ops.register',kind='queries'))
        if kind=='queries' and request.method=='POST' and request.form.get('action')=='restore_query':
            query_id=request.form.get('query_id',type=int)
            if not query_id:raise ValueError('Choose an archived inquiry to restore.')
            target=Workflow.query.filter_by(id=query_id,kind='queries',status='Voided').with_for_update().first_or_404()
            data=dict(target.data or {})
            previous=data.get('archived_previous_status','Active')
            if previous not in ('Active','Follow-up','Converted','Closed'):previous='Active'
            # An inquiry linked to a student must never be reopened as an unconverted lead.
            if data.get('student_id'):previous='Converted'
            target.status=previous
            history=list(data.get('status_history') or [])
            history.append(dict(previous='Voided',status=previous,fields={},date=school_today().isoformat(),reason='Restored archived inquiry'))
            data['status_history']=history[-100:]
            data['restored_from_archive']=school_today().isoformat()
            target.data=data
            audit('Restore archived admission inquiry',query_id=target.id,status=previous)
            commit()
            flash('Archived admission inquiry restored successfully.','success')
            return redirect(url_for('ops.register',kind='queries'))
        if kind=='queries' and request.method=='POST' and request.form.get('action') in ('bulk_query','delete_query','followup_query'):
            action=request.form['action']
            ids=selected() if action=='bulk_query' else [request.form.get('query_id',type=int)]
            if not ids or any(not x for x in ids) or len(ids)>200:raise ValueError('Select between 1 and 200 inquiries.')
            targets=Workflow.query.filter(Workflow.id.in_(ids),Workflow.kind=='queries',Workflow.status!='Voided').with_for_update().all()
            if len(targets)!=len(ids):raise ValueError('An inquiry was not found or was already deleted.')
            if action=='bulk_query':
                status=request.form.get('query_status','')
                fields={}
                for key in ('class_name','follow_up','notes'):
                    if request.form.get('change_'+key)=='on':
                        value=request.form.get('bulk_'+key,'').strip()
                        if key=='class_name' and value not in dict(choices('class_name')):raise ValueError('Select a configured class.')
                        if key=='follow_up':day(value)
                        if len(value)>1000:raise ValueError('Bulk field is too long.')
                        fields[key]=value
                notes_mode=request.form.get('bulk_notes_mode','replace')
                if 'notes' in fields and notes_mode not in ('replace','append'):raise ValueError('Choose a valid notes update mode.')
                if status and status not in ('Active','Follow-up','Converted','Closed'):raise ValueError('Choose a valid status.')
                if not status and not fields:raise ValueError('Select a status or at least one field to update.')
                reason=request.form.get('reason','').strip()
                if not 1<=len(reason)<=1000:raise ValueError('Provide a reason (up to 1,000 characters).')
                effective=day(request.form.get('effective_date',''))
                for target in targets:
                    previous=target.status
                    if status:
                        if (target.data or {}).get('student_id') and status!='Converted':raise ValueError('An enrolled student must remain Converted. Do not change the admission status.')
                        target.status=status
                    data=dict(target.data or {})
                    updated_fields=dict(fields)
                    if 'notes' in updated_fields and notes_mode=='append':
                        existing=str(data.get('notes') or '').strip()
                        addition=updated_fields['notes'].strip()
                        if not addition:raise ValueError('Enter a note to add.')
                        combined=(existing+'\n'+addition) if existing else addition
                        if len(combined)>1000:raise ValueError('Combined notes exceed 1,000 characters. Shorten the new note or use Replace Notes.')
                        updated_fields['notes']=combined
                    data.update(updated_fields)
                    history=list(data.get('status_history',[]))
                    history.append(dict(previous=previous,status=status or previous,fields=updated_fields,date=effective.isoformat(),reason=reason,notes_mode=notes_mode if 'notes' in updated_fields else None))
                    data['status_history']=history[-100:]
                    target.data=data
                    audit('Bulk admission inquiry status',query_id=target.id,previous=previous,status=status,reason=reason)
            elif action=='delete_query':
                target=targets[0]
                previous=target.status
                data=dict(target.data or {})
                data['archived_previous_status']=previous
                data['archived_on']=school_today().isoformat()
                target.data=data
                target.status='Voided'
                audit('Void admission inquiry',query_id=target.id,previous_status=previous)
            else:
                target=targets[0]
                follow=day(request.form.get('follow_up',''))
                note=request.form.get('followup_note','').strip()
                call_result=request.form.get('call_result','Call Completed').strip()
                allowed_results=('Call Pending','Call Completed','No Answer','Call Back Later')
                if call_result not in allowed_results:raise ValueError('Select a valid call result.')
                if not 1<=len(note)<=1000:raise ValueError('Add a follow-up note (up to 1,000 characters).')
                data=dict(target.data or {})
                history=list(data.get('followup_history',[]))
                history.append(dict(date=school_today().isoformat(),next_date=follow.isoformat(),note=note,call_result=call_result))
                data['followup_history']=history[-100:]
                data['call_result']=call_result
                data['follow_up']=follow.isoformat()
                target.data=data
                if target.status not in ('Converted','Closed'):target.status='Follow-up'
                audit('Admission inquiry follow-up',query_id=target.id,next_date=follow.isoformat())
            commit()
            flash('Admission inquiry changes saved.','success')
            return redirect(url_for('ops.register',kind='queries'))
        if kind=='queries' and request.method=='POST' and request.form.get('action')=='update_query':
            row=Workflow.query.filter_by(id=request.form.get('query_id',type=int),kind='queries').with_for_update().first_or_404()
            if row.status=='Voided': raise ValueError('This inquiry is no longer active.')
            data={}
            for key,label,typ,required in schema:
                value=request.form.get(key,'').strip()
                if required and not value: raise ValueError(label+' is required.')
                if len(value)>5000: raise ValueError(label+' is too long.')
                if value and typ=='date': day(value)
                if typ in ('campus','class_name','section','subject') and value and value not in dict(choices(typ)): raise ValueError('Choose a configured '+label+'.')
                data[key]=value
            status=request.form.get('query_status','Active')
            if status not in ('Active','Follow-up','Converted','Closed'): raise ValueError('Invalid inquiry status.')
            if (row.data or {}).get('student_id') and status!='Converted':raise ValueError('This inquiry already created a student. Its status must remain Converted.')
            before=dict(row.data)
            data.update(query_extras())
            data['sms_consent']=request.form.get('sms_consent')=='on'
            data['followup_history']=list(row.data.get('followup_history',[]))
            data['status_history']=list(row.data.get('status_history',[]))
            # Preserve immutable conversion linkage when editing public inquiry fields.
            for key in ('student_id','admission_no','converted_date'):
                if key in before:data[key]=before[key]
            row.data=data
            row.status=status
            audit('Update admission inquiry',query_id=row.id,before=before,after=data,status=status)
            commit()
            flash('Admission inquiry updated.','success')
            return redirect(url_for('ops.register',kind='queries'))
        if request.method=='POST' and not (kind=='auto-reminders' and request.form.get('action')=='preview_reminders'):
            action=request.form.get('action','save')
            if action in ('approve','reject','delete'):
                if kind not in ('increments','advances','leave-approvals','lecture-register'): raise ValueError('This record type does not use approval actions.')
                rows=Workflow.query.filter(Workflow.id.in_(selected()),Workflow.kind==kind).with_for_update().all()
                if not rows: raise ValueError('Select at least one record.')
                if kind=='lecture-register':
                    used={line['id'] for salary in Salary.query.all() for line in salary.detail.get('lecture_details',[])}
                    if any(x.id in used for x in rows):raise ValueError('A selected lecture is already captured in a salary. Its source cannot be changed.')
                if kind=='increments' and action in ('reject','delete'):
                    used={row['id'] for salary in Salary.query.all() for row in salary.detail.get('manual_increments',[])}
                    if any(x.id in used for x in rows):raise ValueError('A selected increment is already captured in a salary. Its saved source cannot be cancelled.')
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
                    if typ in ('campus','class_name','section','subject') and value and value not in dict(choices(typ)):raise ValueError('Choose a configured '+label+'.')
                    data[key]=bool(value) if typ=='checkbox' else value
                if data.get('from_date') and data.get('to_date') and data['from_date']>data['to_date']: raise ValueError('End date must follow start date.')
                if kind=='fee-plans' and not 1<=int(data['due_day'])<=28: raise ValueError('Due day must be between 1 and 28 for this pre-test build.')
                if kind=='auto-reminders' and not 1<=int(data['day'])<=31:raise ValueError('Reminder day must be 1–31.')
                if kind=='advances' and (money(data['amount'])==0 or money(data['return_amount'])==0 or money(data['return_amount'])>money(data['amount'])): raise ValueError('Monthly return must be positive and no greater than the advance.')
                if kind=='increments' and not money(data['amount']):raise ValueError('Enter a positive manual salary increment amount.')
                if kind=='increments':
                    token=request.form.get('increment_token','')
                    if not re.fullmatch(r'[A-Za-z0-9_-]{20,100}',token):raise ValueError('Reload the increment form before saving.')
                    previous=db.session.get(SalaryIncrementRequest,token)
                    if previous:
                        if db.session.get(Workflow,previous.workflow_id).data!=data:raise ValueError('This increment submission was already used with different details. Reload the form.')
                        flash('This increment was already saved. No duplicate was created.','success')
                        return redirect(url_for('ops.register',kind=kind))
                state='Pending' if kind in ('increments','advances','leave-approvals') else 'Active'
                if kind=='lecture-register':
                    state='Approved' if data.get('approve') else 'Pending'
                    if not int(data['lectures']): raise ValueError('Lectures must be positive.')
                obj=Workflow(kind=kind,data=data,status=state);db.session.add(obj)
                if kind=='queries':
                    data.update(query_extras())
                    data['sms_consent']=request.form.get('sms_consent')=='on'
                    db.session.flush()
                    # Admission inquiries never send SMS automatically.
                    # Messages require an explicit operator submission.
                if kind=='increments':
                    db.session.flush();db.session.add(SalaryIncrementRequest(token=token,workflow_id=obj.id))
                audit('Create '+kind);commit()
                flash('Record saved.','success')
            return redirect(url_for('ops.register',kind=kind))
        rows=Workflow.query.filter_by(kind=kind).filter(Workflow.status!='Voided').order_by(Workflow.id.desc()).all()
        if kind=='queries':
            # Repair earlier follow-up updates that changed already-enrolled
            # inquiries back to Follow-up, so converted reporting stays accurate.
            repaired=0
            conversion_audits=Audit.query.filter_by(action='Update admission inquiry').order_by(Audit.id.desc()).all()
            for inquiry in rows:
                if inquiry.status=='Voided':continue
                details=dict(inquiry.data or {})
                # A previous edit could discard the student_id. Recover only from
                # an explicit prior audit snapshot, never by guessing from names.
                if not details.get('student_id'):
                    for log in conversion_audits:
                        payload=log.data or {}
                        prior=payload.get('before') or {}
                        if str(payload.get('query_id'))!=str(inquiry.id) or not isinstance(prior,dict):continue
                        sid=prior.get('student_id')
                        student=db.session.get(Student,int(sid)) if str(sid).isdigit() else None
                        if student:
                            for key in ('student_id','admission_no','converted_date'):
                                if prior.get(key) is not None:details[key]=prior[key]
                            inquiry.data=details
                            repaired+=1
                            break
                if details.get('student_id') and inquiry.status!='Converted':
                    inquiry.status='Converted'
                    audit('Restore converted admission inquiry status',query_id=inquiry.id,student_id=details['student_id'])
                    repaired+=1
            if repaired:commit()
            q=request.args.get('q','').strip().casefold()
            status=request.args.get('status','').strip()
            if q:rows=[r for r in rows if q in ' '.join(str(r.data.get(k,'')) for k in ('name','father','phone','class_name')).casefold()]
            if status:rows=[r for r in rows if r.status==status]
            followup=request.args.get('followup','')
            if followup in ('due','upcoming','today'):
                now=school_today().isoformat()
                rows=[r for r in rows if r.status not in ('Closed','Converted') and r.data.get('follow_up') and (r.data['follow_up']<=now if followup=='due' else r.data['follow_up']>now if followup=='upcoming' else r.data['follow_up']==now)]
        reminder_students=[]
        reminder_message='Dear Parent, your child {student_name} has an outstanding fee of Rs. {remaining_fee} for {fee_month}. Kindly clear the dues. Thank you. {school_name}'
        reminder_previews=[]
        if kind=='auto-reminders':
            # Always compute the audience from the current tenant's live bills; no cached or cross-school recipient list.
            balances=defaultdict(int)
            bill_months={}
            for bill in Bill.query.all():
                if bill.remaining>0:
                    balances[bill.student_id]+=bill.remaining
                    if bill.student_id not in bill_months or bill.month<bill_months[bill.student_id]:
                        bill_months[bill.student_id]=bill.month
            details_model=rm['student']
            details_by_id={d.student_id:(d.data or {}) for d in details_model.query.filter(details_model.student_id.in_(list(balances))).all()} if balances else {}
            for student in Student.query.filter(Student.id.in_(list(balances))).order_by(Student.name).all() if balances else []:
                if student.status!='Active':continue
                details=details_by_id.get(student.id,{})
                phone=next((str(details.get(k) or '').strip() for k in ('father_phone','guardian_phone','parent_phone','phone','mobile','contact','father_mobile') if details.get(k)), '')
                reminder_students.append(dict(id=student.id,name=student.name,student_class=student.class_name or '',father=str(details.get('father_name') or details.get('father') or ''),phone=phone,remaining=balances[student.id],fee_month=bill_months.get(student.id,'')))
            if request.method=='POST' and request.form.get('action')=='preview_reminders':
                selected_ids=set()
                for raw in request.form.getlist('reminder_student_ids'):
                    if not raw.isdigit():raise ValueError('Invalid student selection.')
                    selected_ids.add(int(raw))
                if not selected_ids:raise ValueError('Select at least one student with outstanding fees.')
                reminder_message=request.form.get('reminder_message','').strip()
                if not reminder_message or len(reminder_message)>1000:raise ValueError('Enter a reminder message up to 1000 characters.')
                profile_model=app.extensions.get('institute_setup_models',{}).get('profile')
                school_profile=(db.session.get(profile_model,1).data or {}) if profile_model and db.session.get(profile_model,1) else {}
                school_identity=getattr(g,'school_identity',None) or {}
                school_name=str(school_profile.get('name') or school_identity.get('name') or 'School').strip()
                for student in reminder_students:
                    if student['id'] not in selected_ids:continue
                    msg=reminder_message
                    for key,value in {'student_name':student['name'],'father_name':student['father'],'remaining_fee':f"{student['remaining']/100:,.2f}".rstrip('0').rstrip('.'),'fee_month':student['fee_month'],'school_name':school_name}.items():
                        msg=msg.replace('{'+key+'}',str(value))
                    reminder_previews.append(dict(student=student,message=msg))
                if not reminder_previews:raise ValueError('Selected students no longer have outstanding fees.')
        archived_rows=Workflow.query.filter_by(kind='queries',status='Voided').order_by(Workflow.id.desc()).all() if kind=='queries' else []
        return render('register.html',title=TITLES[kind],kind=kind,schema=schema,rows=rows,archived_rows=archived_rows,increment_token=secrets.token_urlsafe(24),reminder_students=reminder_students,reminder_message=reminder_message,reminder_previews=reminder_previews,sms_devices=(app.extensions['sms_models']['device'].query.filter_by(active=True).all() if kind in ('queries','auto-reminders') and app.extensions.get('sms_models') else []))

    @bp.route('/approve-students',methods=['POST'])
    def approve_students():
        return app.extensions['admission_capacity']['review']()

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
        status_students = []
        if mode == 'inactive-fees':
            student_q = request.args.get('student_q', '').strip()[:120]
            query = Student.query
            if student_q:
                pattern = '%' + student_q.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
                from sqlalchemy import or_
                query = query.filter(or_(Student.name.ilike(pattern, escape='\\'), Student.admission_no.ilike(pattern, escape='\\'), Student.phone.ilike(pattern, escape='\\')))
            status_students = query.order_by(Student.id.desc()).limit(100).all()
        return render('fees.html',title={'inactive-fees':'Inactive Student Fee & Status Management','paid-challans':'Paid Challans','discount-challans':'Challan Discounts'}.get(mode,'Pay or Print Fee Challans'),rows=rows,mode=mode,receipts=receipts,student=lambda id:db.session.get(Student,id),details=details,status_students=status_students)

    @bp.route('/generate-challans',methods=['GET','POST'])
    def generate_challans():
        if request.method=='GET':return redirect(url_for('student_plans.generate'))
        app.extensions['admission_capacity']['lock']()
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
                helper=app.extensions['fee_setup_helpers'];data=details(s)
                if (p.data.get('campus') and p.data['campus']!=data.get('campus')) or (p.data.get('class_name') and p.data['class_name']!=s.class_name):raise ValueError('Choose a schedule for the student campus and class.')
                if helper['scoped_schedule'](s,p.data['name']):raise ValueError('Assign this configured schedule to the student, then generate from Student Fee Plans.')
                rule=helper['effective_rule'](p.data['particular'])
                if not helper['eligible'](rule,m,not Bill.query.filter_by(student_id=id).first(),True):continue
                source=f'plan:{p.id}:student:{id}:month:{m}'
                if Bill.query.filter_by(source=source).first(): continue
                db.session.add(Bill(student_id=id,month=m,due=day(m+'-'+str(p.data['due_day']).zfill(2)),lines=[{'particular':p.data['particular'],'display_name':rule['label'],'amount':amount,'billing_rule':rule}],source=source));created+=1
            audit('Generate challans',count=created,month=m);commit();flash(f'{created} challans generated; duplicates skipped.','success')
            return redirect(url_for('ops.fees',mode='payments'))
        return render('generate_fees.html',title='Generate Fee Challans',plans=plans,students=people(active=False))

    def payment_particulars(b):
        """Allocate historical receipts deterministically; preserve new per-line allocations."""
        remaining=[int(line['amount']) for line in b.lines]
        receipts=Receipt.query.filter_by(bill_id=b.id,voided=False).order_by(Receipt.id).all()
        for receipt in receipts:
            allocation=None
            if (receipt.notes or '').startswith('[SF-LINES]'):
                try:
                    allocation=json.loads(receipt.notes.split('\n',1)[0][10:])
                except (ValueError,TypeError): allocation=None
            if isinstance(allocation,list) and len(allocation)==len(remaining) and all(isinstance(x,list) and len(x)==2 and all(isinstance(v,int) and v>=0 for v in x) for x in allocation) and sum(x[0] for x in allocation)==receipt.amount and sum(x[1] for x in allocation)==receipt.discount:
                for i,(paid,discount) in enumerate(allocation): remaining[i]-=paid+discount
            else:
                # Old receipts did not record particulars. Display a stable estimate.
                old=receipt.amount+receipt.discount
                for i in range(len(remaining)):
                    applied=min(max(0,remaining[i]),old)
                    remaining[i]-=applied;old-=applied
        if sum(remaining)!=b.remaining or any(v<0 for v in remaining):
            # Legacy records can have no receipts; never overstate the total outstanding.
            remaining=[int(line['amount']) for line in b.lines]
            used=max(0,b.total-b.remaining)
            for i in range(len(remaining)):
                take=min(remaining[i],used);remaining[i]-=take;used-=take
        return remaining

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
            count=0;changes=[]
            locked=Bill.query.filter(Bill.id.in_([b.id for b in rows])).with_for_update().all()
            for b in locked:
                aggregate_keys=('amount_'+str(b.id),'discount_'+str(b.id))
                has_aggregate=any(key in request.form for key in aggregate_keys)
                has_lines=any(key.startswith(('line_amount_'+str(b.id)+'_','line_discount_'+str(b.id)+'_')) for key in request.form)
                if has_aggregate and has_lines:raise ValueError('Use either the particular amounts or the total payment form, then reload.')
                legacy_paid=money(request.form.get(aggregate_keys[0])) if has_aggregate else 0
                legacy_discount=money(request.form.get(aggregate_keys[1])) if has_aggregate else 0
                if legacy_paid+legacy_discount>b.remaining:raise ValueError('Payment and discount cannot exceed the remaining challan amount.')
                if b.frozen: 
                    if legacy_paid or legacy_discount or any(money(request.form.get('line_amount_'+str(b.id)+'_'+str(i))) or money(request.form.get('line_discount_'+str(b.id)+'_'+str(i))) for i in range(len(b.lines))): raise ValueError('Unfreeze this challan before changing it.')
                    continue
                available=payment_particulars(b)
                allocations=[]
                for i,left in enumerate(available):
                    paid=money(request.form.get('line_amount_'+str(b.id)+'_'+str(i)))
                    discount_line=money(request.form.get('line_discount_'+str(b.id)+'_'+str(i)))
                    if has_aggregate:
                        discount_line=min(left,legacy_discount);legacy_discount-=discount_line
                        paid=min(left-discount_line,legacy_paid);legacy_paid-=paid
                    if paid+discount_line>left: raise ValueError('Payment and discount cannot exceed the remaining amount for '+str(b.lines[i].get('particular','fee'))+'.')
                    allocations.append([paid,discount_line])
                amount=sum(x[0] for x in allocations)
                discount=sum(x[1] for x in allocations)
                if not amount and not discount: continue
                if amount+discount>b.remaining: raise ValueError('Payment and discount cannot exceed the remaining challan amount.')
                before=dict(paid_paisa=b.paid,discount_paisa=b.discount,remaining_paisa=b.remaining)
                b.paid+=amount;b.discount+=discount
                changes.append(dict(student_id=b.student_id,bill_id=b.id,before=before,after=dict(paid_paisa=b.paid,discount_paisa=b.discount,remaining_paisa=b.remaining),particulars=allocations))
                user_notes=request.form.get('notes','')[:3500]
                receipt_notes='[SF-LINES]'+json.dumps(allocations,separators=(',',':'))+'\n'+user_notes
                receipt=Receipt(student_id=s.id,bill_id=b.id,amount=amount,discount=discount,day=paid_day,account=account,discount_account=request.form.get('discount_account','Discounts'),notes=receipt_notes,token=token+':'+str(b.id));db.session.add(receipt)
                app.extensions['fee_ledger_helpers']['post'](receipt)
                count+=1
            if not count: raise ValueError('Enter a payment or discount amount.')
            if request.form.get('action')=='send': queue('Fee receipt',[s.id])
            audit('Fee payment',student=s.id,count=count,changes=changes);commit();flash('Payment saved. Requested messages are recorded, but no provider is connected.','success')
            return redirect(url_for('ops.history',student_id=s.id,detail='1'))
        return render('pay.html',title='Pay all dues' if mode=='all' else 'Pay this challan',student=s,rows=rows,token=secrets.token_urlsafe(24),mode=mode,particulars=payment_particulars)

    @bp.route('/fee-action',methods=['POST'])
    def fee_action():
        action=request.form.get('action');ids=selected()
        rows=Bill.query.filter(Bill.id.in_(ids)).with_for_update().all()
        if not rows: raise ValueError('Select at least one challan.')
        if action in ('branded','horizontal','vertical','family'):
            return render('challan_print.html',title='Family Challans' if action=='family' else 'Fee Challans',**app.extensions['challan_branding_helpers']['print_context'](rows,action,request.form))
        if action=='freeze' or action=='unfreeze':
            for b in rows: b.frozen=action=='freeze'
            audit(action,ids=ids);commit();return redirect(url_for('ops.fees',mode='payments'))
        if action=='fine':return app.extensions['late_fee_helpers']['selection'](rows)
        if action=='delete':
            if any(b.paid or b.discount or b.frozen for b in rows): raise ValueError('Paid, discounted or frozen challans cannot be deleted. Reverse receipts first.')
            if request.form.get('confirm')!='yes': raise ValueError('Tick the confirmation box before deleting selected unpaid challans.')
            if any(app.extensions.get('fine_queue_helpers',{}).get('bill_used',lambda bid:False)(b.id) or app.extensions.get('fine_automation_helpers',{}).get('bill_used',lambda bid:False)(b.id) for b in rows):raise ValueError('A selected challan contains posted fine liabilities. Review those charges before deletion; no debt was discarded.')
            for b in rows: db.session.delete(b)
            audit('Delete unpaid challans',ids=ids);commit();return redirect(url_for('ops.fees',mode='payments'))
        raise ValueError('Choose an available action.')

    @bp.route('/reverse-receipts',methods=['GET','POST'])
    def reverse_receipts():
        # A direct GET must never fall through to the generic unfinished-menu page.
        # Reversal itself is POST-only, with CSRF and explicit confirmation.
        if request.method=='GET':
            return redirect(url_for('ops.fees',mode='paid-challans'))
        if request.form.get('confirm')!='yes': raise ValueError('Confirm the receipt reversal.')
        rows=Receipt.query.filter(Receipt.id.in_(selected()),Receipt.voided==False).with_for_update().all()
        if not rows: raise ValueError('Select receipts.')
        changes=[]
        for r in rows:
            b=db.session.execute(db.select(Bill).where(Bill.id==r.bill_id).with_for_update()).scalar_one()
            if b.frozen: raise ValueError('Unfreeze challan before reversing its receipt.')
            before=dict(paid_paisa=b.paid,discount_paisa=b.discount,remaining_paisa=b.remaining)
            app.extensions['fee_ledger_helpers']['reverse'](r)
            b.paid-=r.amount;b.discount-=r.discount;r.voided=True
            changes.append(dict(student_id=b.student_id,bill_id=b.id,before=before,after=dict(paid_paisa=b.paid,discount_paisa=b.discount,remaining_paisa=b.remaining)))
        audit('Reverse receipts',ids=[r.id for r in rows],changes=changes);commit();return redirect(url_for('ops.fees',mode='paid-challans'))

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
        d=day(request.values.get('day',school_today().isoformat()));people_kind='student' if kind=='student' else 'employee'
        objs=people(people_kind)
        if request.method=='POST':
            app.extensions['admission_capacity']['lock']()
            app.extensions['school_settings_helpers']['attendance_guard'](kind,d)
            count=0
            for p in objs:
                status=request.form.get('status_'+str(p.id))
                if not status: continue
                row=Daily.query.filter_by(kind=kind,person_id=p.id,day=d).first()
                if status not in STATUSES or not app.extensions['attendance_control_helpers']['allowed'](kind,status,row.status if row else None): raise ValueError('Invalid or disabled attendance status.')
                if not row: row=Daily(kind=kind,person_id=p.id,day=d);db.session.add(row)
                row.status=status
                app.extensions.get('attendance_device_helpers',{}).get('manual_write',lambda r:None)(row)
                val=request.form.get('lectures_'+str(p.id),'0')
                if not val.isdigit() or int(val)>1000: raise ValueError('Invalid lecture count.')
                row.lectures=int(val)
                for k in ('time_in','time_out'):
                    val=request.form.get(k+'_'+str(p.id),'')
                    if val and not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d',val): raise ValueError('Enter valid times.')
                    setattr(row,k,val)
                count+=1
            if request.form.get('send'): queue('Attendance',[p.id for p in objs if request.form.get('status_'+str(p.id))],audience=kind,event='attendance',context={'day':d.isoformat()})
            audit('Save attendance',kind=kind,day=str(d),count=count);commit();flash(f'{count} attendance records saved.','success')
            return redirect(url_for('ops.take_attendance',kind=kind,day=d.isoformat(),**{k:request.form[k] for k in ('campus','class_name','section','academic_session') if request.form.get(k)}))
        existing={r.person_id:r for r in Daily.query.filter_by(kind=kind,day=d).all()}
        shift_details=app.extensions['record_helpers']['raw_many'](people_kind,objs)
        schedules={p.id:app.extensions['school_settings_helpers']['shift'](kind,p,shift_details.get(p.id,{}),d) for p in objs}
        return render('take_attendance.html',schedules=schedules,locked=bool(kind=='staff' and app.extensions['school_settings_helpers']['config']('hrm:attendance-lock').get('daily','') and str(d)<=app.extensions['school_settings_helpers']['config']('hrm:attendance-lock')['daily']),title='Staff Attendance' if kind=='staff' else 'Student Attendance',kind=kind,people=objs,existing=existing,day=d,details=lambda p:details(p,people_kind))

    @bp.route('/attendance-report')
    def attendance_report():
        view=request.args.get('view','attendance-summary');kind='staff' if view=='staff-attendance-report' else 'student'
        start=day(request.args.get('from',school_today().replace(day=1).isoformat()));end=day(request.args.get('to',school_today().isoformat()))
        if start>end: raise ValueError('Invalid date range.')
        cls=Student if kind=='student' else Employee
        rows=Daily.query.filter(Daily.kind==kind,Daily.day>=start,Daily.day<=end).order_by(Daily.day.desc(),Daily.person_id).all()
        if view=='absentees': rows=[r for r in rows if r.status=='Absent']
        if request.args.get('person_id'): rows=[r for r in rows if str(r.person_id)==request.args['person_id']]
        if request.args.get('export'): return csv_response(['Date','Name','Status','Lectures','Time In','Time Out'],[[r.day,db.session.get(cls,r.person_id).name,r.status,r.lectures,r.time_in,r.time_out] for r in rows],'attendance')
        return render('attendance_report.html',title=TITLES.get(view,'Attendance Report'),rows=rows,person=lambda id:db.session.get(cls,id),summary=Counter(r.status for r in rows),kind=kind)

    def date_sheet_scopes():
        """Only active, permitted, institute-mapped cohorts; keep legacy records unchanged."""
        mapping=app.extensions['institute_setup_helpers']['payload'](refresh=request.method=='POST')
        helpers=app.extensions['school_settings_helpers']
        permitted=getattr(g,'access_campuses',None)
        catalog={v for v,_ in choices('campus')}
        subjects=list(dict.fromkeys([v for v,_ in choices('subject')]+[r.name for r in helpers['items']('subject')]))
        rank={v:i for i,v in enumerate(('Montessori','Play','Nursery','KG-I','KG-II','One','Two','Three','Four','Five','Six','Seven','Eight','Nine','Ten','Tenth'))}
        groups=[];tokens={}
        for campus in sorted(mapping['maps']):
            if campus not in catalog or mapping['campuses'].get(campus) is False or (permitted is not None and campus not in permitted):continue
            classes=[]
            for cohort in sorted(mapping['maps'][campus],key=lambda x:(rank.get(x['class_name'],1000),x['class_name'].casefold())):
                cls=cohort['class_name'];academic=cohort.get('academic_session','')
                if not academic:continue
                sections=[]
                for section in sorted(set(cohort.get('sections') or [''])):
                    scope=dict(campus=campus,class_name=cls,section=section,academic_session=academic)
                    token=json.dumps([campus,cls,section,academic],ensure_ascii=False,separators=(',',':'))
                    tokens[token]=scope
                    sections.append(dict(token=token,section=section))
                classes.append(dict(name=cls,academic=academic,sections=sections,subjects=[s for s in subjects if helpers['subject_allowed'](campus,cls,s)]))
            if classes:groups.append(dict(name=campus,classes=classes,test_types=helpers['exam_types'](campus)))
        return bool(mapping['maps']),groups,tokens

    def saved_date_sheet(sheet_id):
        row=db.get_or_404(Workflow,sheet_id)
        if row.kind!='date-sheets':abort(404)
        allowed=getattr(g,'access_campuses',None)
        if allowed is not None and row.data.get('campus') not in allowed:abort(403)
        return row

    def date_sheet_revision(row):
        return hashlib.sha256(json.dumps(row.data,sort_keys=True,ensure_ascii=False).encode()).hexdigest()

    def date_sheet_has_publication(row):
        Item=app.extensions.get('parent_study_models',{}).get('item')
        return bool(Item is not None and Item.query.filter(Item.kind=='dates',Item.data['workflow_id'].as_integer()==row.id).first())

    def date_sheet_mutable(row):
        if date_sheet_has_publication(row):raise ValueError('This date sheet has a parent publication record. Keep it for audit history and create a revised date sheet instead.')

    def date_sheet_format(value,pattern):
        try:return date.fromisoformat(value).strftime(pattern)
        except (ValueError,TypeError):return value or '—'

    app.jinja_env.filters['sheet_date']=date_sheet_format

    def date_sheet_pupils(row, sid=None):
        # Require a specific campus and class; never expose an institute-wide roster.
        if not row.data.get('campus') or not row.data.get('class_name'):
            raise ValueError('A student copy requires a saved campus and class.')
        D=rm['student']
        query=Student.query.join(D,D.student_id==Student.id).filter(Student.status=='Active',Student.class_name==row.data['class_name'])
        for key in ('campus','section','academic_session'):
            if row.data.get(key):query=query.filter(D.data[key].as_string()==row.data[key])
        if sid is not None:query=query.filter(Student.id==sid)
        return query.order_by(Student.name,Student.id).all()

    def date_sheet_student(row,sid):
        pupils=date_sheet_pupils(row,sid)
        if not pupils:abort(404)
        return pupils[0]

    def date_sheet_student_photo(student):
        return rm['file'].query.filter_by(owner_kind='student',owner_id=student.id,photo=True).order_by(rm['file'].id.desc()).first()

    @bp.get('/date-sheet/<int:sheet_id>/student-photo/<int:sid>')
    def date_sheet_photo(sheet_id,sid):
        row=saved_date_sheet(sheet_id)
        student=date_sheet_student(row,sid);photo=date_sheet_student_photo(student)
        if not photo or photo.mime not in ('image/jpeg','image/png','image/webp'):abort(404)
        response=send_file(io.BytesIO(photo.content),mimetype=photo.mime,max_age=0)
        response.headers['Cache-Control']='private, no-store'
        response.headers['X-Content-Type-Options']='nosniff'
        return response

    @bp.get('/date-sheet/<int:sheet_id>/print')
    def date_sheet_print(sheet_id):
        row=saved_date_sheet(sheet_id)
        copy=request.args.get('copy','parent')
        if copy not in ('parent','office','student','class'):abort(404)
        if copy=='class':
            pupils=date_sheet_pupils(row)
            if not pupils:raise ValueError('No active students match this date sheet campus, class, section and session.')
            data=app.extensions['record_helpers']['raw_many']('student',pupils)
            def roll_key(p):
                roll=str(data.get(p.id,{}).get('roll_no') or '').strip()
                return (not bool(roll),not roll.isdigit(),int(roll) if roll.isdigit() else roll.casefold(),p.name.casefold(),p.id)
            pupils.sort(key=roll_key)
            show_photo=request.args.get('photo','1')=='1'
            photos=set()
            if show_photo:
                F=rm['file']
                # Load photo metadata in one query, without copying image bytes into HTML.
                seen=set()
                for f in F.query.filter(F.owner_kind=='student',F.owner_id.in_([p.id for p in pupils]),F.photo.is_(True)).order_by(F.id.desc()).all():
                    if f.owner_id in seen:continue
                    seen.add(f.owner_id)
                    if f.mime in ('image/jpeg','image/png','image/webp'):photos.add(f.owner_id)
            response=make_response(render('date_sheet_print.html',title='Class-wise Student Date Sheets',row=row,office=False,batch_pupils=pupils,pupil_data=data,photo_ids=photos,show_photo=show_photo))
            response.headers['Cache-Control']='private, no-store'
            return response
        if copy=='student':
            raw=request.args.get('student_id','')
            if not raw:
                pupils=date_sheet_pupils(row)
                data=app.extensions['record_helpers']['raw_many']('student',pupils)
                response=make_response(render('date_sheet_students.html',title='Student-wise Date Sheet',row=row,pupils=pupils,pupil_data=data))
            else:
                if not raw.isascii() or not raw.isdigit() or len(raw)>10:abort(404)
                pupil=date_sheet_student(row,int(raw))
                data=app.extensions['record_helpers']['raw_many']('student',[pupil]).get(pupil.id,{})
                show_photo=request.args.get('photo','1')=='1'
                photo=date_sheet_student_photo(pupil) if show_photo else None
                response=make_response(render('date_sheet_print.html',title='Student-wise Date Sheet',row=row,office=False,student=pupil,student_data=data,show_photo=show_photo,student_photo=bool(photo and photo.mime in ('image/jpeg','image/png','image/webp'))))
            response.headers['Cache-Control']='private, no-store'
            return response
        return render('date_sheet_print.html',title='Date Sheet',row=row,office=copy=='office')

    @bp.get('/date-sheet/<int:sheet_id>/edit')
    def date_sheet_edit(sheet_id):
        row=saved_date_sheet(sheet_id);date_sheet_mutable(row)
        helpers=app.extensions['school_settings_helpers']
        subjects=list(dict.fromkeys([v for v,_ in choices('subject')]+[r.name for r in helpers['items']('subject')]))
        subjects=[s for s in subjects if helpers['subject_allowed'](row.data.get('campus',''),row.data.get('class_name',''),s)]
        return render('date_sheet_edit.html',title='Edit Date Sheet',row=row,revision=date_sheet_revision(row),subjects=subjects,exam_types=helpers['exam_types'](row.data.get('campus','')),subject_grading={r.name:r.data.get('grading','Marks') for r in helpers['items']('subject')})

    def award_from_date_sheet():
        # Always read the saved school-scoped document, not client-supplied papers.
        app.extensions['admission_capacity']['lock']()
        sid=request.form.get('source_sheet_id',type=int)
        if not sid:raise ValueError('Choose a saved date sheet.')
        source=saved_date_sheet(sid);d=source.data
        if request.form.get('source_revision')!=date_sheet_revision(source):raise ValueError('The date sheet changed. Review its papers again.')
        if not d.get('campus') or not d.get('class_name') or not d.get('academic_session') or not d.get('exam_test_type'):raise ValueError('The saved date sheet must have a campus, class, session and exam type.')
        if any(request.form.get(k)!=d.get(k) for k in ('class_name','exam_test_type')):raise ValueError('Choose a date sheet matching the selected class and exam type.')
        # Existing linked lists remain independent snapshots; reopening never overwrites marks.
        existing=Workflow.query.filter_by(kind='awards').all()
        prior=next((r for r in existing if r.data.get('source_date_sheet_id')==source.id),None)
        if prior:
            if any(prior.data.get(k)!=d.get(k) for k in ('campus','class_name','section','academic_session')):raise ValueError('The linked award list has a different scope.')
            flash('An award list already exists for this date sheet. Existing marks are preserved.','success')
            return redirect(url_for('ops.marks',award_id=prior.id))
        helpers=app.extensions['school_settings_helpers']
        if d['exam_test_type'] not in helpers['exam_types'](d['campus']):raise ValueError('The exam type is no longer configured for this campus.')
        mapped,_,tokens=date_sheet_scopes()
        if mapped and not any(all(scope[k]==d.get(k,'') for k in ('campus','class_name','section','academic_session')) for scope in tokens.values()):raise ValueError('The date sheet cohort is no longer active in Institute Setup.')
        papers=[]
        for p in d.get('papers',[]):
            subject=p.get('subject','')
            if not subject or not helpers['subject_allowed'](d['campus'],d['class_name'],subject):raise ValueError('A saved paper is no longer assigned to this class. Review the date sheet.')
            day(p.get('date',''))
            if p.get('type') not in ('Written','Oral','Practical'):raise ValueError('Review the paper types on the date sheet.')
            grading=helpers['subject_config'](subject).get('grading','Marks')
            if grading!=p.get('grading','Marks'):raise ValueError('Subject grading changed since the date sheet was saved. Review the date sheet first.')
            if grading=='Marks':
                try:total=float(p.get('total',0))
                except (TypeError,ValueError):raise ValueError('Review total marks on the date sheet.')
                if not 0<total<=10000:raise ValueError('Review total marks on the date sheet.')
            papers.append(dict(p))
        if not papers:raise ValueError('The selected date sheet has no papers.')
        category=request.form.get('assessment_category','')
        if category and category not in PERFORMANCE_CATEGORIES:raise ValueError('Choose a valid assessment category.')
        student_filter=request.form.get('student_filter','class')
        if student_filter not in ('class','subject'):raise ValueError('Choose a valid student filtering mode.')
        used={r.data.get('name') for r in existing}|{r.data.get('batch_name') for r in existing}
        name=('Award — '+d.get('name','Exam'))[:950]
        if name in used:name=name+' — '+str(source.id)
        if name in used:raise ValueError('An award list with this name already exists.')
        data={k:d.get(k,'') for k in ('campus','class_name','section','academic_session','exam_test_type','print_heading')}
        data.update(name=name,papers=papers,gender='',group_name='',return_date='',sort_order='roll',student_filter=student_filter,recheck=bool(d.get('recheck')),assessment_category=category,source_date_sheet_id=source.id,source_date_sheet_revision=date_sheet_revision(source))
        obj=Workflow(kind='awards',data=data,status='Active')
        db.session.add(obj);db.session.flush();audit('Create award list from date sheet',award_id=obj.id,source_sheet_id=source.id,campus=d['campus']);commit()
        return redirect(url_for('ops.marks',award_id=obj.id))

    def award_date_sheet_options():
        allowed=getattr(g,'access_campuses',None)
        rows=Workflow.query.filter_by(kind='date-sheets').order_by(Workflow.id.desc()).all()
        return [dict(id=r.id,revision=date_sheet_revision(r),name=r.data.get('name',''),campus=r.data['campus'],class_name=r.data['class_name'],section=r.data.get('section',''),session=r.data['academic_session'],exam_type=r.data['exam_test_type'],papers=[{k:p.get(k,'') for k in ('subject','date','type','total','grading','time')} for p in r.data.get('papers',[])]) for r in rows if all(r.data.get(k) for k in ('campus','class_name','academic_session','exam_test_type')) and (allowed is None or r.data['campus'] in allowed)]

    @bp.route('/examination/<kind>',methods=['GET','POST'])
    def examination(kind):
        if kind not in ('date-sheets','awards'): abort(404)
        if kind=='awards' and request.method=='POST' and request.form.get('action')=='from-date-sheet':
            return award_from_date_sheet()
        if kind=='date-sheets' and request.method=='POST':
            # Serialize name checks and the entire batch, not individual rows.
            app.extensions['admission_capacity']['lock']()
        mapped,date_groups,date_tokens=date_sheet_scopes() if kind=='date-sheets' else (False,[],{})
        if request.method=='POST':
            editing=None
            if kind=='date-sheets' and request.form.get('action') in ('edit','delete'):
                sheet_id=request.form.get('sheet_id',type=int)
                if not sheet_id:abort(422)
                editing=saved_date_sheet(sheet_id);date_sheet_mutable(editing)
                if request.form.get('revision')!=date_sheet_revision(editing):raise ValueError('This date sheet changed. Reload before editing or deleting.')
                if request.form['action']=='delete':
                    audit('Delete date sheet',sheet_id=editing.id,campus=editing.data.get('campus',''),before=editing.data)
                    db.session.delete(editing);commit();flash('Date sheet deleted.','success')
                    return redirect(url_for('ops.examination',kind=kind))
            name=request.form.get('name','').strip()
            if not name or len(name)>(1000 if editing else 500): raise ValueError('Enter a valid date sheet or award list name.')
            existing=Workflow.query.filter_by(kind=kind).all()
            if any(x is not editing and (name==x.data.get('name') or (name==x.data.get('batch_name') and (not editing or name!=editing.data.get('name')))) for x in existing): raise ValueError('Name must be unique.')
            scopes=[{k:(editing.data.get(k,'') if editing else request.form.get(k,'').strip()) for k in ('campus','class_name','section','academic_session')}]
            if kind=='date-sheets' and not editing and (mapped or request.form.get('date_scope')):
                chosen=request.form.getlist('date_cohort');academic=request.form.get('academic_session','')
                if request.form.get('date_scope')!='mapped' or not 1<=len(chosen)<=500 or len(chosen)!=len(set(chosen)) or any(t not in date_tokens for t in chosen):
                    raise ValueError('Select at least one active campus, class and section from Institute Setup.')
                scopes=[date_tokens[t] for t in chosen]
                if not academic or any(s['academic_session']!=academic for s in scopes):
                    raise ValueError('Choose classes and sections from one academic session.')
            permitted=getattr(g,'access_campuses',None)
            if kind=='date-sheets' and permitted is not None and any(s['campus'] not in permitted for s in scopes):abort(403)
            exam_type=request.form.get('exam_test_type','')
            if exam_type and any(exam_type not in app.extensions['school_settings_helpers']['exam_types'](s['campus']) for s in scopes):raise ValueError('Choose a test type configured for every selected campus.')
            papers=[]
            subjects=request.form.getlist('subject');dates=request.form.getlist('exam_date');types=request.form.getlist('test_type');totals=request.form.getlist('total');teachers=request.form.getlist('teacher')
            for i,subject in enumerate(subjects):
                if not subject: raise ValueError('Subject is required on every row.')
                allowed=[app.extensions['school_settings_helpers']['subject_allowed'](s['campus'],s['class_name'],subject) for s in scopes]
                if (not any(allowed) if kind=='date-sheets' and mapped else not all(allowed)):raise ValueError('Choose a subject assigned to the selected class(es).')
                if kind=='date-sheets' and mapped and subject not in ({v for v,_ in choices('subject')}|{r.name for r in app.extensions['school_settings_helpers']['items']('subject')}):raise ValueError('Choose a configured subject.')
                if i>=len(dates) or i>=len(types): raise ValueError('Every paper needs an exam date and test type.')
                d=day(dates[i]);typ=types[i]
                if typ not in ('Written','Oral','Practical'): raise ValueError('Select a valid test type.')
                subject_config=app.extensions['school_settings_helpers']['subject_config'](subject)
                grading=subject_config.get('grading','Marks')
                total=0
                if grading=='Marks':
                    t=totals[i] if i<len(totals) else ''
                    if not t.strip(): raise ValueError('Enter total marks for every numeric paper; no marks are prefilled.')
                    try: total=float(t)
                    except ValueError: raise ValueError('Total marks must be numeric.')
                    if not 0<total<=10000: raise ValueError('Total marks must be positive and at most 10,000.')
                teacher=teachers[i] if i<len(teachers) else ''
                if teacher and teacher not in dict(choices('teacher')): raise ValueError('Only designations containing Teacher can receive award lists.')
                exam_time=(request.form.getlist('exam_time')+['']*len(subjects))[i] if request.form.get('include_time') else ''
                syllabus=(request.form.getlist('syllabus')+['']*len(subjects))[i] if request.form.get('include_syllabus') else ''
                if kind=='date-sheets' and (exam_time and not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d',exam_time) or len(syllabus)>10000):raise ValueError('Enter a valid exam time and syllabus of at most 10,000 characters.')
                papers.append(dict(subject=subject,grading=grading,subject_group=subject_config.get('group',''),date=d.isoformat(),type=typ,total=total,teacher=teacher,time=exam_time,syllabus=syllabus))
            if not papers: raise ValueError('Add at least one subject.')
            data={k:request.form.get(k,'').strip()[:1000] for k in ('name','print_heading','campus','class_name','section','gender','group_name','academic_session','return_date','sort_order','student_filter')}
            if data['student_filter'] not in ('','class','subject'):raise ValueError('Choose Class Wise or Subject Wise student filtering.')
            if data['sort_order'] not in ('','sid','roll','section'):raise ValueError('Choose SID, Roll No or Section Wise sorting.')
            category=request.form.get('assessment_category','')
            if category and category not in PERFORMANCE_CATEGORIES: raise ValueError('Choose a valid assessment category.')
            data.update(papers=papers,recheck=bool(request.form.get('recheck')),assessment_category=category,exam_test_type=exam_type)
            if data.get('return_date'): day(data['return_date'])
            if kind=='date-sheets':
                data.update(include_time=bool(request.form.get('include_time')),include_syllabus=bool(request.form.get('include_syllabus')))
            if editing:
                before=editing.data
                editing.data={**before,**{k:data[k] for k in ('name','print_heading','papers','recheck','exam_test_type','include_time','include_syllabus')}}
                audit('Edit date sheet',sheet_id=editing.id,campus=before.get('campus',''),before=before,after=editing.data);commit()
                flash('Date sheet updated.','success')
                return redirect(url_for('ops.examination',kind=kind))
            if kind=='date-sheets' and mapped:
                names=[name if len(scopes)==1 else name+' — '+' / '.join((s['campus'],s['class_name'],s['section'] or 'All sections',s['academic_session'])) for s in scopes]
                used={x.data.get('name') for x in existing}|{x.data.get('batch_name') for x in existing}
                if len(names)!=len(set(names)) or any(n in used or len(n)>1000 for n in names):raise ValueError('A generated date sheet name already exists or is too long. Choose another name.')
                helpers=app.extensions['school_settings_helpers']
                scoped_papers=[[p for p in papers if helpers['subject_allowed'](scope['campus'],scope['class_name'],p['subject'])] for scope in scopes]
                missing=[s['campus']+' / '+s['class_name']+' / '+(s['section'] or 'All sections') for s,pp in zip(scopes,scoped_papers) if not pp]
                if missing:raise ValueError('Add at least one applicable paper for each selected class/section: '+', '.join(missing))
                for scope,scope_name,pp in zip(scopes,names,scoped_papers):
                    db.session.add(Workflow(kind=kind,data={**data,**scope,'papers':pp,'name':scope_name,'batch_name':name},status='Active'))
                audit('Create '+kind,name=name,count=len(scopes));commit()
                flash(f'{len(scopes)} date sheet(s) saved.','success')
                return redirect(url_for('ops.examination',kind=kind))
            obj=Workflow(kind=kind,data=data,status='Active');db.session.add(obj);audit('Create '+kind);commit()
            return redirect(url_for('ops.marks',award_id=obj.id)) if kind=='awards' else redirect(url_for('ops.examination',kind=kind))
        return render('examination.html',award_date_sources=award_date_sheet_options() if kind=='awards' else [],date_revision=date_sheet_revision,date_has_publication=date_sheet_has_publication,date_mapped=mapped,date_groups=date_groups,date_sessions=sorted({s['academic_session'] for s in date_tokens.values()}),subject_grading={r.name:r.data.get('grading','Marks') for r in app.extensions['school_settings_helpers']['items']('subject')},configured_tests=app.extensions['school_settings_helpers']['items']('test-type'),title='Create Award List' if kind=='awards' else 'Create Date Sheet',kind=kind,rows=Workflow.query.filter_by(kind=kind).order_by(Workflow.id.desc()).all())

    def award_students(award):
        Details=rm['student']
        query=Student.query.outerjoin(Details,Details.student_id==Student.id).filter(Student.status=='Active')
        for key in ('class_name','campus','section','gender','group_name','academic_session'):
            value=award.data.get(key)
            if value:query=query.filter((Student.class_name if key=='class_name' else Details.data[key].as_string())==value)
        pupils=query.order_by(Student.id).all();data=app.extensions['record_helpers']['raw_many']('student',pupils)
        if award.data.get('student_filter')=='subject':pupils=[p for p in pupils if any(enrolled(award,paper,data.get(p.id,{})) for paper in award.data['papers'])]
        def roll(p):
            value=str(data.get(p.id,{}).get('roll_no','')).strip()
            return (not bool(value),0 if value.isdigit() else 1,int(value) if value.isdigit() else value.casefold(),p.id)
        if award.data.get('sort_order')=='roll':pupils.sort(key=roll)
        elif award.data.get('sort_order')=='section':pupils.sort(key=lambda p:(not bool(data.get(p.id,{}).get('section')),data.get(p.id,{}).get('section','').casefold(),roll(p)))
        return pupils

    @bp.post('/assessment-category/<int:award_id>')
    def assessment_category(award_id):
        award=db.get_or_404(Workflow,award_id)
        if award.kind!='awards': abort(404)
        category=request.form.get('assessment_category','')
        if category and category not in PERFORMANCE_CATEGORIES: raise ValueError('Choose a valid assessment category.')
        award.data={**award.data,'assessment_category':category}
        audit('Set assessment category',award=award.id,category=category);commit()
        flash('Assessment category saved. Existing marks are unchanged.','success')
        return redirect(url_for('ops.marks',award_id=award.id))

    @bp.route('/marks/<int:award_id>',methods=['GET','POST'])
    def marks(award_id):
        award=db.get_or_404(Workflow,award_id)
        if award.kind!='awards': abort(404)
        if request.method=='POST':app.extensions['admission_capacity']['lock']()
        students=award_students(award);papers=award.data['papers']
        scores={(x.student_id,x.paper):x for x in Score.query.filter_by(award_id=award.id).all()}
        qlookup={(x.student_id,x.paper):x for x in QualitativeScore.query.filter_by(award_id=award.id).all()}
        pupil_details=app.extensions['record_helpers']['raw_many']('student',students)
        direct={s.id:app.extensions['school_settings_helpers']['direct_choices'](award.data.get('campus') or pupil_details.get(s.id,{}).get('campus',''),award.data.get('class_name') or s.class_name) for s in students}
        allowed={(s.id,i):enrolled(award,p,pupil_details.get(s.id,{})) for s in students for i,p in enumerate(papers)}
        source=dict(award=award.data,roster=[[s.id,s.name,s.class_name,s.status,pupil_details.get(s.id,{})] for s in students],scores=sorted([[x.id,x.student_id,x.paper,x.obtained,x.state] for x in scores.values()]),qualitative=sorted([[x.id,x.student_id,x.paper,x.value,x.state,x.remarks,x.version] for x in qlookup.values()]),direct=direct)
        stamp=hashlib.sha256(json.dumps(source,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        actor=dict(scope=(getattr(g,'school_identity',None) or {}).get('scope'),owner=session.get('owner_id'),csrf=session.get('record_csrf'))
        signer=URLSafeTimedSerializer(app.config['SECRET_KEY'],salt='schoolflow-marks-review-v1')
        if request.method=='POST':
            raw=request.form.get('marks_review_token','')
            if not raw or len(raw)>8192:raise ValueError('Reload the marks form before saving.')
            try:review=signer.loads(raw,max_age=8*60*60)
            except BadData:raise ValueError('This marks form expired or changed. Reload before saving.')
            if not isinstance(review,dict) or review.get('actor')!=actor or review.get('award_id')!=award.id or review.get('stamp')!=stamp or not re.fullmatch(r'[a-f0-9]{32}',str(review.get('nonce',''))):raise ValueError('The marks, subjects, roster or grading choices changed. Reload; no partial marks were saved.')
            if db.session.get(ExamMarksSave,review['nonce']):raise ValueError('This marks form was already saved. Reload before submitting again.')
            db.session.add(ExamMarksSave(nonce=review['nonce'],award_id=award.id))
            if request.form.get('action')=='send' and not set(selected('student_ids'))<={s.id for s in students}:raise ValueError('Choose notification recipients from this award list.')
            for s in students:
                for i,p in enumerate(papers):
                    if not allowed[(s.id,i)]:
                        if any(request.form.get(f'{field}_{s.id}_{i}','') for field in ('mark','qual','state')):raise ValueError('Marks cannot be entered for a subject the student is not enrolled in. Reload the award list.')
                        continue
                    value=request.form.get(f'mark_{s.id}_{i}','').strip();state=request.form.get(f'state_{s.id}_{i}','')
                    if state not in ('','A','L'): raise ValueError('Invalid paper attendance.')
                    grading=p.get('grading','Marks')
                    if grading!='Marks':
                        row=qlookup.get((s.id,i))
                        revision=request.form.get(f'qual_version_{s.id}_{i}','')
                        if not revision.isdigit() or int(revision)!=(row.version if row else 0):raise ValueError('A qualitative result changed. Reload before saving.')
                        values=request.form.getlist(f'qual_{s.id}_{i}');chosen=values[-1] if values else ''
                        remarks=''
                        if state:chosen=None
                        elif grading=='Checkbox':
                            if chosen not in ('','0','1'):raise ValueError('Choose Done, Not done or Unmarked.')
                            chosen=chosen or None
                        elif grading=='Direct Grading':
                            if chosen and chosen not in direct[s.id] and (not row or chosen!=row.value):raise ValueError('Choose a direct grade enabled in this class grading policy.')
                            remarks=direct[s.id].get(chosen,row.remarks if row and chosen==row.value else '')
                            chosen=chosen or None
                        else:raise ValueError('Unsupported subject grading type.')
                        if not row:row=QualitativeScore(award_id=award.id,student_id=s.id,paper=i);db.session.add(row)
                        row.value=chosen;row.state=state;row.remarks=remarks
                        continue
                    try: n=float(value) if value else None
                    except ValueError: raise ValueError('Marks must be numeric.')
                    if n is not None and (not 0<=n<=p['total']): raise ValueError('Obtained marks must be within total marks.')
                    row=scores.get((s.id,i))
                    if not row: row=Score(award_id=award.id,student_id=s.id,paper=i);db.session.add(row)
                    row.obtained=None if state else n;row.state=state
            if request.form.get('action')=='send': queue('Exam marks',selected('student_ids'))
            audit('Update marks',award=award.id);commit();flash('Marks saved.','success');return redirect(url_for('ops.marks',award_id=award.id))
        scores={(x.student_id,x.paper):x for x in Score.query.filter_by(award_id=award.id).all()}
        counts=Counter(('Absent' if x.state=='A' else 'Leave' if x.state=='L' else 'Present') for x in scores.values() if x.state or x.obtained is not None)
        counts.update(('Absent' if x.state=='A' else 'Leave' if x.state=='L' else 'Present') for x in qlookup.values() if x.state or x.value is not None)
        review_token=signer.dumps(dict(actor=actor,award_id=award.id,stamp=stamp,nonce=secrets.token_hex(16)))
        return render('marks.html',allowed=allowed,marks_review_token=review_token,qualitative=qlookup,direct=direct,title='Update Marks',award=award,students=students,papers=papers,scores=scores,counts=counts)

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
                exam_date=request.form.get('exam_date','');exam_from=request.form.get('exam_from','');exam_to=request.form.get('exam_to','')
                if exam_date:day(exam_date)
                if any(t and not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d',t) for t in (exam_from,exam_to)):raise ValueError('Choose valid exam times.')
                if exam_from and exam_to and exam_to<=exam_from:raise ValueError('Exam end time must be after its start time.')
                title=request.form.get('slip_name','Roll Number Slip').strip()[:160] or 'Roll Number Slip'
                context=dict(rollnosliptitle=title,Examstartingdate=exam_date,examDate=exam_date,examtimeduration=(exam_from+' – '+exam_to) if exam_from and exam_to else (exam_from or exam_to))
                return render('roll_print.html',title=title,students=students,details=details,roll_context=context,exam_date=exam_date,exam_from=exam_from,exam_to=exam_to)
        return render('rolls.html',title='Roll Number Slip',students=people(),details=details)

    @bp.route('/salary-plans',methods=['GET','POST'])
    def plans():
        if request.method=='POST':app.extensions['admission_capacity']['lock']()
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
            for k in ['lecture_wise','lecture_incentive','all_present_bonus','include_plan_earnings','apply_manual_increments']:
                data[k]=bool(request.form.get(k))
            if data['annual_increment']:raise ValueError('Automatic annual increments are off. Use an approved manual increment with an effective month.')
            if data['apply_manual_increments'] and data['lecture_wise'] and not data['include_plan_earnings']:
                raise ValueError('Manual salary increments adjust monthly basic. For lecture-only staff, update their lecture rate instead.')
            data['sandwich_leave']=False  # Disabled by the school for this phase.
            data['allowances']=[]
            for head in app.extensions['school_settings_helpers']['items']('allowance'):
                amount=money(request.form.get('allowance_'+str(head.id),'0'))
                if amount:data['allowances'].append(dict(id=head.id,name=head.name,amount=amount,**head.data))
            data['increment_month']=request.form.get('increment_month','')
            data['increment_type']=request.form.get('increment_type','Abs')
            data['rules']=[]
            for i,status in enumerate(deduction_types):data['rules'].append(parse_rule(request.form,i,status,money))
            if request.form.get('action')=='preview':
                days=request.form.get('preview_working_days','0');counts=[]
                if not days.isdigit() or not 0<=int(days)<=31:raise ValueError('Preview working days must be 0–31.')
                for i in range(len(deduction_types)):
                    raw=request.form.get('preview_count_'+str(i),'0')
                    if not raw.isdigit() or not 0<=int(raw)<=31:raise ValueError('Preview attendance counts must be 0–31.')
                    counts.append(int(raw))
                if sum(counts)>31 or (int(days)>0 and sum(counts)>int(days)):raise ValueError('Preview attendance counts cannot exceed the selected working/calendar days.')
                preview=[deduction(rule,count,data['basic'],int(days)) for rule,count in zip(data['rules'],counts)]
                response=render('salary_plans.html',title='Salary rule preview · not saved',rows=Workflow.query.filter_by(kind='salary-plans').order_by(Workflow.id.desc()).all(),employee=lambda id:db.session.get(Employee,int(id)),data=data,edit=edit,deduction_types=deduction_types,allowances=app.extensions['school_settings_helpers']['items']('allowance'),rule_preview=preview,jump_modes=JUMP_MODES,cap_modes=CAP_MODES)
                db.session.rollback();return response
            if obj: obj.data=data;obj.status='Pending'
            else: db.session.add(Workflow(kind='salary-plans',data=data,status='Pending'))
            audit('Save salary plan',employee=employee_id);commit();flash('Salary plan saved for approval.','success');return redirect(url_for('ops.plans'))
        return render('salary_plans.html',title='Create / Update Salary Plan',rows=Workflow.query.filter_by(kind='salary-plans').order_by(Workflow.id.desc()).all(),employee=lambda id:db.session.get(Employee,int(id)),data=obj.data if obj else {},edit=edit,deduction_types=deduction_types,allowances=app.extensions['school_settings_helpers']['items']('allowance'),rule_preview=None,jump_modes=JUMP_MODES,cap_modes=CAP_MODES)

    def lecture_amount(entry,month_value):
        if entry.data.get('rate_override'): return money(entry.data['rate_override'])*int(entry.data['lectures'])
        rates=[r for r in Workflow.query.filter_by(kind='lecture-rates',status='Active').all() if r.data['employee_id']==entry.data['employee_id'] and r.data['starts']<=month_value and r.data['status']=='Active' and all(not r.data.get(k) or r.data[k]==entry.data.get(k) for k in ('class_name','section','subject'))]
        rates.sort(key=lambda r:(sum(bool(r.data.get(k)) for k in ('class_name','section','subject')),r.data['starts'],r.id),reverse=True)
        if not rates: raise ValueError('No matching lecture rate for a selected approved lecture.')
        return money(rates[0].data['amount'])*int(entry.data['lectures'])

    @bp.route('/payroll',methods=['GET','POST'])
    def payroll():
        if request.method=='POST':app.extensions['admission_capacity']['lock']()
        today=school_today();previous=today.replace(day=1).toordinal()-1;default_month=date.fromordinal(previous).strftime('%Y-%m')
        m=month(request.values.get('month',default_month));view=request.values.get('view','generate-salary')
        if request.method=='POST':
            action=request.form.get('action')
            if action=='generate':
                if m>=today.strftime('%Y-%m'): raise ValueError('Pre-test payroll generates completed previous months only.')
                plans_list=Workflow.query.filter_by(kind='salary-plans',status='Approved').order_by(Workflow.id.desc()).all();seen=set();count=0;generated=[]
                chosen=selected('employee_ids')
                if not chosen: raise ValueError('Select employees.')
                approved={int(p.data['employee_id']) for p in plans_list}
                if not set(chosen)<=approved: raise ValueError('Every selected employee needs an approved salary plan. No payroll was saved.')
                for p in plans_list:
                    eid=int(p.data['employee_id'])
                    if eid in seen or eid not in chosen: continue
                    seen.add(eid)
                    if Salary.query.filter_by(employee_id=eid,month=m).first(): continue
                    data=p.data
                    staff=db.get_or_404(Employee,eid)
                    joining=details(staff,'employee').get('joining_date')
                    if not joining: raise ValueError('Complete the employee joining date before generating salary: '+staff.name)
                    joined=day(joining);month_start=day(m+'-01');month_end=day(m+'-'+str(calendar.monthrange(int(m[:4]),int(m[5:]))[1]))
                    if joined>month_end: raise ValueError('Salary month is before the employee joining date: '+staff.name)
                    pays_basic=not data.get('lecture_wise') or data.get('include_plan_earnings')
                    working_calendar=db.session.get(app.extensions['payroll_calendar_model'],m)
                    if working_calendar and not working_calendar.working_dates:raise ValueError('The saved working calendar has no working dates. Review it first.')
                    if joined>month_start and pays_basic and not working_calendar:
                        raise ValueError('Set this salary month\'s working calendar before calculating joining-month pay: '+staff.name)
                    if request.form.get('attendance_based') and not working_calendar and any(r.get('type')=='Percent' and r.get('amount') for r in data['rules']):
                        raise ValueError('Set the working calendar before calculating percentage-of-daily-basic deductions.')
                    data={**data,'sandwich_leave':False}  # Never apply legacy sandwich flags.
                    for rule in data['rules']:deduction(rule,0,data['basic'],1)  # Validate any legacy rule interpretation before payroll.
                    if data.get('annual_increment'): raise ValueError('Annual increment posting needs a verified reference rule. No payroll was saved.')
                    increment_rows=[row for row in Workflow.query.filter_by(kind='increments',status='Approved').order_by(Workflow.id).all()
                                    if int(row.data['employee_id'])==eid and row.data['effective']<=m] if pays_basic and data.get('apply_manual_increments') else []
                    increment_details=[dict(id=row.id,amount=money(row.data['amount']),effective=row.data['effective'],reason=row.data.get('reason','')) for row in increment_rows]
                    monthly_basic=data['basic']+sum(row['amount'] for row in increment_details)
                    proration=joining_pay(m,joined,monthly_basic,working_calendar.working_dates) if pays_basic and joined>month_start else None
                    base=proration['payable_basic'] if proration else monthly_basic
                    attendance=Daily.query.filter(Daily.kind=='staff',Daily.person_id==eid,Daily.day>=max(joined,month_start),Daily.day<=month_end).all()
                    deduction_attendance=[row for row in attendance if not working_calendar or row.day.isoformat() in working_calendar.working_dates]
                    counts=Counter(r.status for r in deduction_attendance);deductions=0;breakdown=[]
                    days=len(working_calendar.working_dates) if working_calendar else calendar.monthrange(int(m[:4]),int(m[5:]))[1]
                    if request.form.get('attendance_based'):
                        for rule in data['rules']:
                            calculated=deduction(rule,counts[rule['status']],monthly_basic,days)
                            deductions+=calculated['amount'];breakdown.append(calculated)
                    lecture_rows=[r for r in Workflow.query.filter_by(kind='lecture-register',status='Approved').all() if int(r.data['employee_id'])==eid and r.data['date'][:7]==m]
                    if data.get('lecture_wise') and any(day(r.data['date'])<joined for r in lecture_rows): raise ValueError('Approved lectures precede the employee joining date. Correct the lecture register before generating salary.')
                    lecture_details=[dict(id=r.id,date=r.data['date'],class_name=r.data.get('class_name',''),section=r.data.get('section',''),subject=r.data.get('subject',''),lectures=int(r.data['lectures']),amount=lecture_amount(r,m)) for r in lecture_rows] if data.get('lecture_wise') else []
                    lecture_pay=sum(row['amount'] for row in lecture_details)
                    earnings=(base+data['security_return'] if pays_basic else 0)+lecture_pay
                    if pays_basic:
                        earnings+=sum(a['amount'] for a in data.get('allowances',[]) if a['type']=='Earning')
                        deductions+=sum(a['amount'] for a in data.get('allowances',[]) if a['type']=='Deduction')
                    if data.get('lecture_incentive') and not data.get('lecture_wise'): earnings+=data['incentive_per_lecture']*sum(r.lectures for r in attendance)
                    bonus=None
                    if data.get('all_present_bonus') and pays_basic:
                        if data.get('bonus_amount'):raise ValueError('This legacy plan has a fixed all-present amount. Update it to the one-working-day bonus before generating salary.')
                        if not working_calendar:raise ValueError('Set the working calendar before calculating the all-present bonus.')
                        bonus=all_present_bonus(m,joined,monthly_basic,data.get('allowances',[]),working_calendar.working_dates,attendance)
                        earnings+=bonus['amount']
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
                    snapshot=dict(all_present_bonus=bonus,joining_date=joining,lecture_details=lecture_details,plan=data,attendance=breakdown,lectures=[r.id for r in lecture_rows] if data.get('lecture_wise') else [],lecture_pay=lecture_pay,advances=advance_map,basic=base,
                                  base_plan_basic=data['basic'],monthly_basic=monthly_basic,manual_increments=increment_details,proration=proration,
                                  working_calendar=dict(month=m,version=working_calendar.version,working_dates=list(working_calendar.working_dates)) if working_calendar else None)
                    db.session.add(Salary(employee_id=eid,month=m,earnings=earnings,deductions=deductions,net=earnings-deductions,detail=snapshot));count+=1;generated.append(eid)
                if not seen: raise ValueError('Selected employees have no approved salary plans.')
                if request.form.get('generate_sms') and generated:queue('Salary generated',generated,audience='teacher',event='salary-generated',context={'month':m})
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
                if action=='send': queue('Salary paid',[s.employee_id for s in rows],audience='teacher',event='salary-paid',context={'salary_ids':[s.id for s in rows]})
                audit('Salary '+action,ids=ids);commit()
            elif action in ('slip','signature','report','bank'):
                rows=Salary.query.filter(Salary.id.in_(selected())).all()
                if not rows: raise ValueError('Select salaries to print.')
                print_groups={}
                staff={e.id:e for e in Employee.query.filter(Employee.id.in_({s.employee_id for s in rows})).all()}
                staff_details=app.extensions['record_helpers']['raw_many']('employee',list(staff.values()))
                app.extensions['branding_values']['prefetch_employees'](list(staff.values()))
                for salary in rows:print_groups.setdefault(staff_details.get(salary.employee_id,{}).get('campus',''),[]).append(salary)
                group_values={}
                for campus,selected_rows in print_groups.items():
                    values=app.extensions['branding_values']['salary'](selected_rows[0],staff[selected_rows[0].employee_id],staff_details.get(selected_rows[0].employee_id,{})) if len(selected_rows)==1 else {}
                    months=sorted({s.month for s in selected_rows});dates=sorted({s.paid_date.isoformat() for s in selected_rows if s.paid_date})
                    values.update(salary_month=', '.join(months),salary_date=', '.join(dates),total_salary_amount=f'{sum(s.net for s in selected_rows)/100:,.2f}',earnings=f'{sum(s.earnings for s in selected_rows)/100:,.2f}',deductions=f'{sum(s.deductions for s in selected_rows)/100:,.2f}',net_salary=f'{sum(s.net for s in selected_rows)/100:,.2f}')
                    group_values[campus]=values
                return render('salary_print.html',group_values=group_values,print_groups=print_groups,details=lambda p,kind='employee':staff_details.get(p.id,{}),title={'slip':'Salary Slip','signature':'Salary Signature','report':'Salary Report','bank':'Bank Salary Sheet'}[action],rows=rows,employee=lambda id:db.session.get(Employee,id),layout=action)
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

    def communication_screen(fee_mode=False):
        campus=request.values.get('campus','').strip()
        students=people(active=True)
        balances={}
        if fee_mode:
            student_ids=[s.id for s in students]
            for bill in Bill.query.filter(Bill.student_id.in_(student_ids)).all() if student_ids else []:
                if bill.remaining>0:
                    balances[bill.student_id]=balances.get(bill.student_id,0)+bill.remaining
            students=[s for s in students if balances.get(s.id,0)>0]
        default_templates={
            'General announcement':'Dear Parent, please note the latest school announcement. Thank you. {school_name}',
            'PTM invitation':'Dear Parent, you are invited to the Parent Teacher Meeting at {school_name}.',
            'Exam notice':'Dear Parent, please contact {school_name} for the upcoming examination schedule.',
        }
        if fee_mode:
            default_templates={
                'Outstanding fee reminder':'Dear Parent, {student_name} has an outstanding fee of Rs. {remaining_fee} for {fee_month}. Kindly clear the dues. {school_name}',
                'Fee due date':'Dear Parent, please clear the outstanding fee of Rs. {remaining_fee} for {student_name} ({fee_month}). Thank you. {school_name}',
            }
        configured=app.extensions['school_settings_helpers']['config']('exam:sms:'+campus) if campus else {}
        if isinstance(configured,dict):
            default_templates.update({str(k):str(v) for k,v in configured.items() if isinstance(v,str) and v.strip()})
        if request.method=='POST':
            body=request.form.get('message','').strip()
            if not body or len(body)>5000:raise ValueError('Enter a message up to 5000 characters.')
            ids=selected('student_ids')
            valid={s.id for s in students}
            if not ids or any(i not in valid for i in ids):raise ValueError('Select valid recipients from this filtered list.')
            queue(body,ids,context={'type':'fee-intimation' if fee_mode else 'sms-blaster'})
            commit()
            flash('Communication request saved. No SMS was sent: a verified provider is required.','info')
            return redirect(url_for('ops.message_log'))
        return render('messages.html',sms_templates=default_templates,title='Fee Intimation' if fee_mode else 'SMS Blaster',students=students,fee_mode=fee_mode,balances=balances)

    @bp.route('/messages',methods=['GET','POST'])
    def messages():
        return communication_screen(False)

    @bp.route('/fee-intimation',methods=['GET','POST'])
    def fee_intimation():
        return communication_screen(True)

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
            if any(line.get('kind') in ('late_fee','late_fee_forward','attendance_fine') for line in b.lines):raise ValueError('Challans with assessed late fees need manual review before splitting; no fine history was discarded.')
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
            saved=[];changes=[]
            for b in Bill.query.filter(Bill.id.in_([b.id for b in rows])).with_for_update().all():
                value=money(request.form.get('amount_'+str(b.id)))
                if not value: continue
                if b.frozen or value>b.remaining: raise ValueError('Unfreeze challans and enter amounts no greater than the balance.')
                before=dict(paid_paisa=b.paid,remaining_paisa=b.remaining)
                b.paid+=value;changes.append(dict(student_id=b.student_id,bill_id=b.id,before=before,after=dict(paid_paisa=b.paid,remaining_paisa=b.remaining)));receipt=Receipt(student_id=b.student_id,bill_id=b.id,amount=value,discount=0,day=d,account=account,token=token+':'+str(b.id));db.session.add(receipt)
                app.extensions['fee_ledger_helpers']['post'](receipt);saved.append(b.student_id)
            if not saved: raise ValueError('Enter at least one payment amount.')
            if request.form.get('action')=='send': queue('Fee receipt',list(set(saved)))
            audit('Family payment' if family_mode else 'Direct payment',students=saved,changes=changes);commit();flash('Payments saved.','success');return redirect(url_for('ops.history'))
        return render('batch_payment.html',title='Family-wise Payment' if family_mode else 'Direct Payment',family_mode=family_mode,number=query,lookup=lookup,rows=rows,student=lambda id:db.session.get(Student,id),line_remaining={b.id:payment_particulars(b) for b in rows},token=secrets.token_urlsafe(24))

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
    def readiness():
        return render('readiness.html',title='System Check & Testing',storage_backend=db.session.get_bind(mapper=Student.__mapper__).dialect.name,identity_backend=app.extensions['identity_helpers']['control_engine']().dialect.name)

    def dashboard_data():
        # Keep request work independent of pupil/score count: no per-row ORM
        # lookups, no attachment/salary/certificate payloads, and one pass over
        # scalar financial rows rather than rescanning receipts per month.
        today=school_today();month_key=today.strftime('%Y-%m')
        student_count,active=db.session.query(db.func.count(Student.id),db.func.sum(case((Student.status=='Active',1),else_=0))).one()
        employee_count,active_employees=db.session.query(db.func.count(Employee.id),db.func.sum(case((Employee.status=='Active',1),else_=0))).one()
        class_label=db.func.coalesce(db.func.nullif(Student.class_name,''),'Unassigned')
        classes=Counter(dict(db.session.query(class_label,db.func.count(Student.id)).filter(Student.status=='Active').group_by(class_label).order_by(class_label).all()))
        attendance=Counter(dict(db.session.query(Daily.status,db.func.count(Daily.id)).filter(Daily.kind=='student',Daily.day==today).group_by(Daily.status).all()))
        staff_counts=Counter(dict(db.session.query(Daily.status,db.func.count(Daily.id)).filter(Daily.kind=='staff',Daily.day>=today.replace(day=1),Daily.day<=today).group_by(Daily.status).all()))
        pending,queries=db.session.query(db.func.sum(case((Workflow.status=='Pending',1),else_=0)),db.func.sum(case((Workflow.kind=='queries',1),else_=0))).one()
        bill_months={};billed=Counter();remaining_months=Counter();due=0;unpaid=0;defaulters=set()
        for row in db.session.query(Bill.id,Bill.student_id,Bill.month,Bill.lines,Bill.paid,Bill.discount).all():
            total=sum(line['amount'] for line in row.lines);remaining=total-row.paid-row.discount
            bill_months[row.id]=row.month;billed[row.month]+=total;remaining_months[row.month]+=remaining;due+=remaining
            if remaining>0:unpaid+=1;defaulters.add(row.student_id)
        collected=this_month=discount=0;by_bill_month=Counter()
        for row in db.session.query(Receipt.bill_id,Receipt.amount,Receipt.discount,Receipt.day).filter(Receipt.voided==False).all():
            collected+=row.amount;discount+=row.discount
            if str(row.day)[:7]==month_key:this_month+=row.amount
            by_bill_month[bill_months.get(row.bill_id)]+=row.amount
        scores=db.session.query(Score.award_id,Score.paper,Score.obtained).filter(Score.obtained!=None).all()
        award_ids=list({row.award_id for row in scores});papers={}
        for offset in range(0,len(award_ids),900):
            papers.update({row.id:row.data['papers'] for row in db.session.query(Workflow.id,Workflow.data).filter(Workflow.id.in_(award_ids[offset:offset+900])).all()})
        scores=[row for row in scores if row.award_id in papers and 0<=row.paper<len(papers[row.award_id]) and papers[row.award_id][row.paper].get('grading','Marks')=='Marks' and papers[row.award_id][row.paper]['total']>0]
        average=round(sum(row.obtained/papers[row.award_id][row.paper]['total']*100 for row in scores)/len(scores),1) if scores else 0
        months=[(f'{today.year}-{number:02d}',billed[f'{today.year}-{number:02d}'],by_bill_month[f'{today.year}-{number:02d}']) for number in range(1,today.month+1)]
        return dict(students=student_count,active=active or 0,employees=employee_count,active_employees=active_employees or 0,
                    present=attendance['Present'],marked=sum(attendance.values()),attendance=attendance,staff_counts=staff_counts,
                    collected=collected,this_month=this_month,due=due,discount=discount,unpaid=unpaid,defaulters=len(defaulters),
                    pending=pending or 0,queries=queries or 0,average=average,classes=classes,months=months,remaining_months=dict(remaining_months))

    @bp.route('/dashboard')
    def dashboard():
        target=app.extensions.get('general_tools_helpers',{}).get('default_url',lambda:None)()
        if target:return redirect(target)
        return app.extensions['dashboard_render']()

    @app.route('/healthz')
    def health():
        db.session.execute(db.text('SELECT 1'))
        if app.extensions.get('identity_bind_key'):
            with app.extensions['identity_helpers']['control_engine']().connect() as connection:connection.execute(db.text('SELECT 1'))
        response = jsonify(status='ok',build='schoolflow-system-audit-v38')
        response.headers['Cache-Control'] = 'no-store'
        response.vary.add('Origin')
        if request.headers.get('Origin') == 'https://schoolflow-start.onrender.com':
            response.headers['Access-Control-Allow-Origin'] = 'https://schoolflow-start.onrender.com'
        return response

    @app.route('/api/v1/summary')
    def summary_api():
        key=app.config.get('SCHOOLFLOW_API_TOKEN')
        if not key: return jsonify(error='API access is not configured'),503
        if not hmac.compare_digest(request.headers.get('Authorization',''),'Bearer '+key): abort(401)
        # Owner-only aggregate foundation. No unrestricted pupil/employee endpoint.
        return jsonify(dashboard_data())

    app.register_blueprint(bp)
    app.extensions['operation_helpers']=dict(details=details,dashboard=dashboard_data)
