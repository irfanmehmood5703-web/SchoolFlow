"""Real private-school Owner app: campus totals, permissions and saved preferences."""
import os,tempfile,unittest,secrets,json
from datetime import date
from contextlib import contextmanager
from flask import g,template_rendered
from werkzeug.datastructures import MultiDict
os.environ['DATABASE_URL']='sqlite:///:memory:'
from app import app,db,Student,Employee
from owner_app import TOOLS,REPORT_KEYS
from school_clock import school_today

PASSWORD='Fictional-owner-2026-password'
class OwnerAppTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.old={k:app.config.get(k) for k in ('TESTING','SECRET_KEY','IDENTITY_ENFORCE_IN_TESTS','INSTITUTE_DATABASE_DIR')}
        app.config.update(TESTING=True,SECRET_KEY='owner-app-fictional',IDENTITY_ENFORCE_IN_TESTS=True,INSTITUTE_DATABASE_DIR=self.tmp.name)
        self.ctx=app.app_context();self.ctx.push();db.drop_all();db.create_all();self.rm=app.extensions['record_models'];self.ops=app.extensions['ops_models'];self.today=school_today()
        self.schools=[]
        for code in ('OWNER-A','OWNER-B'):
            row=app.extensions['identity_helpers']['provision'](code,'Fictional '+code,'owner@example.invalid',PASSWORD);self.schools.append((row.id,row.storage_key,code));self.seed(row.id,code)
        self.c=self.login()
    def tearDown(self):db.session.remove();db.drop_all();self.ctx.pop();app.config.update(self.old);self.tmp.cleanup()
    @contextmanager
    def tenant(self,i=0):
        with app.test_request_context('/'):
            g.institute_engine=app.extensions['identity_helpers']['engine'](self.schools[i][0])
            yield
            db.session.remove()
    def seed(self,i,code):
        with app.test_request_context('/'):
            g.institute_engine=app.extensions['identity_helpers']['engine'](i)
            for campus in ('North','South'):db.session.add(self.rm['settings'](category='campus',value=campus,class_name=''))
            for n,(campus,status) in enumerate([('North','Active'),('North','Active'),('North','Waiting'),('South','Active')],1):
                s=Student(admission_no='QA-'+str(n),name=code+' pupil '+str(n),class_name='One',status=status);db.session.add(s);db.session.flush();db.session.add(self.rm['student'](student_id=s.id,data=dict(campus=campus,admission_date=str(self.today))))
            for i,campus in enumerate(('North','South'),1):
                e=Employee(employee_no='QA-'+str(i),name=code+' employee '+str(i),role='Teaching',status='Active');db.session.add(e);db.session.flush();db.session.add(self.rm['employee'](employee_id=e.id,data=dict(campus=campus)))
            db.session.flush()
            db.session.add(self.ops['daily'](kind='student',person_id=1,day=self.today,status='Present'));db.session.add(self.ops['daily'](kind='student',person_id=4,day=self.today,status='Absent'))
            db.session.add(self.ops['daily'](kind='staff',person_id=1,day=self.today,status='Present'))
            for sid,amount,paid in [(1,350000,100025),(4,500000,200000)]:
                bill=self.ops['bill'](student_id=sid,month=self.today.strftime('%Y-%m'),due=self.today,lines=[dict(particular='Tuition',amount=amount)],paid=paid);db.session.add(bill);db.session.flush()
                db.session.add(self.ops['receipt'](token=secrets.token_urlsafe(20),bill_id=bill.id,student_id=sid,day=self.today,amount=paid,discount=0,account='Cash'))
                db.session.add(self.ops['receipt'](token=secrets.token_urlsafe(20),bill_id=bill.id,student_id=sid,day=self.today,amount=999999,discount=0,account='Cash',voided=True))
            W=self.ops['workflow'];db.session.add(W(kind='salary-plans',status='Pending',data=dict(employee_id='1')));db.session.add(W(kind='salary-plans',status='Approved',data=dict(employee_id='2')))
            F=app.extensions['general_feedback_model'];db.session.add(F(institute_scope=self.schools[-1][1],kind='complaint',category='Academic',submitted_by='Fictional parent',campus='North',message=code+' feedback'))
            db.session.commit();db.session.remove()
    def login(self,index=0,bound=True):
        c=app.test_client();iid,scope,code=self.schools[index]
        c.get('/mobile/owner?school='+code+'&scope='+scope if bound else '/auth/institute')
        with c.session_transaction() as s:csrf=s['record_csrf']
        if not bound:c.post('/auth/institute',data=dict(_csrf=csrf,code=code))
        with c.session_transaction() as s:csrf=s['record_csrf']
        r=c.post('/auth/login',data=dict(_csrf=csrf,email='owner@example.invalid',password=PASSWORD));self.assertEqual(r.status_code,302)
        self.assertEqual(r.location,'/owner-app' if bound else '/workspace/dashboard');return c
    def page(self,path='/owner-app',client=None):
        captured=[]
        def receive(sender,template,context,**kw):captured.append(context)
        template_rendered.connect(receive,app)
        try:r=(client or self.c).get(path);self.assertEqual(r.status_code,200,(path,r.status_code,r.data[:200]));return r,captured[-1]
        finally:template_rendered.disconnect(receive,app)
    def post(self,**data):
        with self.c.session_transaction() as s:csrf=s['record_csrf']
        return self.c.post('/owner-app/preferences',data=MultiDict([('_csrf',csrf)]+[(k,v) for k,values in data.items() for v in (values if isinstance(values,list) else [values])]))
    def test_summary_campus_money_partial_and_unmarked(self):
        response,ctx=self.page('/owner-app?campus=North');data=ctx['summaries']
        self.assertEqual(data['active-students']['value'],2);self.assertEqual(data['paid-amount']['value'],100025);self.assertEqual(data['fee-collection']['value'],100025);self.assertIn(b'Rs 1,000.25',response.data)
        self.assertEqual(data['attendance-donut']['marked'],1);self.assertEqual(data['attendance-donut']['percent'],100.0)
        self.assertIn(('Unmarked',1),data['attendance-donut']['chips']);self.assertEqual(ctx['staff_marked'],1);self.assertEqual(ctx['staff_unmarked'],0)
        _,south=self.page('/owner-app?campus=South');self.assertEqual(south['summaries']['paid-amount']['value'],200000);self.assertEqual(south['summaries']['attendance-donut']['percent'],0)
        self.assertEqual(self.c.get('/owner-app?campus=Foreign').status_code,404);self.assertEqual(self.c.get('/owner-app?month=not-a-month').status_code,422)
    def test_ledger_net_uses_postings_and_approval_history_uses_real_events(self):
        with self.tenant():
            fm=app.extensions['finance_models'];lm=app.extensions['ledger_models'];p=fm['period'].query.first();a=fm['account'].query.first()
            for campus,income,expense in [('North',125025,20000),('South',900000,10000)]:
                j=lm['journal'](token=secrets.token_urlsafe(20),fingerprint='fictional',day=self.today,campus=campus,kind='journal',period_id=p.id,actor='Fictional owner',actor_key='owner:1');db.session.add(j);db.session.flush()
                for typ,debit,credit in [('Income',0,income),('Expense',expense,0),('Assets',income-expense,0)]:db.session.add(lm['line'](journal_id=j.id,account_id=a.id,debit=debit,credit=credit,snapshot=dict(account_class=typ)))
            student=db.session.get(Student,3);student.status='Active';db.session.add(self.rm['event'](owner_kind='student',owner_id=3,action='Admission allowed'))
            R=app.extensions['requisition_models']['request'];db.session.add(R(number='QA-REQ-1',campus='North',actor_key='owner:1',raised_by='Fictional owner',category='Utilities & Bills',purpose='Fictional stationery',items=[],estimated=10000,status='Awaiting approval',token='qa-request',fingerprint='qa'))
            db.session.commit()
        _,ctx=self.page('/owner-app?campus=North');self.assertEqual(ctx['financial']['income'],125025);self.assertEqual(ctx['financial']['expense'],20000);self.assertEqual(ctx['financial']['net'],105025)
        _,ctx=self.page('/owner-app/approvals?campus=North&state=Approved');self.assertEqual([r['group'] for r in ctx['rows']],['Students'])
        _,ctx=self.page('/owner-app/approvals?campus=North&group=Finance');self.assertEqual(len(ctx['rows']),1)
        _,ctx=self.page('/owner-app/report/complaints?campus=North');self.assertEqual(ctx['summary']['value'],1);self.assertIn('OWNER-A feedback',str(ctx['rows']))
    def test_all_pages_reports_tools_and_no_desktop_navigation(self):
        for path in ('','/reports','/approvals','/connect','/notifications','/profile','/widgets','/reminders','/activity'):
            r,_=self.page('/owner-app'+path);self.assertNotIn(b'class="top-navigation"',r.data);self.assertNotIn(b'>null<',r.data)
        for key in REPORT_KEYS:self.assertIn(self.c.get('/owner-app/report/'+key).status_code,(200,302),key)
        for key,(_,path) in TOOLS.items():
            self.page('/owner-app/open/'+key)
            result=self.c.get(path,follow_redirects=True);self.assertEqual(result.status_code,200,(key,path,result.status_code,result.data[:120]));self.assertNotIn(b'Awaiting reference',result.data)
        self.assertEqual(self.c.get('/owner-app/open/https://evil.invalid').status_code,404)
    def test_cross_school_data_preferences_and_owner_only(self):
        other=self.login(1);r,_=self.page('/owner-app/report/active-students',other);self.assertIn(b'OWNER-B pupil',r.data);self.assertNotIn(b'OWNER-A pupil',r.data)
        self.assertEqual(self.post(action='favourite',key='active-students',version='0').status_code,302)
        _,ctx=self.page('/owner-app/reports',other);self.assertEqual(ctx['owner_pref']['favourites'],[])
        self.assertIn(app.test_client().get('/owner-app').status_code,(302,403))
        with self.c.session_transaction() as s:s['staff_id']=99
        self.assertIn(self.c.get('/owner-app').status_code,(302,403))
    def test_preferences_csrf_conflicts_campus_and_persistence(self):
        self.assertEqual(self.c.post('/owner-app/preferences',data=dict(action='pin',key='active-students',version='0')).status_code,400)
        self.assertEqual(self.post(action='pin',key='active-students',version='0').status_code,302)
        self.assertEqual(self.post(action='favourite',key='active-students',version='0').status_code,409)
        self.assertEqual(self.post(action='favourite',key='active-students',version='1').status_code,302)
        self.assertEqual(self.post(action='widgets',widgets=['active-students','attendance-donut'],version='2').status_code,302)
        self.assertEqual(self.post(action='campus',campus='South',version='3').status_code,302)
        _,ctx=self.page();self.assertEqual(ctx['owner_campus'],'South');self.assertEqual(ctx['summaries']['active-students']['value'],1)
        fresh=self.login();_,ctx=self.page(client=fresh);self.assertIn('active-students',ctx['owner_pref']['pinned']);self.assertIn('active-students',ctx['owner_pref']['favourites']);self.assertEqual(len(ctx['owner_pref']['widgets']),2)
        self.assertEqual(self.post(action='reminder',text='<script>Fictional task</script>',due=str(self.today),version='3').status_code,302)
        r,ctx=self.page('/owner-app/reminders');self.assertIn(b'&lt;script&gt;Fictional task',r.data)
        key=ctx['owner_pref']['reminders'][0]['id'];self.assertEqual(self.post(action='done',key=key,version='4').status_code,302)
        _,ctx=self.page('/owner-app/notifications');self.assertEqual(ctx['reminders'],[])
    def test_attendance_notifications_acknowledge_only_displayed_revisions(self):
        _,ctx=self.page('/owner-app/notifications?campus=North');events=ctx['events'];student=next(e for e in events if e['key'].startswith('owner-attendance:student:'));self.assertIn('1 active records',student['detail'])
        with self.c.session_transaction() as s:csrf=s['record_csrf']
        def read(items):return self.c.post('/owner-app/notifications/read?campus=North',data=dict(_csrf=csrf,items=json.dumps(items)))
        self.assertEqual(read([student]).status_code,204)
        _,ctx=self.page('/owner-app/notifications?campus=North');self.assertTrue(next(e for e in ctx['events'] if e['key']==student['key'])['read'])
        with self.tenant():
            db.session.add(self.ops['daily'](kind='student',person_id=2,day=self.today,status='Present'));db.session.query(self.ops['daily']).filter_by(kind='student',person_id=1,day=self.today).delete();db.session.commit()
        self.assertEqual(read([student]).status_code,204)
        _,ctx=self.page('/owner-app/notifications?campus=North');current=next(e for e in ctx['events'] if e['key']==student['key']);self.assertFalse(current['read']);self.assertNotEqual(current['revision'],student['revision'])
        self.assertEqual(read([dict(key='fake',revision='fake')]).status_code,204)
    def test_approval_counts_real_statuses_and_feedback_scope(self):
        _,ctx=self.page('/owner-app/approvals?campus=North');self.assertEqual(len(ctx['rows']),2);self.assertEqual({r['group'] for r in ctx['rows']},{'Students','Employees'})
        _,ctx=self.page('/owner-app/approvals?campus=South&state=Approved');self.assertEqual(len(ctx['rows']),1)
        _,ctx=self.page('/owner-app/connect?campus=North');self.assertEqual(ctx['feedback']['complaint']['total'],1)
        _,ctx=self.page('/owner-app/connect?campus=South');self.assertEqual(ctx['feedback']['complaint']['total'],0)
        browser=self.login(bound=False);r=browser.get('/workspace/dashboard');self.assertIn(b'class="top-navigation"',r.data)
        r=self.c.get('/workspace/general/parents');self.assertIn(b'owner-embed.css',r.data)

    def test_direct_leave_review_and_decision_is_scoped_and_not_repeated(self):
        Leave=app.extensions['general_leave_model']
        with self.tenant():
            row=Leave(institute_scope=self.schools[0][1],student_id=1,from_date=self.today,to_date=self.today,leave_type='Sick Leave',reason='Fictional leave request')
            db.session.add(row);db.session.flush();lid=row.id;db.session.commit()
        path='/owner-app/approvals/student-leave/'+str(lid)
        r,_=self.page('/owner-app/approvals?campus=North')
        self.assertIn(path.encode(),r.data)
        r,_=self.page(path+'?campus=North')
        self.assertIn(b'Fictional leave request',r.data);self.assertIn(b'name="decision" value="Approved"',r.data);self.assertNotIn(b'<iframe',r.data)
        self.assertEqual(self.c.get(path+'?campus=South').status_code,404)
        other=self.login(1);self.assertEqual(other.get(path).status_code,404)
        self.assertEqual(self.c.post(path,data=dict(decision='Approved')).status_code,400)
        with self.c.session_transaction() as s:csrf=s['record_csrf']
        self.assertEqual(self.c.post(path,data=dict(_csrf=csrf,campus='South',decision='Approved')).status_code,404)
        self.assertEqual(self.c.post(path,data=dict(_csrf=csrf,campus='North',decision='Approved',comment='Fictional note')).status_code,302)
        self.assertEqual(self.c.post(path,data=dict(_csrf=csrf,campus='North',decision='Rejected')).status_code,409)
        r,_=self.page(path+'?campus=North');self.assertIn(b'Fictional note',r.data);self.assertNotIn(b'name="decision"',r.data)
        with self.tenant():
            row=db.session.get(Leave,lid);self.assertEqual(row.status,'Approved')
            self.assertEqual(self.ops['audit'].query.filter_by(action='Decide student leave').count(),1)

if __name__=='__main__':unittest.main()
