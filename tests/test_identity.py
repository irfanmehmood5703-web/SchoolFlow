"""Exercise real sign-in gates and two databases with colliding record IDs."""
import os
import tempfile
import time
import unittest
from datetime import date
from flask import g
os.environ['DATABASE_URL'] = 'sqlite:///:memory:'
from app import app, db, Student

PASSWORD = 'Fictional-test-password-2026'


class IdentityTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        app.config.update(TESTING=True, IDENTITY_ENFORCE_IN_TESTS=True,
                          INSTITUTE_DATABASE_DIR=self.directory.name,
                          SECRET_KEY='identity-fictional-test', PUBLIC_DEMO_ENABLED=True)
        self.ctx = app.app_context(); self.ctx.push()
        db.drop_all(); db.create_all()
        self.models = app.extensions['identity_models']
        provision = app.extensions['identity_helpers']['provision']
        self.a = provision('TEST-A', 'Fictional School A', 'owner@example.invalid', PASSWORD).id
        self.b = provision('TEST-B', 'Fictional School B', 'owner@example.invalid', PASSWORD).id
        self.seed(self.a, 'Only School A', extra=True)
        self.seed(self.b, 'Only School B')
        db.session.add(Student(admission_no='DEMO-1', name='Only Public Demo'))
        db.session.commit(); db.session.remove()
        self.client = app.test_client()

    def tearDown(self):
        db.session.remove(); db.drop_all(); self.ctx.pop()
        app.config['IDENTITY_ENFORCE_IN_TESTS'] = False
        app.config['INSTITUTE_DATABASE_DIR'] = None
        self.directory.cleanup()

    def seed(self, institute_id, name, extra=False):
        rm = app.extensions['record_models']
        with app.test_request_context('/'):
            g.institute_engine = app.extensions['identity_helpers']['engine'](institute_id)
            db.session.add(Student(id=1, admission_no='SAME-001', name=name, status='Active'))
            if extra:
                db.session.add(Student(id=2, admission_no='SAME-002', name='Secret A second pupil'))
            db.session.add(rm['settings'](category='campus', value='Campus '+name, class_name=''))
            db.session.add(rm['file'](id=1, owner_kind='student', owner_id=1, title='Document', filename='test.txt', mime='text/plain', photo=False, content=name.encode(), sha256='test'))
            db.session.flush()
            ops = app.extensions['ops_models']; cm = app.extensions['certificate_models']
            db.session.add(ops['bill'](student_id=1, month='2026-10', due=date(2026,10,10), lines=[dict(particular=name, amount=12345)]))
            campus = cm['campus'](campus='Campus '+name, data={'name':name})
            db.session.add(campus); db.session.flush()
            template = cm['template'](campus_id=campus.id, key='school-leaving', name=name, header='', body='<p>'+name+'</p>', footer='')
            db.session.add(template); db.session.flush()
            batch = cm['batch'](token='same-token-in-both-schools', template_id=template.id, student_ids=[1], copy_type='Original')
            db.session.add(batch); db.session.flush()
            db.session.add(cm['issue'](batch_id=batch.id, student_id=1, template_id=template.id, campus=campus.campus, document_name=name, student_name=name, reference='SLC-1', snapshot={}, html='<p>'+name+'</p>'))
            db.session.commit()
            db.session.remove()

    def csrf(self, client=None):
        client = client or self.client
        client.get('/auth/institute')
        with client.session_transaction() as sess:
            return sess['record_csrf']

    def login(self, code='TEST-A', password=PASSWORD, client=None):
        client = client or self.client
        token = self.csrf(client)
        response = client.post('/auth/institute', data={'_csrf':token, 'code':code})
        if response.status_code != 302:
            return response
        with client.session_transaction() as sess:
            token = sess['record_csrf']
        return client.post('/auth/login', data={'_csrf':token, 'email':'OWNER@example.invalid', 'password':password})

    def test_inline_admission_options_are_isolated_between_schools(self):
        self.assertEqual(self.login().status_code,302)
        token=self.csrf()
        self.assertEqual(self.client.post('/records/options',data={'_csrf':token,'category':'class_name','value':'Only School A Class'}).status_code,200)
        self.assertIn(b'Only School A Class',self.client.get('/records/student/new').data)
        self.assertEqual(self.login('TEST-B').status_code,302)
        page=self.client.get('/records/student/new')
        self.assertNotIn(b'Only School A Class',page.data)
        self.assertIn(b'Christianity',page.data)

    def test_core_profile_and_mapping_payload_are_school_private(self):
        self.assertEqual(self.client.get('/workspace/core/institute').status_code,302)
        self.assertEqual(self.client.get('/workspace/core/admission-options').status_code,302)
        self.login();token=self.csrf()
        response=self.client.post('/workspace/core/institute',data={'_csrf':token,'action':'profile','version':'1','name':'Private School A Setup'})
        self.assertEqual(response.status_code,302)
        self.assertIn(b'Private School A Setup',self.client.get('/workspace/core/institute').data)
        self.client.post('/workspace/core/institute',data={'_csrf':token,'action':'campus','version':'0','campus':'Private Campus A','active':'1'})
        self.assertIn('Private Campus A',self.client.get('/workspace/core/admission-options').json['campuses'])
        self.login('TEST-B')
        self.assertNotIn(b'Private School A Setup',self.client.get('/workspace/core/institute').data)
        self.assertNotIn('Private Campus A',self.client.get('/workspace/core/admission-options').json['campuses'])

    def test_public_landing_and_every_workspace_entry_is_gated(self):
        self.assertIn(b'More time for', self.client.get('/').data)
        for path in ['/workspace/dashboard', '/records/student', '/records/files/1', '/workspace/certificates', '/admissions', '/hrm', '/attendance', '/exams', '/settings']:
            response = self.client.get(path)
            self.assertEqual(response.status_code, 302, path)
            self.assertTrue(response.location.endswith('/auth/institute'), path)
        self.assertEqual(self.client.get('/api/v1/summary').status_code, 401)
        self.assertEqual(self.client.get('/healthz').json['status'], 'ok')

    def test_three_step_login_normalisation_session_rotation_and_logout(self):
        old = self.csrf()
        self.assertEqual(self.login('test-a').status_code, 302)
        with self.client.session_transaction() as sess:
            self.assertEqual(sess['institute_id'], self.a)
            self.assertNotEqual(old, sess['record_csrf'])
            token = sess['record_csrf']
            self.assertNotIn('demo', sess)
        page = self.client.get('/records/student').data
        self.assertIn(b'Only School A', page); self.assertIn(b'Fictional School A', page)
        self.assertEqual(self.client.get('/auth/logout').status_code, 405)
        self.assertEqual(self.client.post('/auth/logout', data={'_csrf':token}).status_code, 302)
        self.assertEqual(self.client.get('/records/student').status_code, 302)

    def test_two_institutes_colliding_ids_files_exports_settings_and_qr(self):
        other = app.test_client()
        self.login(); self.login('TEST-B', client=other)
        for client, expected, excluded in [(self.client, b'Only School A', b'Only School B'), (other, b'Only School B', b'Only School A')]:
            for path in ['/records/student', '/records/student/1', '/records/student/export.csv', '/records/settings']:
                page = client.get(path)
                self.assertEqual(page.status_code, 200, path)
                self.assertIn(expected, page.data, path); self.assertNotIn(excluded, page.data, path)
                self.assertNotIn(b'Only Public Demo', page.data)
            self.assertEqual(client.get('/records/files/1').data, expected)
        self.assertEqual(other.get('/records/student/2').status_code, 404)
        self.assertEqual(other.get('/records/student/2/edit').status_code, 404)
        a = self.client.get('/workspace/certificates/qr/1.svg')
        b = other.get('/workspace/certificates/qr/1.svg')
        self.assertEqual(a.status_code, 200); self.assertEqual(b.status_code, 200)
        self.assertNotEqual(a.data, b.data)

    def test_school_settings_and_subject_mappings_cannot_cross_tenants(self):
        other=app.test_client();self.login();self.login('TEST-B',client=other)
        with self.client.session_transaction() as sess:token=sess['record_csrf']
        result=self.client.post('/workspace/core/exam/display',data={'_csrf':token,'version':'0','decimals':'3','written':'School A Theory'})
        self.assertEqual(result.status_code,302)
        self.assertIn(b'School A Theory',self.client.get('/workspace/core/exam/display').data)
        self.assertNotIn(b'School A Theory',other.get('/workspace/core/exam/display').data)
        # Catalog values remain bound to the authenticated institute too.
        self.client.post('/workspace/core/hrm/departments',data={'_csrf':token,'version':'0','name':'Only School A Department','action':'save'})
        self.assertNotIn(b'Only School A Department',other.get('/workspace/core/hrm/departments').data)
        public=app.test_client()
        for path in ['/workspace/core/hrm/attendance-lock','/workspace/core/exam/subject-options','/workspace/core/hrm/designation-options','/workspace/core/hrm/employee-qr/1.svg']:
            self.assertEqual(public.get(path).status_code,302)

    def test_fee_heads_scoped_schedules_and_previews_are_isolated(self):
        other=app.test_client();self.login();self.login('TEST-B',client=other)
        for client,name in [(self.client,'Only School A'),(other,'Only School B')]:
            with client.session_transaction() as session:token=session['record_csrf']
            response=client.post('/workspace/core/fees/heads',data={'_csrf':token,'version':'0','action':'save','key':'Custom Fee','label':name+' Fee','timing':'monthly'})
            self.assertEqual(response.status_code,302)
            client.post('/records/options',data={'_csrf':token,'category':'class_name','value':'Test Class'})
            response=client.post('/workspace/core/fees/schedules',data={'_csrf':token,'version':'0','action':'save','name':name+' Plan','campuses':['Campus '+name],'classes':['Test Class'],'due_day':'10','head_key':['Custom Fee'],'head_version_0':'1','amount_0':'1000'})
            self.assertEqual(response.status_code,302)
        for client,expected,excluded in [(self.client,b'Only School A',b'Only School B'),(other,b'Only School B',b'Only School A')]:
            for path in ['/workspace/core/fees/heads','/workspace/core/fees/schedules','/workspace/core/fees/preview/1?month=2026-09']:
                response=client.get(path);self.assertEqual(response.status_code,200);self.assertIn(expected,response.data);self.assertNotIn(excluded,response.data)
        public=app.test_client()
        for path in ['/workspace/core/fees/heads','/workspace/core/fees/schedules','/workspace/core/fees/preview/1']:self.assertEqual(public.get(path).status_code,302)

    def test_challan_branding_preview_and_print_are_tenant_private(self):
        from challan_branding import DEFAULTS,FLAGS
        other=app.test_client();self.login();self.login('TEST-B',client=other)
        for client,name in [(self.client,'Only School A'),(other,'Only School B')]:
            with client.session_transaction() as session:token=session['record_csrf']
            data={**DEFAULTS,'_csrf':token,'version':'0','action':'save','note':name+' payment instructions'}
            for flag in FLAGS:
                data.pop(flag,None)
                if DEFAULTS[flag]:data[flag]='1'
            self.assertEqual(client.post('/workspace/core/fees/challan-branding',data=data).status_code,302)
            data.update(action='preview',version='1')
            preview=client.post('/workspace/core/fees/challan-branding',data=data)
            self.assertEqual(preview.status_code,200);self.assertIn((name+' payment instructions').encode(),preview.data)
            printed=client.post('/workspace/fee-action',data={'_csrf':token,'action':'branded','ids':'1'})
            self.assertEqual(printed.status_code,200);self.assertIn((name+' payment instructions').encode(),printed.data)
            self.assertNotIn(('Only School B' if name=='Only School A' else 'Only School A').encode(),printed.data)
            self.assertIn('no-store',printed.headers['Cache-Control'])
        public=app.test_client()
        self.assertEqual(public.get('/workspace/core/fees/challan-branding').status_code,302)
        self.assertEqual(public.post('/workspace/core/fees/challan-branding',data={'action':'preview'}).status_code,302)
        self.assertEqual(public.post('/workspace/fee-action',data={'action':'branded','ids':'1'}).status_code,302)

    def test_bulk_fee_increment_previews_and_confirmation_are_tenant_bound(self):
        import re,html
        P=app.extensions['student_fee_plan_model']
        for institute_id,amount in ((self.a,100000),(self.b,200000)):
            with app.test_request_context('/'):
                g.institute_engine=app.extensions['identity_helpers']['engine'](institute_id)
                db.session.add(P(student_id=1,effective='2026-01',data=dict(schedule='Plan',percentage='0',year='2026',lines=[dict(particular='Tuition',actual=amount,net=amount,discount=0,arrears=0)])))
                db.session.commit();db.session.remove()
        other=app.test_client();self.login();self.login('TEST-B',client=other)
        path='/workspace/core/fees/increments'
        with self.client.session_transaction() as sess:csrf_a=sess['record_csrf']
        with other.session_transaction() as sess:csrf_b=sess['record_csrf']
        preview=self.client.post(path,data=dict(_csrf=csrf_a,action='preview',student_ids='1',effective='2027-01',year='2027',percentage='10'))
        self.assertEqual(preview.status_code,200);self.assertIn(b'Only School A',preview.data);self.assertNotIn(b'Only School B',preview.data)
        token=html.unescape(re.search(rb'name="preview_token" value="([^"]+)"',preview.data)[1].decode())
        self.assertEqual(other.post(path,data=dict(_csrf=csrf_b,action='apply',preview_token=token)).status_code,422)
        self.assertEqual(self.client.post(path,data=dict(_csrf=csrf_a,action='apply',preview_token=token)).status_code,302)
        self.assertIn(b'1,100.00',self.client.get(path).data);self.assertIn(b'2,000.00',other.get(path).data);self.assertNotIn(b'1,100.00',other.get(path).data)
        public=app.test_client();self.assertEqual(public.get(path).status_code,302)
        self.assertEqual(public.post(path,data=dict(action='apply',preview_token=token)).status_code,302)

    def test_late_fee_policies_previews_and_apply_are_institute_private(self):
        import re,html
        other=app.test_client();self.login();self.login('TEST-B',client=other)
        path='/workspace/core/fees/late-policy'
        tokens={}
        for client,name in ((self.client,'Only School A'),(other,'Only School B')):
            with client.session_transaction() as sess:csrf=sess['record_csrf']
            tokens[name]=csrf
            response=client.post('/workspace/core/fees/heads',data=dict(_csrf=csrf,action='save',version='0',key='Late Fee',label=name+' Fine',timing='fine'))
            self.assertEqual(response.status_code,302)
            response=client.post(path,data=dict(_csrf=csrf,action='save',version='0',mode='fixed',rate='100',grace='0',head='Late Fee',accept_formula='1'))
            self.assertEqual(response.status_code,403)
            result=app.test_cli_runner().invoke(args=['institute-late-policy','--code','TEST-A' if name=='Only School A' else 'TEST-B','--expected-version','0','--mode','fixed','--rate','100','--head','Late Fee','--accept-formula'])
            self.assertEqual(result.exit_code,0,result.output)
        preview=self.client.post(path+'/assess',data=dict(_csrf=tokens['Only School A'],action='preview',ids='1',asof='2026-10-13'))
        self.assertEqual(preview.status_code,200);self.assertIn(b'Only School A Fine',preview.data);self.assertNotIn(b'Only School B Fine',preview.data)
        token=html.unescape(re.search(rb'name="preview_token" value="([^"]+)"',preview.data)[1].decode())
        self.assertEqual(other.post(path+'/assess',data=dict(_csrf=tokens['Only School B'],action='apply',preview_token=token)).status_code,422)
        self.assertEqual(self.client.post(path+'/assess',data=dict(_csrf=tokens['Only School A'],action='apply',preview_token=token)).status_code,302)
        for client,own,excluded in ((self.client,b'Only School A Fine',b'Only School B Fine'),(other,b'Only School B Fine',b'Only School A Fine')):
            page=client.get(path);self.assertEqual(page.status_code,200);self.assertIn(own,page.data);self.assertNotIn(excluded,page.data);self.assertIn('no-store',page.headers['Cache-Control'])
        public=app.test_client();self.assertEqual(public.get(path).status_code,302)
        self.assertEqual(public.post(path+'/assess',data=dict(action='apply',preview_token=token)).status_code,302)

    def test_provider_client_name_seeds_private_profile_and_policy_edits_are_locked(self):
        self.login();page=self.client.get('/workspace/core/institute')
        self.assertIn(b'value="Fictional School A"',page.data)
        self.login('TEST-B');page=self.client.get('/workspace/core/institute');self.assertIn(b'value="Fictional School B"',page.data);self.assertNotIn(b'value="Fictional School A"',page.data)
        path='/workspace/core/fees/late-policy';page=self.client.get(path)
        self.assertIn(b'Provider-managed policy',page.data);self.assertNotIn(b'value="save"',page.data)
        with self.client.session_transaction() as sess:csrf=sess['record_csrf']
        self.assertEqual(self.client.post(path,data=dict(_csrf=csrf,action='reset',version='0')).status_code,403)
        runner=app.test_cli_runner()
        self.assertEqual(runner.invoke(args=['institute-late-policy','--code','TEST-B','--show']).exit_code,0)
        self.assertNotEqual(runner.invoke(args=['institute-late-policy','--code','MISSING','--show']).exit_code,0)
        self.assertNotEqual(runner.invoke(args=['institute-late-policy','--code','TEST-B','--mode','fixed','--rate','100']).exit_code,0)

    def test_owner_contact_changes_do_not_change_login_or_other_school(self):
        self.login();token=self.csrf()
        response=self.client.post('/workspace/core/institute',data=dict(_csrf=token,action='profile',version='1',name='Fictional School A',owner_contact='TEST-CONTACT',owner_email='contact@example.invalid'))
        self.assertEqual(response.status_code,302);page=self.client.get('/workspace/core/institute')
        self.assertIn(b'contact@example.invalid',page.data);self.assertIn(b'owner@example.invalid',page.data)
        self.assertEqual(self.login().status_code,302)
        self.login('TEST-B');page=self.client.get('/workspace/core/institute');self.assertNotIn(b'contact@example.invalid',page.data)
        token=self.csrf();self.assertEqual(self.client.post('/workspace/core/institute',data=dict(_csrf=token,action='profile',version='1',name='Fictional School B',owner_email='invalid')).status_code,422)

    def test_student_import_staging_is_private_between_real_institutes(self):
        import io,re,html
        rm=app.extensions['record_models'];Schedule=app.extensions['fee_setup_models']['schedule']
        with app.test_request_context('/'):
            g.institute_engine=app.extensions['identity_helpers']['engine'](self.a);db.session.remove()
            for category,value in [('class_name','Import Class'),('section','A'),('group_name','General'),('academic_session','2026-27'),('fee_plan','Import Plan')]:db.session.add(rm['settings'](category=category,value=value,class_name=''))
            db.session.add(Schedule(name='Import Plan',campus='Campus Only School A',class_name='Import Class',description='',due_day=10,lines=[dict(key='Tuition Fee',amount=350000,minimum=None,maximum=None)]));db.session.commit();db.session.remove();g.pop('institute_engine',None)
        other=app.test_client();self.login();self.login('TEST-B',client=other)
        path='/workspace/core/institute/student-import'
        with self.client.session_transaction() as sess:csrf=sess['record_csrf']
        source='name,gender,father,father_cnic,phone\nPrivate A Pupil,F,Private A Father,TEST,000\n'
        response=self.client.post(path+'/upload',data={'_csrf':csrf,'file':(io.BytesIO(source.encode()),'students.csv')})
        self.assertEqual(response.status_code,302);url=response.location
        self.assertIn(b'Private A Pupil',self.client.get(url).data)
        self.assertEqual(other.get(url).status_code,404);self.assertNotIn(url.split('/')[-1].encode(),other.get(path).data)
        data=dict(_csrf=csrf,action='review',version='1');data.update({'map_'+str(i):key for i,key in enumerate(['name','gender','father','father_cnic','phone'])})
        self.assertEqual(self.client.post(url,data=data).status_code,302)
        page=self.client.get(url);match=re.search(rb'name="confirmation" value="([^"]+)"',page.data);self.assertIsNotNone(match,page.data[-1800:])
        confirmation=html.unescape(match[1].decode())
        self.assertEqual(self.client.post(url+'/apply',data=dict(_csrf=csrf,confirmation=confirmation)).status_code,302)
        self.assertIn(b'Private A Pupil',self.client.get('/records/student').data);self.assertNotIn(b'Private A Pupil',other.get('/records/student').data)
        public=app.test_client();self.assertEqual(public.get(path).status_code,302)
        self.assertEqual(public.get(path+'/template.xlsx').status_code,302)
        self.assertEqual(public.post(path+'/upload',data={}).status_code,302)

    def test_workspace_writes_stay_in_selected_database(self):
        self.login()
        with self.client.session_transaction() as sess: token = sess['record_csrf']
        response = self.client.post('/records/settings', data={'_csrf':token, 'category':'campus', 'value':'New A Campus', 'class_name':''})
        self.assertEqual(response.status_code, 302)
        self.assertIn(b'New A Campus', self.client.get('/records/settings').data)
        self.login('TEST-B')
        self.assertNotIn(b'New A Campus', self.client.get('/records/settings').data)

    def test_financial_reports_and_issued_certificate_ids_are_isolated(self):
        other = app.test_client()
        self.login(); self.login('TEST-B', client=other)
        for client, expected, excluded in [(self.client,b'Only School A',b'Only School B'),(other,b'Only School B',b'Only School A')]:
            for path in ['/workspace/fees/class-fees?from=2026-10&to=2026-10&export=csv', '/workspace/certificates/issued/1', '/workspace/certificates/batch/1']:
                response = client.get(path)
                self.assertEqual(response.status_code, 200, path)
                self.assertIn(expected,response.data,path);self.assertNotIn(excluded,response.data,path)

    def test_demo_cannot_select_a_real_school_by_query_or_form(self):
        self.client.post('/auth/demo', data={'_csrf':self.csrf(), 'institute_id':self.a})
        page = self.client.get('/records/student?institute_id='+str(self.a)).data
        self.assertIn(b'Only Public Demo', page); self.assertNotIn(b'Only School A', page)
        self.assertEqual(self.client.get('/records/student/2').status_code, 404)
        self.login()
        self.assertNotIn(b'Only Public Demo', self.client.get('/records/student').data)
        app.config['PUBLIC_DEMO_ENABLED'] = False
        self.assertEqual(self.client.post('/auth/demo', data={'_csrf':self.csrf()}).status_code, 404)

    def test_missing_institute_invalid_password_and_expired_pending(self):
        self.assertTrue(self.client.get('/auth/login').location.endswith('/auth/institute'))
        self.assertEqual(self.login(password='incorrect').status_code, 200)
        self.assertEqual(self.client.get('/records/student').status_code, 302)
        self.client.post('/auth/institute', data={'_csrf':self.csrf(), 'code':'TEST-A'})
        with self.client.session_transaction() as sess: sess['pending_at'] = time.time()-901
        self.assertTrue(self.client.get('/auth/login').location.endswith('/auth/institute'))

    def test_csrf_guards_all_auth_mutations(self):
        self.assertEqual(self.client.post('/auth/institute', data={'code':'TEST-A'}).status_code, 400)
        self.assertEqual(self.client.post('/auth/demo').status_code, 400)
        self.assertEqual(self.client.post('/auth/logout').status_code, 400)
        self.client.post('/auth/institute', data={'_csrf':self.csrf(), 'code':'TEST-A'})
        self.assertEqual(self.client.post('/auth/login', data={'email':'owner@example.invalid','password':PASSWORD}).status_code, 400)

    def test_login_throttling_persists_across_clients(self):
        for _ in range(10):
            self.assertEqual(self.login(password='incorrect').status_code, 200)
        self.assertEqual(self.login(password='incorrect').status_code, 429)
        self.assertNotIn('owner_id', self.client.get('/').data.decode())

    def test_inactive_school_owner_expiry_and_password_revision_revoke_sessions(self):
        self.login()
        owner = self.models['owner'].query.filter_by(institute_id=self.a).one()
        owner.version += 1; db.session.commit(); db.session.remove()
        self.assertEqual(self.client.get('/records/student').status_code, 302)
        self.login()
        with self.client.session_transaction() as sess: sess['signed_in_at'] = time.time()-28801
        self.assertEqual(self.client.get('/records/student').status_code, 302)
        self.login()
        owner = self.models['owner'].query.filter_by(institute_id=self.a).one()
        owner.active = False; db.session.commit(); db.session.remove()
        self.assertEqual(self.client.get('/records/student').status_code, 302)
        owner = self.models['owner'].query.filter_by(institute_id=self.a).one()
        owner.active = True; db.session.commit(); db.session.remove()
        self.login()
        school = db.session.get(self.models['institute'], self.a); school.active = False; db.session.commit(); db.session.remove()
        self.assertEqual(self.client.get('/records/student').status_code, 302)

    def test_operator_provisioning_is_not_public_and_password_is_hashed(self):
        self.assertEqual(self.client.post('/auth/register').status_code, 404)
        owner = self.models['owner'].query.first()
        self.assertNotEqual(owner.password_hash, PASSWORD)
        for code in ['DEMO', '../outside', 'AB']:
            with self.assertRaises(ValueError):
                app.extensions['identity_helpers']['provision'](code, 'Name', 'test@example.invalid', PASSWORD)
        with self.assertRaises(ValueError):
            app.extensions['identity_helpers']['provision']('TEST-A', 'Name', 'test@example.invalid', PASSWORD)

    def test_password_help_does_not_claim_email_was_sent(self):
        page = self.client.get('/auth/forgot-password')
        self.assertEqual(page.status_code, 200)
        self.assertIn(b'Email reset delivery is not connected', page.data)


    def test_attendance_fines_provider_scope_and_pending_liability_isolation(self):
        Head=app.extensions['fee_setup_models']['head'];Item=app.extensions['school_settings_models']['item'];Charge=app.extensions['fine_charge_model']
        with app.test_request_context('/'):
            g.institute_engine=app.extensions['identity_helpers']['engine'](self.a);db.session.remove()
            db.session.add(Head(key='Attendance Fine',label='Private A attendance fine',timing='fine',months=[],custom=True));db.session.commit();db.session.remove()
        runner=app.test_cli_runner();args=['institute-attendance-fine-policy','--code','TEST-A','--head','Attendance Fine','--rule','Absent:1:25']
        self.assertNotEqual(runner.invoke(args=args).exit_code,0)
        self.assertEqual(runner.invoke(args=args+['--expected-version','0']).exit_code,0)
        self.assertNotEqual(runner.invoke(args=args+['--expected-version','0']).exit_code,0)
        self.login();page=self.client.get('/workspace/core/fees/attendance-fines');self.assertIn(b'Private A attendance fine',page.data)
        with self.client.session_transaction() as sess:csrf=sess['record_csrf']
        self.assertEqual(self.client.post('/workspace/core/fees/attendance-fines',data=dict(_csrf=csrf,action='save',version='1')).status_code,403)
        with app.test_request_context('/'):
            g.institute_engine=app.extensions['identity_helpers']['engine'](self.a);db.session.remove()
            db.session.add(Charge(student_id=1,source='attendance:1:2026-09',kind='attendance',target_month='2026-10',amount=1000,data={'line':{'particular':'Attendance Fine','display_name':'Private A fine liability'}}));db.session.commit();db.session.remove()
        self.assertIn(b'Private A fine liability',self.client.get('/workspace/core/fees/pending-fines').data)
        self.login('TEST-B');self.assertNotIn(b'Private A attendance fine',self.client.get('/workspace/core/fees/attendance-fines').data)
        self.assertNotIn(b'Private A fine liability',self.client.get('/workspace/core/fees/pending-fines').data)
        with self.client.session_transaction() as sess:csrf=sess['record_csrf']
        response=self.client.post('/workspace/core/fees/pending-fines',data={'_csrf':csrf,'action':'preview','ids':'1','bill_1':'1'})
        self.assertEqual(response.status_code,404)


    def test_background_fine_tick_processes_only_enabled_tenant_schedules(self):
        from datetime import datetime,timedelta
        from zoneinfo import ZoneInfo
        from unittest.mock import patch
        now=datetime(2026,11,1,12,0,tzinfo=ZoneInfo('Asia/Karachi'));Item=app.extensions['school_settings_models']['item'];Head=app.extensions['fee_setup_models']['head'];Bill=app.extensions['ops_models']['bill']
        for iid in (self.a,self.b):
            with app.test_request_context('/'):
                g.institute_engine=app.extensions['identity_helpers']['engine'](iid);db.session.remove()
                bill=db.session.get(Bill,1);bill.due=now.date()-timedelta(days=1)
                if iid==self.a:
                    detail=app.extensions['record_models']['student'](student_id=1,data={'campus':'Campus Only School A'});db.session.add(detail)
                    db.session.add(Head(key='Late Fine',label='Late Fine',timing='fine',months=[],custom=True))
                    db.session.add(Item(kind='late-fee-policy',scope='Campus Only School A',name='',data=dict(mode='daily',rate=1000,grace=0,maximum=None,head='Late Fine',head_label='Late Fine')))
                    db.session.add(Item(kind='late-fee-automation',scope='Campus Only School A',name='',data=dict(enabled=True,activation_day='2026-11-01',delay=1,time='00:05',defer=True,off_days=[],holidays=[])))
                db.session.commit();db.session.remove()
        with patch('fine_automation.local_now',return_value=now):
            app.extensions['fine_automation_helpers']['tick_all']();app.extensions['fine_automation_helpers']['tick_all']()
        for iid,amount in [(self.a,13345),(self.b,12345)]:
            with app.test_request_context('/'):
                g.institute_engine=app.extensions['identity_helpers']['engine'](iid);db.session.remove();self.assertEqual(db.session.get(Bill,1).total,amount);db.session.remove()
        g.pop('institute_engine',None)


    def test_payment_qr_uses_only_signed_in_institute_link_and_reference(self):
        from unittest.mock import patch
        import qrcode
        Item=app.extensions['school_settings_models']['item']
        for iid,host in [(self.a,'school-a.example.invalid'),(self.b,'school-b.example.invalid')]:
            with app.test_request_context('/'):
                g.institute_engine=app.extensions['identity_helpers']['engine'](iid);db.session.remove()
                db.session.add(Item(kind='challan-branding',scope='',name='Fee Challan',data=dict(show_payment_qr=True,payment_url='https://'+host+'/pay?ref={consumer}')));db.session.commit();db.session.remove()
        g.pop('institute_engine',None);path='/workspace/core/fees/challan-payment-qr/1'
        self.assertEqual(self.client.get(path).status_code,302)
        real=qrcode.make
        for code,host in [('TEST-A','school-a.example.invalid'),('TEST-B','school-b.example.invalid')]:
            self.login(code)
            with patch('challan_consumers.qrcode.make',wraps=real) as make:response=self.client.get(path)
            self.assertEqual(response.status_code,200);self.assertIn(host,make.call_args[0][0]);self.assertNotIn('school-b' if code=='TEST-A' else 'school-a',make.call_args[0][0])


    def test_report_excel_export_keeps_institute_data_separate(self):
        import io
        from openpyxl import load_workbook
        for code,own,other in [('TEST-A','Only School A','Only School B'),('TEST-B','Only School B','Only School A')]:
            self.login(code);response=self.client.get('/workspace/reports/fees/student-fees?from=2026-10&to=2026-10&export=xlsx')
            self.assertEqual(response.status_code,200)
            values=list(load_workbook(io.BytesIO(response.data))['Report'].values);text=str(values)
            self.assertIn(own,text);self.assertNotIn(other,text)


    def test_roll_holiday_and_year_settings_are_private_to_each_institute(self):
        import re
        self.assertEqual(self.login().status_code,302);token=self.csrf()
        path='/workspace/core/roll-number-series';page=self.client.get(path)
        key=re.search(rb'name="series_key" value="([^"]+)"',page.data)[1].decode()
        form={'_csrf':token,'action':'series','series_key':key,'prefix_'+key:'PRIVATE-A-','start_'+key:'1','digits_'+key:'3','version_'+key:'0'}
        self.assertEqual(self.client.post(path,data=form).status_code,302)
        self.assertEqual(self.client.post('/workspace/core/holidays',data=dict(_csrf=token,action='save',version='0',name='Private School A closure',date='2027-02-01',campus='')).status_code,302)
        self.assertEqual(self.client.post('/workspace/core/fees/yearly-increment',data=dict(_csrf=token,action='add-year',version='0',year='2028')).status_code,302)
        self.assertEqual(self.login('TEST-B').status_code,302)
        self.assertNotIn(b'PRIVATE-A-',self.client.get(path).data)
        self.assertNotIn(b'Private School A closure',self.client.get('/workspace/core/holidays').data)
        self.assertNotIn(b'2028',self.client.get('/workspace/core/fees/yearly-increment').data)
        self.assertEqual(self.login('TEST-A').status_code,302)
        self.assertIn(b'PRIVATE-A-',self.client.get(path).data);self.assertIn(b'Private School A closure',self.client.get('/workspace/core/holidays').data)

    def test_discount_type_catalog_is_private_to_each_school(self):
        self.login('TEST-A');token=self.csrf()
        response=self.client.post('/workspace/core/fees/discount-types',data={'_csrf':token,'name':'Private School A concession','active':'1','version':'0'})
        self.assertEqual(response.status_code,302)
        self.assertIn(b'Private School A concession',self.client.get('/workspace/core/fees/discount-types').data)
        self.login('TEST-B')
        self.assertNotIn(b'Private School A concession',self.client.get('/workspace/core/fees/discount-types').data)
        self.assertEqual(self.client.get('/workspace/core/fees/discount-types?edit=1').status_code,404)


if __name__ == '__main__':
    unittest.main()
