"""Vendor bootstrap, privilege separation and real private-school provisioning."""
import os,tempfile,time,unittest
os.environ['DATABASE_URL']='sqlite:///:memory:'
from werkzeug.security import generate_password_hash
from app import app,db

PASSWORD='Central-owner-password-2026'
SCHOOL_PASSWORD='Private-school-password-2026'

class VendorTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory()
        app.config.update(TESTING=True,IDENTITY_ENFORCE_IN_TESTS=True,INSTITUTE_DATABASE_DIR=self.directory.name,SECRET_KEY='vendor-test-only',VENDOR_SETUP_HASH=generate_password_hash('fictional-setup-code'),PUBLIC_DEMO_ENABLED=True)
        self.ctx=app.app_context();self.ctx.push();db.drop_all();db.create_all();self.client=app.test_client()
    def tearDown(self):
        db.session.remove();db.drop_all();self.ctx.pop();self.directory.cleanup();app.config.update(IDENTITY_ENFORCE_IN_TESTS=False,VENDOR_SETUP_HASH='')
    def csrf(self,client=None):
        client=client or self.client;client.get('/vendor/login')
        with client.session_transaction() as s:return s['record_csrf']
    def post(self,path,data,client=None):
        client=client or self.client;data=dict(data,_csrf=self.csrf(client));return client.post(path,data=data)
    def setup_owner(self):
        return self.post('/vendor/setup',dict(setup_code='fictional-setup-code',email='vendor@example.invalid',password=PASSWORD,confirm=PASSWORD))
    def create(self,code='PRIVATE-A'):
        return self.post('/vendor/schools',dict(code=code,name='Private School '+code,email='school@example.invalid',password=SCHOOL_PASSWORD,confirm=SCHOOL_PASSWORD))
    def test_setup_requires_private_code_csrf_and_single_owner(self):
        self.assertEqual(self.client.post('/vendor/setup',data={}).status_code,400)
        self.assertEqual(self.post('/vendor/setup',dict(setup_code='wrong')).status_code,422)
        self.assertIsNone(db.session.get(app.extensions['vendor_models']['owner'],1))
        self.assertEqual(self.setup_owner().status_code,302)
        with self.client.session_transaction() as s:self.assertNotIn('owner_id',s);self.assertEqual(s['vendor_id'],1)
        other=app.test_client();r=self.post('/vendor/setup',dict(setup_code='fictional-setup-code',email='attacker@example.invalid',password=PASSWORD,confirm=PASSWORD),other)
        self.assertEqual(r.status_code,302);self.assertEqual(db.session.get(app.extensions['vendor_models']['owner'],1).email,'vendor@example.invalid')
    def test_disabled_bootstrap_and_foreign_sessions_cannot_create_schools(self):
        app.config['VENDOR_SETUP_HASH']=''
        self.assertEqual(self.post('/vendor/setup',dict(setup_code='fictional-setup-code')).status_code,404)
        for role in ('demo','owner_id','staff_id'):
            client=app.test_client()
            with client.session_transaction() as s:s[role]=True;s['institute_id']=1
            self.assertEqual(client.get('/vendor/schools').status_code,302)
            self.assertEqual(self.post('/vendor/schools',{},client).status_code,302)
    def test_create_private_school_then_sign_in_to_matching_branding(self):
        self.setup_owner();self.assertEqual(self.create().status_code,302)
        page=self.client.get('/vendor/schools').data;self.assertIn(b'PRIVATE-A',page);self.assertNotIn(SCHOOL_PASSWORD.encode(),page)
        school=app.extensions['identity_models']['institute'].query.one();self.assertEqual(school.code,'PRIVATE-A')
        client=app.test_client();client.get('/auth/institute')
        with client.session_transaction() as s:token=s['record_csrf']
        self.assertEqual(client.post('/auth/institute',data=dict(_csrf=token,code='PRIVATE-A')).status_code,302)
        with client.session_transaction() as s:token=s['record_csrf']
        self.assertEqual(client.post('/auth/login',data=dict(_csrf=token,email='school@example.invalid',password=SCHOOL_PASSWORD)).status_code,302)
        self.assertIn(b'Prepare this school',client.get('/workspace/general/app-links').data)
        self.assertEqual(client.get('/vendor/schools').status_code,302)
        self.assertEqual(self.client.get('/workspace/dashboard').status_code,302)
    def test_invalid_duplicate_and_cross_school_reset(self):
        self.setup_owner();self.assertEqual(self.create('DEMO').status_code,422)
        self.assertEqual(self.create().status_code,302);self.assertEqual(self.create().status_code,422)
        School=app.extensions['identity_models']['institute'];Owner=app.extensions['identity_models']['owner']
        school=School.query.one();owner=Owner.query.one();old=owner.password_hash
        self.assertEqual(self.post(f'/vendor/schools/{school.id}/reset-password',dict(code='OTHER',password=PASSWORD,confirm=PASSWORD)).status_code,400)
        db.session.rollback();self.assertEqual(Owner.query.one().password_hash,old)
        self.assertEqual(self.post(f'/vendor/schools/{school.id}/reset-password',dict(code=school.code,password=PASSWORD,confirm=PASSWORD)).status_code,302)
        self.assertEqual(Owner.query.one().version,2)
    def test_session_expiry_logout_and_password_rotation(self):
        self.setup_owner();other=app.test_client()
        self.assertEqual(self.post('/vendor/login',dict(email='vendor@example.invalid',password=PASSWORD),other).status_code,302)
        new='Changed-owner-password-2026'
        self.assertEqual(self.post('/vendor/password',dict(current_password=PASSWORD,password=new,confirm=new)).status_code,302)
        self.assertEqual(other.get('/vendor/schools').status_code,302)
        self.assertEqual(self.client.get('/vendor/schools').status_code,200)
        with self.client.session_transaction() as s:s['vendor_signed_at']=time.time()-4000
        self.assertEqual(self.client.get('/vendor/schools').status_code,302)
        self.assertEqual(self.post('/vendor/login',dict(email='vendor@example.invalid',password=new)).status_code,302)
        self.assertEqual(self.client.get('/vendor/logout').status_code,405)
        self.assertEqual(self.post('/vendor/logout',{}).status_code,302)
        self.assertEqual(self.client.get('/vendor/schools').status_code,302)
    def test_throttling_and_no_cache(self):
        self.assertEqual(self.client.get('/vendor/setup').headers['Cache-Control'],'no-store')
        for _ in range(10):self.assertEqual(self.post('/vendor/setup',dict(setup_code='bad')).status_code,422)
        self.assertEqual(self.setup_owner().status_code,429)
    def test_unicode_password_and_html_escape(self):
        password='خفیہ-password-2026'
        self.assertEqual(self.post('/vendor/setup',dict(setup_code='fictional-setup-code',email='vendor@example.invalid',password=password,confirm=password)).status_code,302)
        self.assertEqual(self.post('/vendor/schools',dict(code='ESCAPE',name='<script>alert(1)</script>',email='school@example.invalid',password=SCHOOL_PASSWORD,confirm=SCHOOL_PASSWORD)).status_code,302)
        page=self.client.get('/vendor/schools').data;self.assertNotIn(b'<script>alert(1)</script>',page)
        self.assertEqual(app.extensions['vendor_models']['audit'].query.count(),2)

if __name__=='__main__':unittest.main()
