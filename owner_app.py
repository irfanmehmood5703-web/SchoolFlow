"""Owner mobile workspace: summaries first, scoped to the signed-in institute."""
import calendar,hmac,secrets,time
from collections import Counter,defaultdict
from datetime import date,datetime,timedelta,timezone
from flask import Blueprint,abort,g,redirect,render_template,request,session,url_for
from sqlalchemy import or_
from urllib.parse import quote
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import StaleDataError
from school_clock import school_today
from widget_catalog import WIDGETS,KEYS
from widget_sources import build_widgets

# Curated destinations. The client cannot supply a redirect URL or a model name.
TOOLS={
 'compose':('New Message','/workspace/messages'),
 'assistant':('AI Assistant','/workspace/assistant'),
 'messages':('Live Chat & Messaging','/workspace/conversations'),
 'sent':('Sent Messages','/workspace/message-log'),
 'ptm':('Parent Teacher Meetings','/workspace/general/ptm/events'),
 'parents':('Parent Portal Activity','/workspace/general/parents'),
 'users':('Users & Privileges','/workspace/core/users'),
 'security':('Account Security','/workspace/core/users/my-password'),
 'apps':('School App Updates','/workspace/general/app-links'),
 'subscription':('SchoolFlow Subscription','/workspace/core/subscription'),
 'diary':('Class Diaries','/workspace/general/diary'),
 'admissions':('Admission Approvals','/workspace/admission-approvals'),
 'salary-plans':('Salary Plans','/workspace/salary-plans'),
 'increments':('Annual Increments','/workspace/register/increments'),
 'advances':('Advance Salary','/workspace/register/advances'),
 'leave-approvals':('Employee Leaves','/workspace/register/leave-approvals'),
 'payments':('Payment Approvals','/workspace/core/users/payment-requests'),
 'requisitions':('Lab & Campus Requisitions','/workspace/finance/requisitions/approvals'),
 'cash-bank':('Cash Flow & Bank Reconciliation','/workspace/finance/cash-report'),
 'payroll':('Monthly Payroll','/workspace/payroll'),
 'feedback':('Complaints & Suggestions','/workspace/general/?section=feedback'),
 'student-leaves':('Student Leave Approvals','/workspace/general/?section=leaves'),
 'verification':('User Verification','/workspace/general/parents/links'),
 'student360':('Student 360','/workspace/student-360'),
 'lecture':('Lecture Delivery','/workspace/hrm-reports/lecture-delivery'),
 'salary-report':('Salary Register','/workspace/hrm-reports/salary-report'),
 'staff-daily':('Daily Staff Attendance Register','/workspace/reports/attendance/staff-attendance-report'),
 'category-expenses':('Category-wise Expense Report','/workspace/finance/ledger/report/profit'),
 'quality':('System & Data Checks','/workspace/readiness'),
 'help':('SchoolFlow Help','/workspace/how-to'),
}
EXTRA_REPORTS=[
 ('expense-breakdown','Finance','Category-wise Expense Report','category-expenses','Posted income and expense accounts for the selected period.'),
 ('cash-bank-report','Finance','Cash Flow & Bank Reconcile','cash-bank','Cash and bank accounts, with reconciliation tools.'),
 ('student-overview','Exam & Attendance','Student 360','student360','One child: attendance, academics, fees and conduct.'),
 ('lecture-delivery','HRM','Lecture Delivery','lecture','Scheduled lessons and payroll status.'),
 ('salary-register','HRM','Monthly Payroll Register','salary-report','Salary register, allowances and advances.'),
 ('daily-staff','HRM','Daily Staff Attendance Register','staff-daily','Attendance and on-duty status by employee.'),
 ('parent-meetings','Parents & Communication','Parent–Teacher Meetings','ptm','Events, meeting attendance and parent feedback.'),
 ('parent-adoption','Parents & Communication','Parent Portal Activity','parents','Family sign-in activity and parent access.'),
 ('owner-messages','Parents & Communication','Live Chat & Messaging','messages','Your authorised parent and staff conversations.'),
 ('message-history','Parents & Communication','Sent Messages','sent','School notification and SMS request history.'),
 ('class-diaries','HRM','Class Diaries','diary','Saved subject diaries and attachments.'),
]
REPORT_KEYS=set(KEYS)|{r[0] for r in EXTRA_REPORTS}
APP_VERSION=3

