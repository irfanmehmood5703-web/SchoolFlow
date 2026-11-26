"""Owner-only scheduled report notices, derived from actual tenant records.

Reports can be captured by the existing scheduler and read from the inbox.
External delivery is opt-in. All amounts remain integer paisa.
"""
from datetime import datetime,timedelta
from collections import Counter
import re,hashlib,json
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
WEEKDAYS=('Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday')
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
    def lecture_catalog(active_assignments):
        """Owner's configured academic scopes, not just existing teacher assignments."""
        Catalog=app.extensions['record_models']['settings']
        config=app.extensions['institute_setup_helpers']['payload'](refresh=request.method=='POST')
        rows=Catalog.query.order_by(Catalog.value).all()
        values=lambda category:{r.value for r in rows if r.category==category}
        order={v:i for i,v in enumerate(('Montessori','Play','Nursery','KG-I','KG-II','One','Two','Three','Four','Five','Six','Seven','Eight','Nine','Ten','Tenth'))}
        schools=[];allowed=app.extensions['school_settings_helpers']['subject_allowed']
        for campus in sorted(values('campus'),key=str.casefold):
            if config['campuses'].get(campus) is False:continue
            mapped=config['maps'].get(campus)
            scopes={c['class_name']:c.get('sections',[]) for c in mapped} if mapped is not None else {c:values('section') for c in values('class_name')}
            classes=[]
            for cls,sections in sorted(scopes.items(),key=lambda x:(order.get(x[0],1000),x[0].casefold())):
                sections=sorted(set(sections)&values('section'),key=str.casefold)
                if not sections or cls not in values('class_name'):continue
                subjects=sorted({r.value for r in rows if r.category=='subject' and (not r.class_name or r.class_name==cls) and allowed(campus,cls,r.value)},key=str.casefold)
                classes.append(dict(name=cls,sections=sections,subjects=subjects))
            if classes:schools.append(dict(name=campus,classes=classes))
        Staff=app.extensions['staff_account_model']
        accounts={str(r.employee_id):r for r in Staff.query.all()}
        teachers=[]
        for employee in Employee.query.filter_by(status='Active').order_by(Employee.name,Employee.id):
            if 'teacher' not in (employee.role or '').lower():continue
            eid=str(employee.id);account=accounts.get(eid)
            campuses=[c['name'] for c in schools if account is None or c['name'] in account.data.get('campuses',[])]
            teachers.append(dict(id=eid,name=employee.name,campuses=campuses))
        full=[dict(teacher=str(a.data['employee_id']),campus=a.data['campus'],class_name=a.data['class_name'],section=a.data['section']) for a in active_assignments if not a.data.get('subject')]
        return dict(teachers=teachers,campuses=schools,full_classes=full)
    def period_rows():
        return W.query.filter_by(kind='automatic-period-reminder',status='Active').order_by(W.id).all()
    def period_group_key(data):
        # Identical recurring schedules can be represented by old or new rows.
        # Group by the exact assignment, subject, start time and reminder; never
        # combine different subjects, teachers, sections or times.
        assignment=data.get('assignment',{})
        mode=data.get('mode','lecture')
        return json.dumps([mode,data.get('assignment_id'),assignment,
                           data.get('subject') or assignment.get('subject') or '',
                           data.get('time','') if mode=='lecture' else '',
                           data.get('lead') if mode=='lecture' else 0],sort_keys=True,ensure_ascii=False)
    def clock_label(clock):
        if not isinstance(clock,str) or not re.fullmatch(r'(?:[01][0-9]|2[0-3]):[0-5][0-9]',clock):return 'Invalid time'
        hour,minute=map(int,clock.split(':'))
        return f'{hour%12 or 12}:{minute:02d} {"AM" if hour<12 else "PM"}'
    def timetable_groups(rows,employees):
        groups={}
        for row in rows:groups.setdefault(period_group_key(row.data),[]).append(row)
        out=[]
        for members in groups.values():
            members.sort(key=lambda r:(r.data.get('weekday',7),r.id))
            row=members[0];d=row.data;a=d.get('assignment',{})
            full=d.get('mode')=='full-class'
            out.append(dict(id=row.id,rows=members,teacher=employees.get(str(a.get('employee_id')),'Inactive teacher'),
                            campus=a.get('campus',''),class_name=a.get('class_name',''),section=a.get('section',''),
                            subject='Full Class' if full else d.get('subject') or a.get('subject') or 'Class period',
                            full=full,time='All day' if full else clock_label(d.get('time')),
                            lead=d.get('lead',0),days=sorted({r.data['weekday'] for r in members if r.data.get('weekday') in range(7)})))
        return sorted(out,key=lambda group:(group['teacher'].casefold(),not group['full'],group['rows'][0].data.get('time',''),group['campus'],group['class_name'],group['section'],group['subject']))
    @bp.route('/periods/<int:pid>/edit',methods=['GET','POST'])
    def edit_period(pid):
        if not owner():abort(403)
        csrf()
        if request.method=='POST':app.extensions['admission_capacity']['lock']()
        rows=period_rows()
        anchor=next((r for r in rows if r.id==pid),None)
        if not anchor:abort(404 if request.method=='GET' else 409,'This timetable entry has changed. Reload the saved timetable.')
        single=request.args.get('scope')=='day'
        members=[anchor] if single else [r for r in rows if period_group_key(r.data)==period_group_key(anchor.data)]
        revision=hashlib.sha256(json.dumps([(r.id,r.data) for r in members],sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        data=anchor.data;a=data.get('assignment',{});mode=data.get('mode','lecture')
        active={r.id:r.data for r in assignments()}
        aid=data.get('assignment_id');employee=db.session.get(Employee,int(a['employee_id'])) if str(a.get('employee_id','')).isdigit() else None
        subject=data.get('subject') or a.get('subject') or ''
        valid_subject=(subject==a.get('subject') if a.get('subject') else not subject or subject in period_subjects(a)) if aid in active and a==active[aid] else False
        if not employee or employee.status!='Active' or not valid_subject or mode not in ('lecture','full-class') or (mode=='full-class' and subject):
            abort(409,'This teacher or assignment is no longer active. Review the class assignment before editing; you can still remove an unused timetable entry.')
        old_days={r.data['weekday'] for r in members}
        if request.method=='POST':
            if request.form.get('revision')!=revision:abort(409,'This timetable changed since you opened it. Reload before saving.')
            supplied=request.form.getlist('weekdays')
            if not supplied or any(d not in ('0','1','2','3','4','5','6') for d in supplied) or (single and len(set(supplied))!=1):
                abort(422,'Select one valid weekday for a day edit, or at least one weekday for a weekly edit.')
            days=sorted(set(map(int,supplied)))
            if mode=='lecture':
                hour=request.form.get('hour',type=int);minute=request.form.get('minute',type=int);meridiem=request.form.get('meridiem')
                lead=request.form.get('lead',type=int)
                if hour not in range(1,13) or minute not in range(60) or meridiem not in ('AM','PM') or lead not in (0,5,10,15,30):
                    abort(422,'Choose a valid hour, minute, AM/PM and reminder.')
                clock=f'{hour%12+(12 if meridiem=="PM" else 0):02d}:{minute:02d}'
            else:clock='';lead=0
            selected_ids={r.id for r in members}
            for r in rows:
                d=r.data;snapshot=d.get('assignment',{})
                if r.id in selected_ids or str(snapshot.get('employee_id'))!=str(a.get('employee_id')) or d.get('weekday') not in days:continue
                if mode=='lecture' and d.get('mode','lecture')=='lecture' and d.get('time')==clock:
                    abort(409,'This teacher already has a lecture at the selected time on one of these days. Nothing was changed.')
                if mode=='full-class' and d.get('mode')=='full-class' and active.get(d.get('assignment_id'))==snapshot:
                    abort(409,'This teacher already has Full Class on a selected day. Nothing was changed.')
            if len(rows)-len(members)+len(days)>500:abort(422,'Remove unused timetable entries before adding more.')
            before=[dict(id=r.id,data=dict(r.data)) for r in members]
            # Keep IDs on unchanged weekdays; retire only unchecked days and
            # add newly selected days. The academic assignment is never changed.
            unused={r.id:r for r in members}
            after=[]
            for day in days:
                row=next((r for r in unused.values() if r.data.get('weekday')==day),None)
                if row is None and single:row=anchor
                updated={**data,'mode':mode,'weekday':day,'time':clock,'lead':lead}
                if row is not None:
                    unused.pop(row.id,None);row.data=updated
                else:
                    row=W(kind='automatic-period-reminder',status='Active',data=updated);db.session.add(row);db.session.flush()
                after.append(dict(id=row.id,data=updated))
            for row in unused.values():row.status='Voided'
            db.session.add(ops['audit'](action='Edit teacher timetable',data={'scope':'day' if single else 'weekly','before':before,'after':after}))
            db.session.commit()
            flash('Timetable updated successfully. The Teacher App will show the new schedule.','success')
            return redirect(url_for('automatic_reports.index',_anchor='saved-timetable'))
        clock=data.get('time','')
        hour,minute=map(int,clock.split(':')) if mode=='lecture' and isinstance(clock,str) and re.fullmatch(r'(?:[01][0-9]|2[0-3]):[0-5][0-9]',clock) else (8,0)
        return render_template('timetable_edit.html',title='Edit timetable',teacher=employee.name,assignment=a,subject=subject or ('Full Class' if mode=='full-class' else 'Class period'),full=mode=='full-class',single=single,days=old_days,weekdays=WEEKDAYS,revision=revision,hour=hour%12 or 12,minute=minute,meridiem='AM' if hour<12 else 'PM',lead=data.get('lead',5),time_label='All day' if mode=='full-class' else clock_label(clock))
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
                    out.append(dict(scope,time='All day',time_label='All day',subject='Full Class',lead=0,mode='full-class'))
                continue
            if d.get('mode','lecture')!='lecture' or lead not in (0,5,10,15,30) or not isinstance(clock,str) or not re.fullmatch(r'(?:[01][0-9]|2[0-3]):[0-5][0-9]',clock):continue
            subject=d.get('subject') or a.get('subject') or ''
            if a.get('subject'):
                if subject!=a['subject']:continue
            elif subject:
                aid=d['assignment_id']
                if aid not in catalog:catalog[aid]=period_subjects(a)
                if subject not in catalog[aid]:continue
            out.append(dict(scope,time=clock,time_label=clock_label(clock),subject=subject or 'Class period',lead=lead,mode='lecture'))
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
    def teacher_lecture_alerts(cohorts,now=None):
        """Next two days of authorised, dated lecture alerts for device alarms."""
        now=now or datetime.now(SCHOOL_TIMEZONE)
        horizon=now+timedelta(days=2)
        holidays=app.extensions['holiday_calendar_helpers']['rows']()
        timetable=teacher_timetable(cohorts)
        alerts=[]
        for offset in range(3):
            day=now.date()+timedelta(days=offset)
            for p in timetable:
                if p['mode']!='lecture' or p['weekday']!=day.weekday():continue
                if any(h.scope in ('',p['campus']) and (h.data['date'][5:]==day.strftime('%m-%d') if h.data.get('repeats') else h.data['date']==day.isoformat()) for h in holidays):continue
                hour,minute=map(int,p['time'].split(':'))
                start=now.replace(hour=hour,minute=minute,second=0,microsecond=0)+timedelta(days=offset)
                due=start-timedelta(minutes=p['lead'])
                if start+timedelta(minutes=5)<now or due>horizon:continue
                alerts.append(dict(p,day=str(day),due_at=int(due.timestamp()*1000),starts_at=int(start.timestamp()*1000)))
        return sorted(alerts,key=lambda p:(p['due_at'],p['starts_at'],p['campus'],p['class_name'],p['section'],p['subject']))[:200]
    @bp.post('/periods')
    def periods():
        if not owner():abort(403)
        csrf();app.extensions['admission_capacity']['lock']()
        action=request.form.get('action')
        if action in ('add','add_full_class'):
            active_rows={r.id:r for r in assignments()}
            def resolve_assignment(raw):
                assignment_id,separator,subject=raw.partition(':')
                aid=int(assignment_id) if assignment_id.isascii() and assignment_id.isdigit() and len(assignment_id)<=18 else None
                assignment=active_rows.get(aid)
                if not assignment:abort(422,'Choose an active teacher class assignment for every lecture.')
                if separator and (assignment.data.get('subject') or not subject or subject not in period_subjects(assignment.data)):abort(422,'Choose a configured subject for this class.')
                employee=db.session.get(Employee,int(assignment.data['employee_id']))
                if not employee or employee.status!='Active':abort(422,'Choose an active teacher.')
                return aid,assignment,separator,subject
            raw_assignments=request.form.getlist('assignment_id')
            direct_fields=('lecture_teacher','lecture_campus','lecture_class','lecture_section','lecture_subject')
            direct=any(field in request.form for field in direct_fields)
            if direct and (action!='add' or raw_assignments):abort(422,'Choose lecture details or an existing assignment, not both.')
            rows=period_rows()
            if action=='add_full_class':
                if len(raw_assignments)!=1:abort(422,'Choose one full-class assignment.')
                aid,assignment,separator,subject=resolve_assignment(raw_assignments[0])
                if separator or assignment.data.get('subject'):abort(422,'Full Class requires an active class-only assignment.')
                supplied=request.form.getlist('weekdays')
                if not supplied or any(day not in ('0','1','2','3','4','5','6') for day in supplied):abort(422,'Select at least one valid weekday.')
                days=sorted(set(map(int,supplied)))
                active={aid:r.data for aid,r in active_rows.items()}
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
            lead=request.form.get('lead',type=int);clocks=request.form.getlist('time')
            count=len(clocks)
            if not 1<=count<=12 or (legacy and count!=1) or (not direct and len(raw_assignments)!=count):abort(422,'Choose one to twelve lectures, each with its own assignment and start time.')
            if direct and (legacy or any(len(request.form.getlist(f))!=count for f in direct_fields)):abort(422,'Complete the teacher, campus, class, section and subject for every lecture.')
            if lead not in (0,5,10,15,30) or any(not re.fullmatch(r'(?:[01][0-9]|2[0-3]):[0-5][0-9]',clock) for clock in clocks):abort(422,'Choose a valid start time for every lecture and reminder lead time.')
            if direct:
                # Resolve existing whole-class or subject assignments first.
                # A new lecture grants only its selected subject, never the whole
                # class or a new campus. The same tenant transaction saves access
                # and timetable together; a rejected batch rolls both back.
                catalog=lecture_catalog(active_rows.values())
                teachers={t['id']:t for t in catalog['teachers']}
                campuses={c['name']:c for c in catalog['campuses']}
                def assignment_key(a):
                    return (str(a.get('employee_id')),a.get('campus'),a.get('class_name'),a.get('section'),a.get('subject') or '')
                by_scope={}
                for a in active_rows.values():by_scope.setdefault(assignment_key(a.data),a)
                selections=[]
                for eid,campus,cls,section,selection in zip(*(request.form.getlist(f) for f in direct_fields)):
                    teacher=teachers.get(eid);school=campuses.get(campus)
                    cohort=next((c for c in school['classes'] if c['name']==cls),None) if school else None
                    if not teacher or campus not in teacher['campuses'] or not cohort or section not in cohort['sections']:abort(422,'Choose an active teacher and a configured campus, class and section within their campus access.')
                    whole=by_scope.get((eid,campus,cls,section,''))
                    if selection=='class-period':
                        if not whole:abort(422,'A class period without a subject requires existing whole-class access.')
                        subject=''
                    elif selection.startswith('subject:') and selection[8:] in cohort['subjects']:
                        subject=selection[8:]
                    else:abort(422,'Choose a subject configured for this class.')
                    selections.append((eid,campus,cls,section,subject))
                for eid,campus,cls,section,subject in selections:
                    scope=(eid,campus,cls,section,subject)
                    whole=by_scope.get((eid,campus,cls,section,''))
                    assignment=by_scope.get(scope) or whole
                    if assignment is None:
                        assignment=W(kind='teacher-classes',status='Active',data=dict(employee_id=eid,campus=campus,class_name=cls,section=section,subject=subject))
                        db.session.add(assignment);db.session.flush()
                        by_scope[scope]=assignment;active_rows[assignment.id]=assignment
                        db.session.add(ops['audit'](action='Create teacher-classes from timetable',data={'assignment_id':assignment.id,**assignment.data}))
                    raw_assignments.append(str(assignment.id)+(':'+subject if subject and not assignment.data.get('subject') else ''))
            # Validate every selected subject and weekday before inserting any
            # timetable entry, including collisions inside the submitted batch.
            def key(data):
                return (str(data.get('assignment',{}).get('employee_id')),data.get('weekday'),data.get('time'))
            def signature(data):
                snapshot=data.get('assignment',{})
                return (data.get('assignment_id'),snapshot,data.get('subject') or snapshot.get('subject') or '',data.get('lead'))
            existing={}
            for row in rows:
                if row.data.get('mode','lecture')=='lecture':existing.setdefault(key(row.data),[]).append(row.data)
            new={};already=set()
            for raw,clock in zip(raw_assignments,clocks):
                aid,assignment,separator,subject=resolve_assignment(raw)
                for day in days:
                    data=dict(mode='lecture',assignment_id=aid,assignment=dict(assignment.data),weekday=day,time=clock,lead=lead,**({'subject':subject} if separator else {}))
                    slot=key(data);matches=existing.get(slot,[])
                    if matches:
                        if legacy or any(signature(old)!=signature(data) for old in matches):abort(409,'A different or existing period for this teacher already starts at that time on a selected day. No timetable entries were changed.')
                        already.add(slot);continue
                    if slot in new and signature(new[slot])!=signature(data):abort(409,'Two selected lectures start at the same time for this teacher. No timetable entries were changed.')
                    new.setdefault(slot,data)
            if len(rows)+len(new)>500:abort(422,'Remove unused periods before adding more.')
            for data in new.values():
                db.session.add(W(kind='automatic-period-reminder',status='Active',data=data))
                db.session.add(ops['audit'](action='Create period reminder',data={'assignment_id':data['assignment_id'],'weekday':data['weekday'],'time':data['time']}))
            flash(f'{len(new)} lecture day(s) saved. {len(already)} already scheduled; no duplicates created.','success')
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
        employees={str(e.id):e.name for e in Employee.query.filter_by(status='Active').all()}
        return render_template('automatic_reports.html',title='Automatic Reports & Notifications',catalog=REPORTS,rules=rules,version=row.version if row else 0,events=events(),history=W.query.filter_by(kind='automatic-report-snapshot',status='Active').order_by(W.id.desc()).limit(30).all(),worker=bool(app.config.get('FINE_WORKER_ENABLED')),period_groups=timetable_groups(period_rows(),employees),assignments=active_assignments,lecture_catalog=lecture_catalog(active_assignments),assignment_subjects={a.id:period_subjects(a.data) for a in active_assignments if not a.data.get('subject')},employees=employees,weekdays=WEEKDAYS,wa_options=wa_options(),wa_enabled=wa_config()[1].get('enabled',False),wa_version=wa_config()[0].version if wa_config()[0] else 0)
    @bp.after_request
    def private(response):
        response.headers['Cache-Control']='no-store';return response
    app.extensions['automatic_report_events']=events
    app.extensions['automatic_report_helpers']=dict(capture=capture,tick_all=tick_all,teacher_periods=teacher_periods,teacher_timetable=teacher_timetable,teacher_lecture_alerts=teacher_lecture_alerts,wa_send=wa_send)
    app.register_blueprint(bp)
