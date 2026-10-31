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
        response=self.client.post('/workspace/core/institute',data={'_csrf':token,'action':'profile','version':'0','name':'Private School A Setup'})
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


if __name__ == '__main__':
    unittest.main()