def configure_owner_app(app,db,Student,Employee):
    bp=Blueprint('owner_app',__name__,url_prefix='/owner-app')
    rm=app.extensions['record_models'];ops=app.extensions['ops_models'];D=rm['student'];E=rm['employee']
    class Preference(db.Model):
        __tablename__='owner_app_preference'
        actor=db.Column(db.String(80),primary_key=True)
        data=db.Column(db.JSON,nullable=False,default=dict)
        version=db.Column(db.Integer,nullable=False,default=1)
        __mapper_args__={'version_id_col':version}
    app.extensions['owner_app_models']=dict(preference=Preference)
    @app.context_processor
    def client_context():
        binding=app.extensions.get('mobile_client_helpers',{}).get('binding',lambda:None)()
        return dict(is_owner_client=bool(binding and binding.get('kind')=='owner'))
    def preference():
        row=db.session.get(Preference,'owner:'+str(session['owner_id']))
        value=dict(widgets=list(KEYS),pinned=['daily-profit','fee-defaulters','attendance-donut'],favourites=[],reminders=[])
        if row:value.update(row.data)
        return value,row
    def link(endpoint='owner_app.home',**values):
        values.setdefault('campus',g.owner_campus);values.setdefault('month',g.owner_month)
        return url_for(endpoint,**values)
    def cents(value):return 'Rs '+f'{int(value)/100:,.2f}' if value is not None else 'Not available'
    def csrf():
        if not session.get('record_csrf') or not hmac.compare_digest(request.form.get('_csrf',''),session['record_csrf']):abort(400,'Reload before saving.')
        app.extensions['admission_capacity']['lock']()
    @bp.before_request
    def protect():
        if not session.get('owner_id') or session.get('staff_id') or session.get('demo') or not getattr(g,'school_identity',None):abort(403)
        g.owner_campuses=app.extensions['staff_access_helpers']['campuses']()
        g.owner_campus=request.form.get('campus','') if request.method=='POST' and request.form.get('action')=='campus' else request.values.get('campus',session.get('owner_app_campus',''))
        if g.owner_campus and g.owner_campus not in g.owner_campuses:abort(404,'Campus not found in this school.')
        g.owner_month=request.values.get('month',school_today().strftime('%Y-%m'))
        try:
            if len(g.owner_month)!=7:raise ValueError()
            g.owner_start=date.fromisoformat(g.owner_month+'-01')
            g.owner_end=min(date(g.owner_start.year,g.owner_start.month,calendar.monthrange(g.owner_start.year,g.owner_start.month)[1]),school_today())
            if g.owner_end<g.owner_start:g.owner_end=g.owner_start
        except ValueError:abort(422,'Choose a valid report month.')
        if request.method=='POST':csrf()
    @bp.after_request
    def no_cache(response):response.headers['Cache-Control']='no-store';return response
    @bp.errorhandler(IntegrityError)
    @bp.errorhandler(StaleDataError)
    def conflict(error):
        db.session.rollback();return 'Your dashboard changed in another window. Reload before saving.',409
    @bp.context_processor
    def context():
        pref,row=preference()
        return dict(owner_link=link,owner_campus=g.owner_campus,owner_campuses=g.owner_campuses,owner_month=g.owner_month,owner_pref=pref,owner_revision=row.version if row else 0,money=cents,tools=TOOLS,app_version=APP_VERSION,owner_now=datetime.now(timezone.utc).isoformat(),owner_today=school_today(),previous_month=(g.owner_start-timedelta(days=1)).strftime('%Y-%m'),next_month=(g.owner_start+timedelta(days=32)).replace(day=1).strftime('%Y-%m'),owner_name=(g.school_identity or {}).get('name','Your school'))
    def people(active=False):
        q=db.session.query(Student,D).outerjoin(D,D.student_id==Student.id)
        if active:q=q.filter(Student.status=='Active')
        if g.owner_campus:q=q.filter(D.data['campus'].as_string()==g.owner_campus)
        return q.all()
    def employees():
        q=db.session.query(Employee,E).outerjoin(E,E.employee_id==Employee.id)
        if g.owner_campus:q=q.filter(E.data['campus'].as_string()==g.owner_campus)
        return q.all()
    def workflows():
        ids={str(s.id) for s,_ in people()};eids={str(e.id) for e,_ in employees()}
        rows=ops['workflow'].query.filter(ops['workflow'].kind.in_(['queries','salary-plans','increments','advances','leave-approvals','staff-payment-approval','complaints','suggestions','complaints-suggestions'])).order_by(ops['workflow'].id.desc()).all()
        if g.owner_campus:rows=[w for w in rows if w.data.get('campus')==g.owner_campus or g.owner_campus in w.data.get('campuses',[]) or str(w.data.get('employee_id','')) in eids or str(w.data.get('student_id','')) in ids]
        return rows
    def summaries(keys=None):
        selected=set(keys or KEYS)
        config=db.session.get(app.extensions['general_tools_models']['policy'],1)
        result=build_widgets(app,db,Student,Employee,selected,g.owner_start,g.owner_end,school_today(),app.extensions['general_tools_helpers']['releases'](),config.data.get('tuition_head','') if config else '',campus=g.owner_campus)
        if selected & {'complaints','complaints-chart'}:
            F=app.extensions['general_feedback_model'];q=F.query.filter_by(institute_scope=g.school_identity['scope'])
            if g.owner_campus:q=q.filter_by(campus=g.owner_campus)
            feedback=q.all()
            if 'complaints' in result:
                s=result['complaints'];s['value']+=sum(r.status=='Open' for r in feedback);s['rows'] += [['F-'+str(r.id),r.kind,r.status,r.message] for r in feedback]
                s['unit']='open feedback records';s['note']='Saved school feedback submissions and legacy complaint workflows. F- IDs identify feedback submissions.'
            if 'complaints-chart' in result:
                s=result['complaints-chart'];months=dict(s['chart'])
                for r in feedback:
                    month=r.created_at.strftime('%Y-%m')
                    if month in months and r.created_at.date()<=school_today():months[month]+=1
                s.update(value=sum(months.values()),rows=[[k,v] for k,v in months.items()],chart=list(months.items()),note='Actual creation months of school feedback submissions and legacy workflows.')
        for key,s in result.items():
            s.update(key=key,label=next(r[2] for r in WIDGETS if r[0]==key),group=next(r[1] for r in WIDGETS if r[0]==key),chips=[])
            s['display']=cents(s['value']) if s['unit']=='money' else (str(s['value'])+'%' if s['unit']=='percent' and s['value'] is not None else f"{s['value']:,}" if isinstance(s['value'],(int,float)) else 'Not available')
            s['preview_chart']=s['chart'][:12]
        # Explicit denominators: unmarked records are never counted as absent.
        if 'attendance-donut' in result:
            s=result['attendance-donut'];counts=dict(s['chart']);marked=sum(v for k,v in counts.items() if k not in ('Unmarked','Off Day'));present=counts.get('Present',0)+counts.get('Late',0)
            percent=round(100*present/marked,1) if marked else None
            s.update(percent=percent,display=str(percent)+'%' if percent is not None else 'Not marked',unit='present + late / marked',chips=[(k,v) for k,v in counts.items()],marked=marked)
        if 'fee-collection' in result:
            rows=result['fee-collection']['rows'];due=sum(round(float(r[4].replace(',',''))*100)-round(float(r[6].replace(',',''))*100) for r in rows);remaining=sum(round(float(r[7].replace(',',''))*100) for r in rows)
            s=result['fee-collection'];s.update(percent=round(100*s['value']/due,1) if due else None,chips=[('Net payable',cents(due)),('Outstanding',cents(remaining)),('Challans',len(rows))])
        for key in ('new-admissions','inactive-students'):
            if key in result:result[key]['chips']=[('This month',dict(result[key]['chart']).get(school_today().strftime('%Y-%m'),0)),('12 months',result[key]['value'])]
        if 'admission-queries' in result:
            s=result['admission-queries'];open_rows=[r for r in s['rows'] if r[3] not in ('Voided','Converted','Closed')];s.update(value=len(open_rows),display=str(len(open_rows)),rows=open_rows,unit='open enquiries',note='Open enquiries exclude archived, converted and closed records.')
        for key in ('class-fees','strength-chart','class-results','month-results','performance-bands','staff-attendance','employee-status'):
            if key in result:result[key]['chips']=[(str(k),v) for k,v in result[key]['preview_chart'][:4]]
        if 'unpaid-challans' in result:
            rows=result['unpaid-challans']['rows'];result['unpaid-challans']['chips']=[('Partly paid',sum(float(r[5].replace(',',''))>0 for r in rows)),('Overdue',sum(r[3]<school_today().isoformat() for r in rows))]
        if 'sms' in result:
            jobs=app.extensions['sms_models']['job'];q=jobs.query
            if g.owner_campus:q=q.join(app.extensions['sms_models']['device'],jobs.device_id==app.extensions['sms_models']['device'].id).filter(app.extensions['sms_models']['device'].campus==g.owner_campus)
            counts=Counter(j.state for j in q.all());result['sms'].update(display=str(counts.get('sent',0)),unit='phone-submission results',chips=list(counts.items()),note='Sent means the school phone reported network submission. SIM balance and recipient delivery are not measured.')
        for key,group,label,tool,note in EXTRA_REPORTS:
            if keys is None or key in keys:result[key]=dict(key=key,group=group,label=label,display='',unit=note,chips=[],note=note)
        return result
    def finance():
        J=app.extensions['ledger_models']['journal'];L=app.extensions['ledger_models']['line'];month=g.owner_start
        previous=(month-timedelta(days=1)).replace(day=1);q=db.session.query(J.day,L.snapshot,L.debit,L.credit).join(L,L.journal_id==J.id).filter(J.day>=previous,J.day<=g.owner_end)
        if g.owner_campus:q=q.filter(J.campus==g.owner_campus)
        income=expense=prior=today_in=today_out=0;days=defaultdict(lambda:[0,0])
        for day,snapshot,debit,credit in q.all():
            typ=snapshot.get('account_class');amount=credit-debit if typ=='Income' else debit-credit if typ=='Expense' else 0
            if day<month:prior+=amount if typ=='Income' else -amount if typ=='Expense' else 0;continue
            if typ=='Income':income+=amount;days[day][0]+=amount;today_in+=amount if day==school_today() else 0
            elif typ=='Expense':expense+=amount;days[day][1]+=amount;today_out+=amount if day==school_today() else 0
        def line(index):
            values=[days[month+timedelta(days=i)][index] for i in range((g.owner_end-month).days+1)];low=min(values+[0]);high=max(values+[1]);return ' '.join(f'{i*260/max(len(values)-1,1):.1f},{65-(v-low)*55/max(high-low,1):.1f}' for i,v in enumerate(values))
        return dict(income=income,expense=expense,net=income-expense,today_income=today_in,today_expense=today_out,previous=prior,change=round((income-expense-prior)/abs(prior)*100,1) if prior else None,income_line=line(0),expense_line=line(1))
    def approvals():
        rows=[]
        students=people();decisions={}
        for event in rm['event'].query.filter_by(owner_kind='student').filter(rm['event'].owner_id.in_([s.id for s,_ in students]),rm['event'].action.in_(['Admission allowed','Admission refused'])).order_by(rm['event'].id.desc()).all():decisions.setdefault(event.owner_id,event)
        for s,d in students:
            decision=decisions.get(s.id)
            state='Pending' if s.status=='Waiting' else 'Declined' if s.status in ('Refused','Rejected') else 'Approved' if decision and decision.action=='Admission allowed' else None
            if state:rows.append(dict(id='student:'+str(s.id),group='Students',kind='Admission Approval',label=s.name,state=state,url=link('owner_app.open_tool',key='admissions')))
        names={str(e.id):e.name for e,_ in employees()}
        kinds={'salary-plans':'Salary Plan','increments':'Annual Increment','advances':'Advance Salary','leave-approvals':'Leaves','staff-payment-approval':'Fee Payment'}
        for row in workflows():
            if row.kind not in kinds:continue
            state='Declined' if row.status in ('Rejected','Declined') else row.status
            if state not in ('Pending','Approved','Declined'):continue
            rows.append(dict(id='workflow:'+str(row.id),group='Finance' if row.kind=='staff-payment-approval' else 'Employees',kind=kinds[row.kind],label=names.get(str(row.data.get('employee_id','')),'Request #'+str(row.id)),state=state,url=link('owner_app.open_tool',key='payments' if row.kind=='staff-payment-approval' else row.kind)))
        R=app.extensions['requisition_models']['request'];q=R.query
        if g.owner_campus:q=q.filter(R.campus==g.owner_campus)
        for row in q.order_by(R.id.desc()).all():
            if row.status in ('Awaiting approval','Approved','Rejected'):rows.append(dict(id='requisition:'+str(row.id),group='Finance',kind='Lab & Campus Requisitions',label=row.number,state={'Awaiting approval':'Pending','Rejected':'Declined'}.get(row.status,row.status),url=link('owner_app.open_tool',key='requisitions')))
        return rows
    def engagement():
        people_rows=people(True);families={d.family_id for _,d in people_rows if d and d.family_id};A=app.extensions['parent_models']['account'];accounts=A.query.filter(A.family_id.in_(families)).all() if families else []
        recent=sum(a.last_used>=time.time()-30*86400 for a in accounts);ever=sum(a.last_used>0 for a in accounts)
        C=app.extensions['message_models']['conversation'];M=app.extensions['message_models']['message'];Seen=app.extensions['message_models']['seen'];who='owner:'+str(session['owner_id']);q=C.query.filter(or_(C.first_actor==who,C.second_actor==who))
        if g.owner_campus:q=q.filter(C.campus==g.owner_campus)
        active_ids={s.id for s,_ in people_rows}
        conversations=[c for c in q.all() if not c.student_id or c.student_id in active_ids];seen={s.conversation_id:s.last_id for s in Seen.query.filter_by(actor=who).all()};unread=sum(m.actor!=who and not m.blocked and m.id>seen.get(m.conversation_id,0) for m in M.query.filter(M.conversation_id.in_([c.id for c in conversations])).all()) if conversations else 0
        P=app.extensions['ptm_models']['event'];events=P.query.filter(*([P.campus==g.owner_campus] if g.owner_campus else [])).count()
        return dict(families=len(families),recent=recent,ever=ever,never=len(families)-ever,percent=round(recent/len(families)*100) if families else None,chats=sum(c.status=='Open' for c in conversations),unread=unread,ptm=events)
    def render(view,**data):return render_template('owner_app.html',view=view,title='Owner App',**data)
    @bp.get('')
    def home():
        pref,_=preference();data=summaries();pending=sum(r['state']=='Pending' for r in approvals());finance_data=finance()
        today_staff=[e.id for e,_ in employees() if e.status=='Active'];marks=ops['daily'].query.filter_by(kind='staff',day=school_today()).filter(ops['daily'].person_id.in_(today_staff)).all();staff=Counter(r.status for r in marks)
        inv=app.extensions['client_subscription_models']['invoice'].query.filter_by(institute_id=session['institute_id']).order_by(app.extensions['client_subscription_models']['invoice'].month.desc()).first()
        return render('home',summaries=data,financial=finance_data,engagement=engagement(),pending=pending,staff=staff,staff_marked=len(marks),staff_unmarked=len(today_staff)-len(marks),invoice=inv)
    @bp.get('/reports')
    def reports():return render('reports',summaries=summaries(),catalog=[*WIDGETS,*[(k,g,l,'') for k,g,l,_,_ in EXTRA_REPORTS]],groups=list(dict.fromkeys(r[1] for r in [*WIDGETS,*EXTRA_REPORTS])),query=request.args.get('q','').strip().casefold())
    @bp.get('/report/<key>')
    def report(key):
        if key not in REPORT_KEYS:abort(404)
        extra=next((r for r in EXTRA_REPORTS if r[0]==key),None)
        if extra:return redirect(link('owner_app.open_tool',key=extra[3]))
        summary=summaries([key])[key]
        try:page=max(1,int(request.args.get('page','1')))
        except ValueError:abort(422)
        total=len(summary['rows']);page=min(page,max(1,(total+24)//25));rows=summary['rows'][(page-1)*25:page*25]
        return render('report',summary=summary,rows=rows,page=page,total=total)
    @bp.get('/approvals')
    def approval_list():
        group=request.args.get('group','All');state=request.args.get('state','Pending')
        if group not in ('All','Students','Employees','Finance') or state not in ('Pending','Approved','Declined'):abort(422)
        all_rows=approvals();rows=[r for r in all_rows if (group=='All' or r['group']==group) and r['state']==state]
        return render('approvals',rows=rows,all_rows=all_rows,group=group,state=state)
    def feedback_counts():
        F=app.extensions['general_feedback_model'];q=F.query.filter_by(institute_scope=g.school_identity['scope'])
        if g.owner_campus:q=q.filter_by(campus=g.owner_campus)
        rows=q.all()
        return {kind:dict(total=sum(r.kind==kind for r in rows),open=sum(r.kind==kind and r.status=='Open' for r in rows),done=sum(r.kind==kind and r.status!='Open' for r in rows)) for kind in ('complaint','suggestion')}
    @bp.get('/connect')
    def connect():return render('connect',engagement=engagement(),feedback=feedback_counts(),summaries=summaries(['complaints','complaints-chart','sms']))
    @bp.get('/notifications')
    def notifications():return render('notifications',events=app.extensions['notice_events'](),reminders=[r for r in preference()[0]['reminders'] if not r.get('done') and r['due']<=school_today().isoformat()])
    @bp.get('/activity')
    def activity():
        A=ops['audit'];q=A.query
        if g.owner_campus:q=q.filter(A.data['campus'].as_string()==g.owner_campus)
        try:page=max(1,int(request.args.get('page',1)))
        except ValueError:abort(422)
        return render('activity',rows=q.order_by(A.id.desc()).limit(50).offset((page-1)*50).all(),page=page)
    @bp.get('/profile')
    def profile():return render('profile')
    @bp.get('/widgets')
    def widgets():return render('widgets',catalog=WIDGETS)
    @bp.get('/reminders')
    def reminders():return render('reminders')
    @bp.post('/preferences')
    def save_preferences():
        value,row=preference()
        if request.form.get('version')!=str(row.version if row else 0):abort(409,'Your dashboard changed. Reload first.')
        action=request.form.get('action');key=request.form.get('key','')
        if action in ('pin','favourite'):
            if key not in REPORT_KEYS:abort(422)
            field='pinned' if action=='pin' else 'favourites';items=list(value[field]);items.remove(key) if key in items else items.append(key);value[field]=items
        elif action=='widgets':
            items=request.form.getlist('widgets')
            if len(items)!=len(set(items)) or any(k not in KEYS for k in items):abort(422)
            value['widgets']=items
        elif action=='campus':
            session['owner_app_campus']=g.owner_campus;return redirect(link())
        elif action=='reminder':
            text=request.form.get('text','').strip();due=request.form.get('due','')
            try:date.fromisoformat(due)
            except ValueError:abort(422)
            if not 1<=len(text)<=300 or len(value['reminders'])>=100:abort(422)
            value['reminders']=[*value['reminders'],dict(id=secrets.token_urlsafe(12),text=text,due=due,done=False)]
        elif action=='done':
            items=[dict(r) for r in value['reminders']]
            item=next((r for r in items if r['id']==key),None)
            if not item:abort(404)
            item['done']=not item['done'];value['reminders']=items
        else:abort(422)
        if row:row.data=value
        else:db.session.add(Preference(actor='owner:'+str(session['owner_id']),data=value))
        db.session.add(ops['audit'](action='Update owner app preferences',data=dict(owner_id=session['owner_id'],action=action,key=key)));db.session.commit()
        target={'pin':'owner_app.reports','favourite':'owner_app.reports','widgets':'owner_app.home','reminder':'owner_app.reminders','done':'owner_app.reminders'}[action]
        return redirect(link(target))
    @bp.get('/open/<key>')
    def open_tool(key):
        if key not in TOOLS:abort(404)
        title,path=TOOLS[key];separator='&' if '?' in path else '?'
        target=path+separator+'owner_embed=1&from='+g.owner_start.isoformat()+'&to='+g.owner_end.isoformat()+'&month='+g.owner_month+('&campus='+quote(g.owner_campus,safe='') if g.owner_campus else '')
        return render('tool',tool_title=title,tool_url=target)
    app.extensions['owner_app_helpers']=dict(home=lambda:url_for('owner_app.home'),summaries=summaries)
    app.register_blueprint(bp)
