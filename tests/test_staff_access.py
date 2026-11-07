"""Real staff sign-in, per-action campus scopes and revoked-session enforcement."""
import os,tempfile,unittest,time
from datetime import date
from flask import g
from werkzeug.security import generate_password_hash
os.environ['DATABASE_URL']='sqlite:///:memory:'
from app import app,db,Student,Employee

class StaffAccessTests(unittest.TestCase):
    password='Fictional-staff-password-2026'
    def setUp(self):
        self.dir=tempfile.TemporaryDirectory();app.config.update(TESTING=True,IDENTITY_ENFORCE_IN_TESTS=True,INSTITUTE_DATABASE_DIR=self.dir.name,SECRET_KEY='staff-access-test')
        self.ctx=app.app_context();self.ctx.push();db.drop_all();db.create_all();self.M=app.extensions['identity_models'];self.Staff=app.extensions['staff_account_model'];self.rm=app.extensions['record_models'];self.ops=app.extensions['ops_models']
        self.school=app.extensions['identity_helpers']['provision']('STAFF-TEST','Fictional school','owner@example.invalid',self.password).id
        with app.test_request_context('/'):
            g.institute_engine=app.extensions['identity_helpers']['engine'](self.school);db.session.remove()
            for c in ('Campus A','Campus B'):db.session.add(self.rm['settings'](category='campus',value=c,class_name=''))
            e=Employee(employee_no='E1',name='Fictional teacher',role='Teacher',status='Active');db.session.add(e);db.session.flush();db.session.add(self.rm['employee'](employee_id=e.id,data={'campus':'Campus A'}))
            for i,c in enumerate(('Campus A','Campus B'),1):
                s=Student(admission_no='S'+str(i),name='Pupil '+c,class_name='One',status='Active');db.session.add(s);db.session.flush();db.session.add(self.rm['student'](student_id=s.id,data={'campus':c}));db.session.add(self.ops['bill'](student_id=s.id,month='2026-11',due=date(2026,11,10),lines=[{'particular':'Tuition','amount':10000}]))
            staff=self.Staff(employee_id=e.id,username='teacher.one',email='teacher@example.invalid',password_hash=generate_password_hash(self.password),active=True,data=dict(role='Teacher',campuses=['Campus A','Campus B'],accounts=['Cash in Hand'],payment_mode='day',payment_days=0,permissions={'dashboard.view':['Campus A'],'admissions.view':['Campus A'],'admissions.export':['Campus A'],'fees.view':['Campus A'],'fees.pay':['Campus A'],'attendance.view':['Campus A']}));db.session.add(staff);db.session.commit();self.sid=staff.id;db.session.remove()
        g.pop('institute_engine',None);self.c=app.test_client()
    def tearDown(self):db.session.remove();db.drop_all();self.ctx.pop();app.config.update(IDENTITY_ENFORCE_IN_TESTS=False,INSTITUTE_DATABASE_DIR=None);self.dir.cleanup()
    def csrf(self):
        self.c.get('/auth/institute')
        with self.c.session_transaction() as s:return s['record_csrf']
    def login(self,username='teacher.one',password=None):
        token=self.csrf();self.c.post('/auth/institute',data={'_csrf':token,'code':'STAFF-TEST'})
        with self.c.session_transaction() as s:token=s['record_csrf']
        return self.c.post('/auth/login',data={'_csrf':token,'email':username,'password':password or self.password})
    def token(self):
        with self.c.session_transaction() as s:return s['record_csrf']
    def test_staff_username_and_email_login_and_wrong_password(self):
        self.assertEqual(self.login(password='wrong').status_code,200);self.assertEqual(self.login().status_code,302)
        with self.c.session_transaction() as s:self.assertEqual(s['staff_id'],self.sid);self.assertNotIn('owner_id',s)
        self.assertEqual(self.c.get('/workspace/dashboard').status_code,200)
        self.assertEqual(self.login('teacher@example.invalid').status_code,302)
    def test_staff_views_exports_and_record_ids_are_scoped_to_permission_campus(self):
        self.login();page=self.c.get('/records/student');self.assertEqual(page.status_code,200);self.assertIn(b'Pupil Campus A',page.data);self.assertNotIn(b'Pupil Campus B',page.data)
        self.assertEqual(self.c.get('/records/student/2').status_code,404);self.assertEqual(self.c.get('/records/student?campus=Campus+B').status_code,403)
        export=self.c.get('/records/student/export.csv');self.assertEqual(export.status_code,200);self.assertNotIn(b'Pupil Campus B',export.data)
        fees=self.c.get('/workspace/fees/payments');self.assertEqual(fees.status_code,200);self.assertNotIn(b'Pupil Campus B',fees.data)
    def test_ungranted_writes_settings_and_unknown_api_are_denied(self):
        self.login();token=self.token()
        self.assertEqual(self.c.post('/records/student/new',data={'_csrf':token,'name':'Forged'}).status_code,403)
        self.assertEqual(self.c.get('/workspace/core/users').status_code,403)
        self.assertEqual(self.c.get('/workspace/core/institute').status_code,403)
        self.assertEqual(self.c.get('/workspace/finance/fee-posting').status_code,403)
        self.assertEqual(self.c.post('/workspace/finance/fee-posting',data={'_csrf':token,'enabled':'1','version':'0'}).status_code,403)
        self.assertEqual(self.c.get('/api/v1/summary').status_code,403)
    def test_cash_account_and_payment_date_rules_are_checked_before_payment(self):
        self.login();token=self.token()
        base={'_csrf':token,'student_id':'1','account':'Cash at Bank','paid_date':date.today().isoformat()}
        self.assertEqual(self.c.post('/workspace/pay',data=base).status_code,403)
        base.update(account='Cash in Hand',paid_date='2020-01-01');self.assertEqual(self.c.post('/workspace/pay',data=base).status_code,403)
    def test_account_or_permission_change_invalidates_an_existing_sign_in(self):
        self.login()
        with app.test_request_context('/'):
            g.institute_engine=app.extensions['identity_helpers']['engine'](self.school);db.session.remove();staff=db.session.get(self.Staff,self.sid);staff.data={**staff.data,'permissions':{}};db.session.commit();db.session.remove()
        g.pop('institute_engine',None);self.assertEqual(self.c.get('/records/student').status_code,302)
    def test_primary_owner_retains_access_and_can_create_staff_with_no_permissions(self):
        self.assertEqual(self.login('owner@example.invalid').status_code,302)
        self.assertEqual(self.c.get('/workspace/core/users').status_code,200);self.assertEqual(self.c.get('/workspace/core/users/new').status_code,200)
        self.assertEqual(self.c.get('/workspace/core/users/1').status_code,200)
    def test_owner_can_save_campus_permissions_and_role_labels_without_changing_password(self):
        self.login('owner@example.invalid');token=self.token()
        r=self.c.post('/workspace/core/users/1',data={'_csrf':token,'version':'1','action':'permissions','perm_admissions.view':['Campus B']});self.assertEqual(r.status_code,302)
        self.login();page=self.c.get('/records/student');self.assertIn(b'Pupil Campus B',page.data);self.assertNotIn(b'Pupil Campus A',page.data)
    def tenant(self,fn):
        with app.test_request_context('/'):
            g.staff_principal=None;g.access_campuses=None
            g.institute_engine=app.extensions['identity_helpers']['engine'](self.school);db.session.remove();value=fn();db.session.commit();db.session.remove()
        g.pop('institute_engine',None);return value
    def two_step(self):
        def save():
            row=db.session.get(self.Staff,1);row.data={**row.data,'two_step':True}
        self.tenant(save)
    def payment(self,**extra):
        from zoneinfo import ZoneInfo
        from datetime import datetime
        data={'_csrf':self.token(),'student_id':'1','mode':'current','bill_id':'1','token':'fictionalPaymentToken_1234567890','account':'Cash in Hand','paid_date':datetime.now(ZoneInfo('Asia/Karachi')).date().isoformat(),'amount_1':'25','action':'pay'};data.update(extra)
        return self.c.post('/workspace/pay',data=data)
    def balances(self):return self.tenant(lambda:(db.session.get(self.ops['bill'],1).paid,self.ops['receipt'].query.count(),self.ops['workflow'].query.filter_by(kind='staff-payment-approval').count()))
    def test_two_step_request_does_not_post_until_different_owner_approves_and_cannot_replay(self):
        self.two_step();self.login();self.assertEqual(self.payment().status_code,302);self.assertEqual(self.balances(),(0,0,1))
        self.assertEqual(self.c.get('/workspace/core/users/payment-requests').status_code,200)
        self.assertEqual(self.payment().status_code,302);self.assertEqual(self.balances(),(0,0,1))
        self.assertEqual(self.c.post('/workspace/core/users/payment-requests',data={'_csrf':self.token(),'id':'1','action':'approve'}).status_code,403)
        self.login('owner@example.invalid');token=self.token()
        self.assertEqual(self.c.get('/workspace/core/users/payment-requests').status_code,200)
        response=self.c.post('/workspace/core/users/payment-requests',data={'_csrf':token,'id':'1','action':'approve'});self.assertEqual(response.status_code,302,response.data)
        self.assertEqual(self.balances(),(2500,1,1))
        self.assertEqual(self.c.post('/workspace/core/users/payment-requests',data={'_csrf':token,'id':'1','action':'approve'}).status_code,422);self.assertEqual(self.balances(),(2500,1,1))
    def test_queue_reject_stale_balance_and_cross_campus_forgery(self):
        self.two_step();self.login();self.assertEqual(self.payment(amount_2='25').status_code,403);self.assertEqual(self.balances(),(0,0,0))
        self.assertEqual(self.payment().status_code,302)
        def change():db.session.get(self.ops['bill'],1).paid=1000
        self.tenant(change);self.login('owner@example.invalid');token=self.token()
        self.assertEqual(self.c.post('/workspace/core/users/payment-requests',data={'_csrf':token,'id':'1','action':'approve'}).status_code,422);self.assertEqual(self.balances(),(1000,0,1))
        self.assertEqual(self.c.post('/workspace/core/users/payment-requests',data={'_csrf':token,'id':'1','action':'reject','reason':'Balance changed'}).status_code,302);self.assertEqual(self.balances(),(1000,0,1))
    def test_queue_rejects_missing_csrf_discount_account_and_missing_payment_day(self):
        self.two_step();self.login()
        self.assertEqual(self.payment(_csrf='').status_code,400)
        self.assertEqual(self.payment(discount_1='5').status_code,403)
        self.assertEqual(self.payment(paid_date='').status_code,422);self.assertEqual(self.balances(),(0,0,0))
    def test_staff_can_change_own_password_without_access_admin_and_old_password_fails(self):
        self.login();new='Changed-fictional-password-2026'
        self.assertEqual(self.c.get('/workspace/core/users/my-password').status_code,200)
        self.assertEqual(self.c.post('/workspace/core/users/my-password',data={'_csrf':self.token(),'current_password':'wrong','password':new,'confirm_password':new}).status_code,422)
        self.assertEqual(self.c.post('/workspace/core/users/my-password',data={'_csrf':self.token(),'current_password':self.password,'password':new,'confirm_password':new}).status_code,302)
        self.assertEqual(self.c.get('/workspace/dashboard').status_code,200)
        self.assertEqual(self.login().status_code,200);self.assertEqual(self.login(password=new).status_code,302)
    def test_primary_owner_can_change_own_password(self):
        self.login('owner@example.invalid');new='Changed-owner-password-2026'
        self.assertEqual(self.c.post('/workspace/core/users/my-password',data={'_csrf':self.token(),'current_password':self.password,'password':new,'confirm_password':new}).status_code,302)
        self.assertEqual(self.c.get('/workspace/dashboard').status_code,200);self.assertEqual(self.login('owner@example.invalid',new).status_code,302)
    def test_grid_preferences_are_saved_used_in_exports_and_copied_without_rights(self):
        self.login();self.assertEqual(self.c.post('/workspace/core/users/my-grids',data={'_csrf':self.token(),'grid':'users','size':'25','columns':['username','status']}).status_code,302)
        def second():
            e=Employee(employee_no='E2',name='Another fictional teacher',role='Teacher',status='Active');db.session.add(e);db.session.flush();db.session.add(self.rm['employee'](employee_id=e.id,data={'campus':'Campus B'}));db.session.add(self.Staff(employee_id=e.id,username='teacher.two',password_hash=generate_password_hash(self.password),active=True,data={'permissions':{},'campuses':[]}))
        self.tenant(second);self.login('owner@example.invalid')
        response=self.c.post('/workspace/core/users/copy-grid',data={'_csrf':self.token(),'source':'1','target':'2','source_version':'2','version':'1'});self.assertEqual(response.status_code,302,response.data)
        copied=self.tenant(lambda:dict(db.session.get(self.Staff,2).data));self.assertEqual(copied['grid_settings']['users']['columns'],['username','status']);self.assertEqual(copied['permissions'],{})
    def test_owner_creates_staff_and_new_account_has_no_implicit_rights(self):
        def employee():
            e=Employee(employee_no='E2',name='New fictional employee',role='Teacher',status='Active');db.session.add(e);db.session.flush();db.session.add(self.rm['employee'](employee_id=e.id,data={'campus':'Campus A'}))
        self.tenant(employee);self.login('owner@example.invalid')
        response=self.c.post('/workspace/core/users/new',data={'_csrf':self.token(),'version':'0','employee_id':'2','username':'new.teacher','password':self.password,'active':'1','role':'User','campuses':['Campus A'],'accounts':['Cash in Hand'],'payment_mode':'day','payment_days':'0'});self.assertEqual(response.status_code,302,response.data)
        self.assertEqual(self.login('new.teacher').status_code,302);self.assertEqual(self.c.get('/records/student').status_code,403)
    def test_payroll_send_requires_pay_permission_not_update(self):
        def scope():
            r=db.session.get(self.Staff,1);r.data={**r.data,'permissions':{'payroll.update':['Campus A']}}
        self.tenant(scope);self.login()
        self.assertEqual(self.c.post('/workspace/payroll',data={'_csrf':self.token(),'action':'send','month':'2026-10','ids':['1'],'credit':'Cash in Hand','debit':'Cash in Hand','paid_date':date.today().isoformat()}).status_code,403)
    def test_direct_payment_request_and_discount_approval_keep_real_receipt_amounts(self):
        self.two_step();self.login()
        response=self.c.post('/workspace/direct-payment',data={'_csrf':self.token(),'number':'1','lookup':'sid','token':'directQueuePayment_1234567890','account':'Cash in Hand','paid_date':date.today().isoformat(),'amount_1':'10','action':'pay'});self.assertEqual(response.status_code,302,response.data);self.assertEqual(self.balances(),(0,0,1))
        self.login('owner@example.invalid');self.assertEqual(self.c.post('/workspace/core/users/payment-requests',data={'_csrf':self.token(),'id':'1','action':'approve'}).status_code,302);self.assertEqual(self.balances(),(1000,1,1))
        def discount_access():
            r=db.session.get(self.Staff,1);r.data={**r.data,'accounts':['Cash in Hand','Discounts']}
        self.tenant(discount_access);self.login();self.assertEqual(self.payment(amount_1='5',discount_1='2',token='discountQueuePayment_1234567890').status_code,302)
        self.login('owner@example.invalid');self.assertEqual(self.c.post('/workspace/core/users/payment-requests',data={'_csrf':self.token(),'id':'2','action':'approve'}).status_code,302)
        self.assertEqual(self.tenant(lambda:(db.session.get(self.ops['bill'],1).paid,db.session.get(self.ops['bill'],1).discount)),(1500,200))
        audit=self.tenant(lambda:self.ops['audit'].query.filter_by(action='Fee payment').one().data);self.assertEqual(audit['changes'][0]['after']['paid_paisa'],1500);self.assertEqual(audit['_activity_actor']['label'],'owner@example.invalid')
    def test_self_approval_is_denied_even_with_approval_permission(self):
        self.two_step()
        def allow():
            r=db.session.get(self.Staff,1);r.data={**r.data,'permissions':{**r.data['permissions'],'fees.approve':['Campus A']}}
        self.tenant(allow);self.login();self.assertEqual(self.payment().status_code,302)
        response=self.c.post('/workspace/core/users/payment-requests',data={'_csrf':self.token(),'id':'1','action':'approve'});self.assertEqual(response.status_code,403);self.assertIn(b'different user',response.data);self.assertEqual(self.balances(),(0,0,1))
    def test_certificate_delete_and_create_require_their_own_permissions(self):
        self.login('owner@example.invalid');self.assertEqual(self.c.post('/workspace/core/certificates/new',data={'_csrf':self.token(),'version':'0','name':'Fictional design','campus':'Campus A','body':'<p>Hello</p>'}).status_code,302)
        def allow():
            r=db.session.get(self.Staff,1);r.data={**r.data,'permissions':{'certificates.update':['Campus A','Campus B']}}
        self.tenant(allow);self.login();token=self.token()
        self.assertEqual(self.c.post('/workspace/core/certificates/1/delete',data={'_csrf':token,'version':'1','confirm':'yes'}).status_code,403)
        self.assertEqual(self.c.post('/workspace/core/certificates/new',data={'_csrf':token,'version':'0','name':'Forged','campus':'Campus A','body':'Forged'}).status_code,403)
        self.assertEqual(self.tenant(lambda:app.extensions['certificate_models']['template'].query.count()),1)
    def test_disabled_requester_cannot_have_an_old_request_approved(self):
        self.two_step();self.login();self.payment()
        def disable():db.session.get(self.Staff,1).active=False
        self.tenant(disable);self.login('owner@example.invalid')
        self.assertEqual(self.c.post('/workspace/core/users/payment-requests',data={'_csrf':self.token(),'id':'1','action':'approve'}).status_code,422);self.assertEqual(self.balances(),(0,0,1))
    def test_simultaneous_approvals_post_one_receipt_only(self):
        from concurrent.futures import ThreadPoolExecutor
        self.two_step();self.login();self.payment();self.login('owner@example.invalid')
        with self.c.session_transaction() as saved:credentials=dict(saved)
        def approve(_):
            client=app.test_client()
            with client.session_transaction() as cookie:cookie.update(credentials)
            return client.post('/workspace/core/users/payment-requests',data={'_csrf':credentials['record_csrf'],'id':'1','action':'approve'}).status_code
        # Concurrent requests need separate real connections for the identity
        # registry too; in-memory SQLite's StaticPool shares one DBAPI handle.
        from sqlalchemy import create_engine,select
        original=db.engines[None];control=create_engine('sqlite:///'+self.dir.name+'/control.db',connect_args={'timeout':20})
        tables=[t for t in db.metadata.sorted_tables if t.info.get('identity_control')]
        db.session.remove();db.metadata.create_all(control,tables=tables)
        with original.connect() as source,control.begin() as target:
            for table in tables:
                records=[dict(r) for r in source.execute(select(table)).mappings()]
                if records:target.execute(table.insert(),records)
        db.engines[None]=control
        try:
            with ThreadPoolExecutor(max_workers=2) as pool:statuses=list(pool.map(approve,range(2)))
            self.assertEqual(sorted(statuses),[302,422]);self.assertEqual(self.balances(),(2500,1,1))
        finally:db.session.remove();db.engines[None]=original;control.dispose()
    def test_account_email_cannot_collide_with_another_username(self):
        def employee():
            e=Employee(employee_no='E2',name='Fictional second teacher',role='Teacher',status='Active');db.session.add(e);db.session.flush()
        self.tenant(employee);self.login('owner@example.invalid')
        response=self.c.post('/workspace/core/users/new',data={'_csrf':self.token(),'version':'0','employee_id':'2','username':'teacher@example.invalid','email':'another@example.invalid','password':self.password,'active':'1','role':'User','payment_mode':'day','payment_days':'0'});self.assertEqual(response.status_code,422)
        self.assertEqual(self.tenant(lambda:self.Staff.query.count()),1)
    def test_role_titles_save_only_labels_and_reject_duplicate_titles(self):
        self.login('owner@example.invalid');token=self.token()
        values={'_csrf':token,'version':'0','Super Admin':'Principal','Admin':'Office Admin','User':'Staff member','Teacher':'Teacher'}
        self.assertEqual(self.c.post('/workspace/core/users/roles',data=values).status_code,302)
        self.assertIn(b'Principal',self.c.get('/workspace/core/users/roles').data)
        values.update(version='1',Teacher='Principal');self.assertEqual(self.c.post('/workspace/core/users/roles',data=values).status_code,422)
        self.login();self.assertEqual(self.c.get('/workspace/core/users').status_code,403)
    def test_saved_grid_columns_are_used_by_matching_user_logging_export(self):
        self.login('owner@example.invalid')
        self.assertEqual(self.c.post('/workspace/core/users/my-grids',data={'_csrf':self.token(),'grid':'logs','size':'25','columns':['summary']}).status_code,302)
        response=self.c.get('/workspace/core/user-logging?export=csv');self.assertEqual(response.status_code,200);self.assertEqual(response.data.decode('utf-8-sig').splitlines()[0],'What happened')
        self.assertEqual(self.c.post('/workspace/core/users/my-grids',data={'_csrf':self.token(),'grid':'logs','size':'25','columns':['password_hash']}).status_code,422)

    def test_finance_requires_separate_all_campus_permissions(self):
        self.login();self.assertEqual(self.c.get('/workspace/finance/groups').status_code,403)
        with app.test_request_context('/'):
            g.institute_engine=app.extensions['identity_helpers']['engine'](self.school);db.session.remove()
            person=db.session.get(self.Staff,self.sid);data=dict(person.data);permissions=dict(data['permissions']);permissions['finance.view']=['Campus A'];data['permissions']=permissions;person.data=data;db.session.commit();self.version=person.version;db.session.remove()
        with self.c.session_transaction() as sess:sess['staff_version']=self.version
        self.assertEqual(self.c.get('/workspace/finance/groups').status_code,403)
        with app.test_request_context('/'):
            g.institute_engine=app.extensions['identity_helpers']['engine'](self.school);db.session.remove()
            person=db.session.get(self.Staff,self.sid);data=dict(person.data);permissions=dict(data['permissions']);permissions['finance.view']=['Campus A','Campus B'];data['permissions']=permissions;person.data=data;db.session.commit();self.version=person.version;db.session.remove()
        with self.c.session_transaction() as sess:sess['staff_version']=self.version
        self.assertEqual(self.c.get('/workspace/finance/groups').status_code,200)
        self.assertEqual(self.c.post('/workspace/finance/groups/new',data={'_csrf':self.token(),'version':'0','name':'Forbidden','account_class':'Assets','active':'1'}).status_code,403)
        self.assertEqual(self.c.get('/workspace/finance/chart-of-accounts?print=1').status_code,403)

    def test_closing_or_reopening_finance_period_requires_approval(self):
        def grant_finance(approval=False):
            with app.test_request_context('/'):
                g.institute_engine=app.extensions['identity_helpers']['engine'](self.school);db.session.remove()
                person=db.session.get(self.Staff,self.sid);data=dict(person.data);permissions=dict(data['permissions'])
                for action in ('view','create','update')+ (('approve',) if approval else ()):
                    permissions['finance.'+action]=['Campus A','Campus B']
                data['permissions']=permissions;person.data=data;db.session.commit();version=person.version;db.session.remove()
            with self.c.session_transaction() as sess:sess['staff_version']=version
        self.login();grant_finance()
        form=dict(_csrf=self.token(),version='0',begin='2026-01-01',end='2026-12-31',closed='1')
        self.assertEqual(self.c.post('/workspace/finance/periods/new',data=form).status_code,403)
        form['closed']='0';response=self.c.post('/workspace/finance/periods/new',data=form);self.assertEqual(response.status_code,302)
        self.assertEqual(self.c.post(response.location+'/edit',data={**form,'version':'1','closed':'1'}).status_code,403)
        grant_finance(True)
        self.assertEqual(self.c.post(response.location+'/edit',data={**form,'version':'1','closed':'1'}).status_code,302)

    def test_ledger_posting_and_print_do_not_use_student_fee_permissions(self):
        self.login()
        self.assertEqual(self.c.get('/workspace/finance/ledger/entry/journal').status_code,403)
        self.assertEqual(self.c.post('/workspace/finance/ledger/entry/journal',data={'_csrf':self.token()}).status_code,403)
        self.assertEqual(self.c.get('/workspace/finance/ledger/report/profit?print=1').status_code,403)
        with app.test_request_context('/'):
            g.institute_engine=app.extensions['identity_helpers']['engine'](self.school);db.session.remove();person=db.session.get(self.Staff,self.sid)
            data=dict(person.data);permissions=dict(data['permissions']);permissions['finance.create']=['Campus A','Campus B'];data['permissions']=permissions;person.data=data;db.session.commit();version=person.version;db.session.remove()
        with self.c.session_transaction() as sess:sess['staff_version']=version
        self.assertEqual(self.c.post('/workspace/finance/ledger/entry/journal',data={'_csrf':self.token(),'save_action':'print'}).status_code,403)

    def test_finance_reports_require_distinct_view_print_update_delete_grants(self):
        self.login()
        for path in ('journals','general','daily'):
            self.assertEqual(self.c.get('/workspace/finance/reports/'+path).status_code,403)
        self.assertEqual(self.c.get('/workspace/finance/reports/journal/1/edit').status_code,403)
        self.assertEqual(self.c.post('/workspace/finance/reports/journal/void',data={'_csrf':self.token()}).status_code,403)
        def grants(actions):
            with app.test_request_context('/'):
                g.institute_engine=app.extensions['identity_helpers']['engine'](self.school);db.session.remove();person=db.session.get(self.Staff,self.sid)
                data=dict(person.data);data['permissions']={'finance.'+action:['Campus A','Campus B'] for action in actions};person.data=data;db.session.commit();version=person.version;db.session.remove()
            with self.c.session_transaction() as sess:sess['staff_version']=version
        grants(['view'])
        for path in ('journals','general','daily'):
            self.assertEqual(self.c.get('/workspace/finance/reports/'+path).status_code,200)
            self.assertEqual(self.c.get('/workspace/finance/reports/'+path+'?print=1').status_code,403)
        self.assertEqual(self.c.get('/workspace/finance/reports/journal/1/edit').status_code,403)
        grants(['update'])
        self.assertEqual(self.c.post('/workspace/finance/reports/journal/void',data={'_csrf':self.token()}).status_code,403)
        self.assertEqual(self.c.post('/workspace/finance/reports/journal/1/edit',data={'_csrf':self.token(),'save_action':'print'}).status_code,403)

    def test_fee_audit_and_void_reports_require_full_finance_scope(self):
        self.login()
        paths=('audit/fees','audit/challans/voided','reports/voided','ledger/setup')
        for path in paths:self.assertEqual(self.c.get('/workspace/finance/'+path).status_code,403)
        for allowed in (['Campus A'],['Campus A','Campus B']):
            with app.test_request_context('/'):
                g.institute_engine=app.extensions['identity_helpers']['engine'](self.school);db.session.remove();person=db.session.get(self.Staff,self.sid)
                person.data={**person.data,'permissions':{'finance.view':allowed}};db.session.commit();version=person.version;db.session.remove()
            with self.c.session_transaction() as sess:sess['staff_version']=version
            for path in paths:self.assertEqual(self.c.get('/workspace/finance/'+path).status_code,200 if len(allowed)==2 else 403)
        self.assertEqual(self.c.get('/workspace/finance/audit/fees?export=csv').status_code,403)
        self.assertEqual(self.c.get('/workspace/finance/audit/fees?print=1').status_code,403)

    def test_requisition_posting_requires_manage_action_campus_and_cash_grants(self):
        from datetime import datetime,timezone
        import secrets
        now=datetime.now(timezone.utc);today=app.extensions['ledger_helpers']['today']()
        def seed():
            fm=app.extensions['finance_models'];rm=app.extensions['requisition_models'];stamp=dict(created_at=now,updated_at=now,created_by='QA',updated_by='QA')
            group=fm['group'](name='QA assets',account_class='Assets',active=True,**stamp);db.session.add(group);db.session.flush()
            for i,name in enumerate(('Cash in Hand','Staff Advances'),1000):db.session.add(fm['account'](code=i,name=name,group_id=group.id,inactive=False,**stamp))
            db.session.add(fm['period'](begin=today,end=today,closed=False,**stamp))
            from requisitions import DEFAULTS
            db.session.flush();cash=fm['account'].query.filter_by(name='Cash in Hand').one();advance=fm['account'].query.filter_by(name='Staff Advances').one()
            db.session.add(rm['config'](id=1,data={**DEFAULTS,'advance_account':advance.id,'pay_account':cash.id}))
            for rid,campus in ((1,'Campus A'),(2,'Campus B')):db.session.add(rm['request'](id=rid,number='QA-'+str(rid),campus=campus,actor_key='staff:1',raised_by='QA',category='Procurement / Supplies',purpose='Fictional finance QA',items=[],estimated=2000,approved=2000,status='Approved',token=secrets.token_urlsafe(32),fingerprint='f'))
            return cash.id
        cash_id=self.tenant(seed);self.login()
        path='/workspace/finance/requisitions/1/posting/issue'
        self.assertEqual(self.c.get(path).status_code,403)
        def grants(actions,account=True):
            def save():
                p=db.session.get(self.Staff,self.sid);p.data={**p.data,'permissions':{'requisitions.'+a:['Campus A'] for a in actions},'accounts':['Cash in Hand'] if account else []};db.session.flush();return p.version
            version=self.tenant(save)
            with self.c.session_transaction() as sess:sess['staff_version']=version
        grants(['manage']);self.assertEqual(self.c.get(path).status_code,200)
        form=dict(_csrf=self.token(),post_token=secrets.token_urlsafe(32),version='1',day=today.isoformat(),amount='10',account_id=str(cash_id))
        self.assertEqual(self.c.post(path,data=form).status_code,403)
        grants(['manage','pay'],False);self.assertEqual(self.c.post(path,data=form).status_code,403)
        grants(['manage','pay']);self.assertEqual(self.c.get('/workspace/finance/requisitions/2/posting/issue').status_code,404)
        self.assertEqual(self.c.post(path,data=form).status_code,302)
        self.assertEqual(self.tenant(lambda:app.extensions['requisition_models']['movement'].query.count()),1)
        self.assertEqual(self.c.get('/workspace/finance/requisitions/reports?print=1').status_code,403)
        self.assertEqual(self.c.post('/workspace/finance/requisitions/1/posting/return',data={**form,'version':'2'}).status_code,403)

    def test_cash_and_shareholders_use_finance_permissions(self):
        self.login()
        for path in ('cash-report','shareholders','shareholders/new','shareholders/1/edit','shareholders/1/transactions'):
            self.assertEqual(self.c.get('/workspace/finance/'+path).status_code,403)
        self.assertEqual(self.c.post('/workspace/finance/shareholders/new',data={'_csrf':self.token()}).status_code,403)
        with app.test_request_context('/'):
            g.institute_engine=app.extensions['identity_helpers']['engine'](self.school);db.session.remove();person=db.session.get(self.Staff,self.sid)
            data=dict(person.data);data['permissions']={'finance.view':['Campus A','Campus B']};person.data=data;db.session.commit();version=person.version;db.session.remove()
        with self.c.session_transaction() as sess:sess['staff_version']=version
        for path in ('cash-report','shareholders'):
            self.assertEqual(self.c.get('/workspace/finance/'+path).status_code,200)
            self.assertEqual(self.c.get('/workspace/finance/'+path+'?print=1').status_code,403)
        self.assertEqual(self.c.get('/workspace/finance/shareholders/new').status_code,403)

    def test_requisitions_my_rows_and_decisions_are_separately_scoped(self):
        R=app.extensions['requisition_models']['request']
        def seed():
            for rid,campus,key,purpose in [(1,'Campus A','staff:'+str(self.sid),'Own A'),(2,'Campus B','staff:'+str(self.sid),'Own B'),(9,'Campus A','owner:1','Other A'),(99,'Campus B','owner:1','Other B')]:
                db.session.add(R(id=rid,number='REQ-'+str(rid),campus=campus,actor_key=key,raised_by=key,category='Procurement / Supplies',purpose=purpose,items=[{'item':'Test','qty':'1','unit_price':1000,'amount':1000}],estimated=1000,token='fictional-token-'+str(rid),fingerprint='test'))
            p=db.session.get(self.Staff,self.sid);p.data={**p.data,'permissions':{'requisitions.view':['Campus A'],'requisitions.create':['Campus A']}}
            db.session.flush();return p.version
        version=self.tenant(seed);self.login()
        page=self.c.get('/workspace/finance/requisitions/mine');self.assertEqual(page.status_code,200);self.assertIn(b'Own A',page.data);self.assertNotIn(b'Own B',page.data);self.assertNotIn(b'Other A',page.data)
        for rid in (2,9):self.assertEqual(self.c.get(f'/workspace/finance/requisitions/{rid}').status_code,404)
        for endpoint in ('approvals','issue','settle','reports','settings'):
            self.assertEqual(self.c.get('/workspace/finance/requisitions/'+endpoint).status_code,403)
        token=self.token();form=dict(_csrf=token,post_token='FictionalToken012345678901234567890123',campus='Campus A',category='Procurement / Supplies',purpose='New A',item=['Paper'],qty=['1'],unit_price=['1'])
        response=self.c.post('/workspace/finance/requisitions/mine',data=form);self.assertEqual(response.status_code,302);self.assertTrue(response.location.endswith('/100'))
        form['campus']='Campus B';self.assertEqual(self.c.post('/workspace/finance/requisitions/mine',data=form).status_code,403)
        self.assertEqual(self.c.post('/workspace/finance/requisitions/9/decide',data={'_csrf':token}).status_code,403)
        def approve_permission():
            p=db.session.get(self.Staff,self.sid);p.data={**p.data,'permissions':{'requisitions.approve':['Campus A']}};db.session.flush();return p.version
        version=self.tenant(approve_permission)
        with self.c.session_transaction() as sess:sess['staff_version']=version
        page=self.c.get('/workspace/finance/requisitions/approvals');self.assertEqual(page.status_code,200);self.assertIn(b'Other A',page.data);self.assertNotIn(b'Own B',page.data)
        r=self.c.post('/workspace/finance/requisitions/9/decide',data=dict(_csrf=self.token(),post_token='DecisionToken012345678901234567890123',version='1',decision='Approved',approved='10'));self.assertEqual(r.status_code,302)

    def test_internal_snapshot_capture_is_whole_institute_and_restores_staff_scope(self):
        def check():
            p=db.session.get(self.Staff,self.sid);g.staff_principal=p;g.access_campuses={'Campus A'}
            app.extensions['snapshot_helpers']['capture']()
            self.assertIs(g.staff_principal,p);self.assertEqual(g.access_campuses,{'Campus A'})
            g.staff_principal=None;g.access_campuses=None
            row=app.extensions['snapshot_models']['snapshot'].query.filter_by(campus='Campus B').one()
            self.assertEqual(row.metrics['strength'],1);self.assertEqual(row.metrics['expected'],10000)
        self.tenant(check)
        self.login();self.assertEqual(self.c.get('/workspace/finance/snapshots').status_code,403)
        self.assertEqual(self.c.post('/workspace/finance/snapshots/capture',data={'_csrf':self.token()}).status_code,403)
