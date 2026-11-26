"""Owner-only scheduled report notices, derived from actual tenant records.

Reports can be captured by the existing scheduler and read from the inbox.
External delivery is opt-in. All amounts remain integer paisa.
"""
from datetime import datetime,timedelta
from collections import Counter
import re,hashlib
from flask import Blueprint,abort,flash,g,redirect,render_template,request,session,url_for
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import StaleDataError
from school_clock import SCHOOL_TIMEZONE
from workspace_actor import csrf

REPORTS=(
    ('fee-received','Fee Collection','daily','20:00'),
    ('fee-forecast','Next Month Fee Forecast','monthly','08:00'),
    ('fee-due','Monthly Billed Fee & Outstanding','monthly','08:00'),
    ('student-attendance','Student Attendance Summary','daily','14:00'),
    ('staff-attendance','Staff Attendance & Absences','daily','14:00'),
    ('salary-due','Generated Salary Payable','monthly','08:00'),
    ('income-expense','Income & Expenses','daily','14:00'),
)
KEY='automatic-owner-reports'
def money(value):return 'Rs. {:,.2f}'.format(value/100)

def period(now,frequency,clock):
    today=now.date()
    start=today if frequency=='daily' else today-timedelta(days=today.weekday()) if frequency=='weekly' else today.replace(day=1)
    # Each new period is available after the selected local clock time.
    if now.strftime('%H:%M')<clock and today==start:return None
    return start,today

def configure_automatic_reports(app,db,Student,Employee):
    bp=Blueprint('automatic_reports',__name__,url_prefix='/workspace/core/automatic-reports')
    Setting=app.extensions['school_settings_models']['setting'];ops=app.extensions['ops_models']
    def owner():
        return bool(session.get('owner_id') and not session.get('staff_id') and not session.get('demo') and not getattr(g,'staff_principal',None) and getattr(g,'school_identity',None))
    def settings():
        row=db.session.get(Setting,KEY)
        data=row.data if row else {}
        return row,{k:{'enabled':not row and k=='fee-received','frequency':f,'time':t,**data.get(k,{})} for k,_,f,t in REPORTS}
    def summary(key,start,end):
        Bill=ops['bill'];Receipt=ops['receipt'];Daily=ops['daily'];Salary=ops['salary']
        if key=='fee-received':
            rows=Receipt.query.filter(Receipt.voided==False,Receipt.day>=start,Receipt.day<=end).all()
            return ('No fee received · ' if not any(r.amount>0 for r in rows) else '')+'Received '+money(sum(r.amount for r in rows))+' · Discounts '+money(sum(r.discount for r in rows))+' · '+str(len(rows))+' receipts'
        if key=='fee-forecast':
            # Use exactly the automatic generation rules and effective dated
            # assigned plans; never generate a bill or claim arrears here.
            target=(end.replace(day=1)+timedelta(days=32)).replace(day=1).strftime('%Y-%m')
            Plan=app.extensions['student_fee_plan_model'];helper=app.extensions['fee_setup_helpers']
            active={s.id for s in Student.query.filter_by(status='Active').all()}
            plans={}
            for p in Plan.query.filter(Plan.effective<=target).order_by(Plan.effective.desc(),Plan.id.desc()):
                if p.student_id in active:plans.setdefault(p.student_id,p)
            billed=set();first_before=set();arrears=0;existing=0
            for b in Bill.query.filter(Bill.month<=target):
                if b.month==target:
                    billed.add(b.student_id);existing+=b.total-b.discount
                else:
                    first_before.add(b.student_id)
                    arrears+=max(0,b.remaining)
            projected=0;covered=0;manual=0
            for sid,p in plans.items():
                if sid in billed:continue
                covered+=1
                for line in p.data.get('lines',[]):
                    rule=helper['effective_rule'](line['particular'],line)
                    if rule['timing'] in ('manual','fine'):
                        manual+=int(bool(line.get('net')))
                        continue
                    if line.get('net') and helper['eligible'](rule,target,sid not in first_before,False):
                        projected+=line['net']
            return target+' · Existing net challans '+money(existing)+' · Estimated ungenerated '+money(projected)+' · Estimated total '+money(existing+projected)+' · Prior outstanding '+money(arrears)+' · '+str(covered)+' unbilled assigned plans · '+str(len(active-set(plans)-billed))+' active students without an assigned plan · '+str(manual)+' manual/fine lines excluded. Excludes optional first-time arrears and future changes.'
        if key=='fee-due':
            month=end.strftime('%Y-%m')
            rows=Bill.query.filter(Bill.month<=month).all();current=[r for r in rows if r.month==month]
            arrears=sum(max(0,r.remaining) for r in rows if r.month<month)
            return 'Generated challans '+money(sum(r.total for r in current))+' · Discounts '+money(sum(r.discount for r in current))+' · Paid '+money(sum(r.paid for r in current))+' · Current outstanding '+money(sum(max(0,r.remaining) for r in current))+' · Prior arrears '+money(arrears)+' (excludes ungenerated fees)'
        if key in ('student-attendance','staff-attendance'):
            kind='student' if key=='student-attendance' else 'staff'
            counts=Counter(r.status for r in Daily.query.filter(Daily.kind==kind,Daily.day>=start,Daily.day<=end).all())
            return 'Recorded attendance entries: '+(' · '.join(str(k)+' '+str(v) for k,v in sorted(counts.items())) if counts else 'None saved')+' (unmarked is not absent)'
        if key=='salary-due':
            rows=Salary.query.filter_by(month=end.strftime('%Y-%m')).all()
            return 'Generated payroll '+money(sum(r.net for r in rows))+' · Paid '+money(sum(r.paid for r in rows))+' · Outstanding '+money(sum(max(0,r.net-r.paid) for r in rows))+' · '+str(len(rows))+' generated salaries'
        J=app.extensions['ledger_models']['journal'];L=app.extensions['ledger_models']['line']
        income=expense=0
        for snapshot,debit,credit in db.session.query(L.snapshot,L.debit,L.credit).join(J,J.id==L.journal_id).filter(J.day>=start,J.day<=end):
            if snapshot.get('account_class')=='Income':income+=credit-debit
            elif snapshot.get('account_class')=='Expense':expense+=debit-credit
        return 'Income '+money(income)+' · Expenses '+money(expense)+' · Net '+money(income-expense)
    W=ops['workflow']
    def due_reports(now=None):
        now=now or datetime.now(SCHOOL_TIMEZONE)
        _,rules=settings();out=[]
        for key,label,_,_ in REPORTS:
            rule=rules[key]
            if not rule['enabled']:continue
            dates=period(now,rule['frequency'],rule['time'])
            if not dates:continue
            start,end=dates
            out.append(dict(key='auto-report:'+key,revision=rule['frequency']+':'+str(start),title=label,detail=str(start)+' to '+str(end)+' · '+summary(key,start,end),url=url_for('automatic_reports.index')))
        return out
    def events(now=None):
        if not owner():return []
        return due_reports(now)
    def capture(now=None):
        now=now or datetime.now(SCHOOL_TIMEZONE)
        # Serialize with all other tenant mutations; stable per-period keys
        # prevent repeat snapshots across gunicorn workers and restarts.
        row,rules=settings()
        if not any(rule['enabled'] for rule in rules.values()):return 0
        app.extensions['admission_capacity']['lock']()
        saved=W.query.filter_by(kind='automatic-report-snapshot',status='Active').all()
        seen={(r.data.get('key'),r.data.get('revision')) for r in saved}
        count=0
        current_events=due_reports(now)
        current_keys={(event['key'],event['revision']) for event in current_events}
        for event in current_events:
            if (event['key'],event['revision']) in seen:continue
            db.session.add(W(kind='automatic-report-snapshot',status='Active',data={**event,'captured':now.isoformat()}));count+=1
        if count:
            # Keep bounded history and never store external credentials here.
            expired=[r for r in saved if (r.data.get('key'),r.data.get('revision')) not in current_keys]
            for old in sorted(expired,key=lambda r:r.id,reverse=True)[90:]:db.session.delete(old)
        db.session.commit()
        return count
    WA_KEY='automatic-report-whatsapp'
    def wa_config():
        row=db.session.get(Setting,WA_KEY)
        return row,row.data if row else {}
    def wa_options():
        return app.extensions['whatsapp_helpers']['report_options']()
    def wa_send(now=None):
        row,cfg=wa_config()
        if not cfg.get('enabled'):return
        helper=app.extensions['whatsapp_helpers']
        if not any(o['provider']==cfg.get('provider') and o['id']==cfg.get('device') for o in wa_options()):return
        mobile=helper['decrypt'](cfg['recipient'])
        # Only the current enabled reports; no replay of older saved history.
        # Stable report period + recipient consent, with provider-side claim before network.
        for event in due_reports(now):
            # Durable per-report claim remains even when provider history is pruned.
            # Commit the claim first; uncertain external results are not retried.
            app.extensions['admission_capacity']['lock']()
            latest=db.session.get(Setting,WA_KEY,populate_existing=True)
            if not latest or latest.data!=cfg:db.session.rollback();break
            claim_key='automatic-wa-claim:'+event['key']
            claim=db.session.get(Setting,claim_key,populate_existing=True)
            if claim and claim.data.get('revision')==event['revision']:db.session.rollback();continue
            claim=claim or Setting(key=claim_key)
            claim.data=dict(revision=event['revision'],status='Pending')
            db.session.add(claim);db.session.commit()
            token=hashlib.sha256(('scheduled-report:'+event['key']+':'+event['revision']).encode()).hexdigest()
            outcome=helper['send_report'](token,cfg['device'],cfg['provider'],mobile,event['title']+'\n'+event['detail'])
            app.extensions['admission_capacity']['lock']()
            claim=db.session.get(Setting,claim_key,populate_existing=True)
            if claim and claim.data.get('revision')==event['revision']:claim.data={**claim.data,'status':outcome}
            db.session.commit()
    @bp.post('/whatsapp')
    def whatsapp():
        if not owner():abort(403)
        csrf();app.extensions['admission_capacity']['lock']()
        row,cfg=wa_config()
        if request.form.get('version')!=str(row.version if row else 0):abort(409,'Settings changed. Reload first.')
        if request.form.get('action')=='disable':
            if row:row.data={'enabled':False}
        elif request.form.get('action')=='enable':
            device=request.form.get('device','');provider=request.form.get('provider',type=int)
            mobile=request.form.get('mobile','').strip()
            if not any(o['provider']==provider and o['id']==device for o in wa_options()):abort(422,'Link and enable the selected WhatsApp provider first.')
            if not re.fullmatch('[1-9][0-9]{7,14}',mobile) or request.form.get('consent')!='yes':abort(422,'Confirm that you control this WhatsApp number and consent to school financial summaries.')
            row=row or Setting(key=WA_KEY)
            row.data=dict(enabled=True,provider=provider,device=device,recipient=app.extensions['whatsapp_helpers']['encrypt'](mobile))
            db.session.add(row)
        else:abort(422)
        db.session.add(ops['audit'](action='Change scheduled WhatsApp report consent',data={'enabled':request.form.get('action')=='enable'}))
        db.session.commit()
        flash('WhatsApp report settings saved. No immediate message was sent.','success')
        return redirect(url_for('automatic_reports.index'))
    def tick_all():
        with app.app_context():
            School=app.extensions['identity_models']['institute']
            schools=[(s.id,s.storage_key) for s in School.query.filter_by(active=True).all()];db.session.remove()
            for sid,scope in schools:
                with app.test_request_context('/internal/automatic-reports'):
                    try:
                        g.institute_engine=app.extensions['identity_helpers']['engine'](sid)
                        g.school_identity=dict(scope=scope,demo=False)
                        capture()
                        wa_send()
                    except Exception:
                        db.session.rollback();app.logger.exception('Automatic report worker failed for institute %s',sid)
                    finally:db.session.remove();g.pop('institute_engine',None)
    @app.cli.command('automatic-reports-tick')
    def tick_cli():
        tick_all()
    def assignments():
        return [r for r in W.query.filter_by(kind='teacher-classes',status='Active').order_by(W.id) if all(r.data.get(k) for k in ('employee_id','campus','class_name','section')) and str(r.data['employee_id']).isdigit()]
    def period_subjects(assignment):
        # Explicit subject assignments remain restricted to that subject.
        if assignment.get('subject'):return [assignment['subject']]
        allowed=app.extensions['school_settings_helpers']['subject_allowed']
        Catalog=app.extensions['record_models']['settings'];cls=assignment['class_name']
        return sorted({r.value for r in Catalog.query.filter_by(category='subject').all() if (not r.class_name or r.class_name==cls) and allowed(assignment['campus'],cls,r.value)},key=str.casefold)
    def period_rows():
        return W.query.filter_by(kind='automatic-period-reminder',status='Active').order_by(W.id).all()
    def teacher_timetable(cohorts):
        """Recurring weekly periods for the exact active, permitted assignments."""
        allowed={r.id:r.data for r in cohorts}
        out=[];catalog={}
        for row in period_rows():
            d=row.data;a=allowed.get(d.get('assignment_id'))
            if not a or a!=d.get('assignment'):continue
            weekday=d.get('weekday');clock=d.get('time','');lead=d.get('lead')
            if weekday not in range(7):continue
            scope=dict(weekday=weekday,campus=a['campus'],class_name=a['class_name'],section=a['section'])
            if d.get('mode')=='full-class':
                if not a.get('subject') and not d.get('subject'):
                    out.append(dict(scope,time='All day',subject='Full Class',lead=0,mode='full-class'))
                continue
            if d.get('mode','lecture')!='lecture' or lead not in (0,5,10,15,30) or not isinstance(clock,str) or not re.fullmatch(r'(?:[01][0-9]|2[0-3]):[0-5][0-9]',clock):continue
            subject=d.get('subject') or a.get('subject') or ''
            if a.get('subject'):
                if subject!=a['subject']:continue
            elif subject:
                aid=d['assignment_id']
                if aid not in catalog:catalog[aid]=period_subjects(a)
                if subject not in catalog[aid]:continue
            out.append(dict(scope,time=clock,subject=subject or 'Class period',lead=lead,mode='lecture'))
        return sorted(out,key=lambda r:(r['weekday'],r['mode']!='full-class',r['time'],r['campus'],r['class_name'],r['section'],r['subject']))
    def teacher_periods(cohorts,now=None):
        now=now or datetime.now(SCHOOL_TIMEZONE)
        day=now.date();minute=now.hour*60+now.minute
        out=[];holidays=app.extensions['holiday_calendar_helpers']['rows']()
        for p in teacher_timetable(cohorts):
            if p['mode']!='lecture' or p['weekday']!=day.weekday():continue
            if any(h.scope in ('',p['campus']) and (h.data['date'][5:]==day.strftime('%m-%d') if h.data.get('repeats') else h.data['date']==day.isoformat()) for h in holidays):continue
            hour,m=map(int,p['time'].split(':'));start=hour*60+m
            if start<minute:continue
            out.append(dict(p,due=minute>=start-p['lead']))
        return out
    @bp.post('/periods')
    def periods():
        if not owner():abort(403)
        csrf();app.extensions['admission_capacity']['lock']()
        action=request.form.get('action')
        if action in ('add','add_full_class'):
            raw=request.form.get('assignment_id','');assignment_id,separator,subject=raw.partition(':')
            aid=int(assignment_id) if assignment_id.isascii() and assignment_id.isdigit() and len(assignment_id)<=18 else None
            assignment=next((r for r in assignments() if r.id==aid),None)
            if not assignment:abort(422,'Choose an active teacher class assignment.')
            if separator and (assignment.data.get('subject') or not subject or subject not in period_subjects(assignment.data)):abort(422,'Choose a configured subject for this class.')
            employee=db.session.get(Employee,int(assignment.data['employee_id']))
            if not employee or employee.status!='Active':abort(422,'Choose an active teacher.')
            rows=period_rows()
            if action=='add_full_class':
                if separator or assignment.data.get('subject'):abort(422,'Full Class requires an active class-only assignment.')
                supplied=request.form.getlist('weekdays')
                if not supplied or any(day not in ('0','1','2','3','4','5','6') for day in supplied):abort(422,'Select at least one valid weekday.')
                days=sorted(set(map(int,supplied)))
                active={r.id:r.data for r in assignments()}
                existing=set()
                for row in rows:
                    d=row.data;a=active.get(d.get('assignment_id'))
                    if d.get('mode')!='full-class' or not a or a!=d.get('assignment') or a.get('subject') or str(a['employee_id'])!=str(assignment.data['employee_id']) or d.get('weekday') not in days:continue
                    if row.data['assignment_id']!=aid:abort(409,'This teacher already has another Full Class on a selected day. Change the class schedule first.')
                    existing.add(d['weekday'])
                new_days=[day for day in days if day not in existing]
                if len(rows)+len(new_days)>500:abort(422,'Remove unused timetable entries before adding more.')
                for day in new_days:
                    db.session.add(W(kind='automatic-period-reminder',status='Active',data=dict(mode='full-class',assignment_id=aid,assignment=dict(assignment.data),weekday=day,time='',lead=0)))
                if new_days:db.session.add(ops['audit'](action='Create full class schedule',data={'assignment_id':aid,'weekdays':new_days}))
                flash(f'{len(new_days)} full-class day(s) saved. {len(existing)} already scheduled; no duplicates created.','success')
                db.session.commit();return redirect(url_for('automatic_reports.index'))
            # New weekly submissions select multiple days. Retain the original
            # single-day field for existing clients and their conflict behaviour.
            supplied=request.form.getlist('weekdays');legacy=not supplied and 'weekday' in request.form
            if legacy:supplied=request.form.getlist('weekday')
            if not supplied or any(day not in ('0','1','2','3','4','5','6') for day in supplied) or (legacy and len(supplied)!=1):abort(422,'Select at least one valid weekday.')
            days=sorted(set(map(int,supplied)))
            lead=request.form.get('lead',type=int);clock=request.form.get('time','')
            if lead not in (0,5,10,15,30) or not re.fullmatch(r'(?:[01][0-9]|2[0-3]):[0-5][0-9]',clock):abort(422,'Choose a period start and reminder lead time.')
            # Check every selected day before creating anything. A replay of the
            # exact same lecture in the weekly form is harmless; a different
            # lecture at the same teacher/day/start rejects the whole batch.
            existing=set();selected_subject=subject if separator else assignment.data.get('subject') or ''
            for row in rows:
                d=row.data;snapshot=d.get('assignment',{})
                if d.get('mode','lecture')!='lecture' or str(snapshot.get('employee_id'))!=str(assignment.data['employee_id']) or d.get('weekday') not in days or d.get('time')!=clock:continue
                same=(d.get('assignment_id')==aid and snapshot==assignment.data and (d.get('subject') or snapshot.get('subject') or '')==selected_subject and d.get('lead')==lead)
                if legacy or not same:abort(409,'A different or existing period for this teacher already starts at that time on a selected day. No timetable entries were changed.')
                existing.add(d['weekday'])
            new_days=[day for day in days if day not in existing]
            if len(rows)+len(new_days)>500:abort(422,'Remove unused periods before adding more.')
            for day in new_days:
                db.session.add(W(kind='automatic-period-reminder',status='Active',data=dict(mode='lecture',assignment_id=aid,assignment=dict(assignment.data),weekday=day,time=clock,lead=lead,**({'subject':subject} if separator else {}))))
                db.session.add(ops['audit'](action='Create period reminder',data={'assignment_id':aid,'weekday':day,'time':clock}))
            flash(f'{len(new_days)} lecture day(s) saved. {len(existing)} already scheduled; no duplicates created.','success')
        elif action=='remove':
            row=W.query.filter_by(kind='automatic-period-reminder',status='Active',id=request.form.get('id',type=int)).first_or_404()
            row.status='Voided';db.session.add(ops['audit'](action='Remove full class schedule' if row.data.get('mode')=='full-class' else 'Remove period reminder',data={'id':row.id}))
        else:abort(422)
        db.session.commit();return redirect(url_for('automatic_reports.index'))
    @bp.route('',methods=['GET','POST'])
    def index():
        if not owner():abort(403)
        if request.method=='POST':
            csrf()
            app.extensions['admission_capacity']['lock']()
            row,rules=settings()
            if request.form.get('version')!=str(row.version if row else 0):abort(409,'Settings changed. Reload first.')
            for key,_,_,_ in REPORTS:
                freq=request.form.get(key+'_frequency','')
                clock=request.form.get(key+'_time','')
                if freq not in ('daily','weekly','monthly') or not re.fullmatch(r'(?:[01][0-9]|2[0-3]):[0-5][0-9]',clock):abort(422,'Choose a valid report frequency and time.')
                rules[key]=dict(enabled=request.form.get(key+'_enabled')=='on',frequency=freq,time=clock)
            row=row or Setting(key=KEY);row.data=rules;db.session.add(row)
            db.session.add(ops['audit'](action='Save automatic report settings',data={'enabled':[k for k,v in rules.items() if v['enabled']]}))
            try:db.session.commit()
            except (IntegrityError,StaleDataError):db.session.rollback();abort(409,'Settings changed. Reload first.')
            flash('Automatic report settings saved.','success')
            return redirect(url_for('automatic_reports.index'))
        row,rules=settings();active_assignments=assignments()
        return render_template('automatic_reports.html',title='Automatic Reports & Notifications',catalog=REPORTS,rules=rules,version=row.version if row else 0,events=events(),history=W.query.filter_by(kind='automatic-report-snapshot',status='Active').order_by(W.id.desc()).limit(30).all(),worker=bool(app.config.get('FINE_WORKER_ENABLED')),periods=period_rows(),assignments=active_assignments,assignment_subjects={a.id:period_subjects(a.data) for a in active_assignments if not a.data.get('subject')},employees={str(e.id):e.name for e in Employee.query.filter_by(status='Active').all()},weekdays=('Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday'),wa_options=wa_options(),wa_enabled=wa_config()[1].get('enabled',False),wa_version=wa_config()[0].version if wa_config()[0] else 0)
    @bp.after_request
    def private(response):
        response.headers['Cache-Control']='no-store';return response
    app.extensions['automatic_report_events']=events
    app.extensions['automatic_report_helpers']=dict(capture=capture,tick_all=tick_all,teacher_periods=teacher_periods,teacher_timetable=teacher_timetable,wa_send=wa_send)
    app.register_blueprint(bp)
