"""Template CRUD, scopes, custom issuing, exports and preserved document history."""
import io,os,unittest
from openpyxl import load_workbook
os.environ['DATABASE_URL']='sqlite:///:memory:'
from app import app,db,Student

class CertificateManagerTests(unittest.TestCase):
    path='/workspace/core/certificates'
    def setUp(self):
        app.config.update(TESTING=True,IDENTITY_ENFORCE_IN_TESTS=False)
        self.ctx=app.app_context();self.ctx.push();db.drop_all();db.create_all();self.m=app.extensions['certificate_models'];self.rm=app.extensions['record_models'];self.A=app.extensions['ops_models']['audit']
        for campus in ('Campus A','Campus B'):db.session.add(self.rm['settings'](category='campus',value=campus,class_name=''))
        db.session.commit();self.c=app.test_client();self.c.get(self.path)
        with self.c.session_transaction() as s:self.csrf=s['record_csrf']
    def tearDown(self):db.session.remove();db.drop_all();self.ctx.pop()
    def create(self,**changes):
        data=dict(_csrf=self.csrf,version='0',name='Fictional template',campus='Campus A',header='<h2>[institute_name]</h2>',body='<p>[studentName]</p>',footer='<p>[refNo]</p>');data.update(changes);return self.c.post(self.path+'/new',data=data)
    def test_pages_and_preview_are_read_only_and_html_is_sanitized(self):
        self.assertEqual(self.c.get(self.path+'/new').status_code,200)
        response=self.create(action='preview',body='<p onclick="bad()">[studentName]</p><script>bad()</script>');self.assertEqual(response.status_code,200);self.assertIn(b'sandbox=""',response.data);self.assertNotIn(b'onclick="bad()"',response.data)
        self.assertEqual(self.m['template'].query.count(),0);self.assertEqual(self.m['campus'].query.count(),0);self.assertEqual(self.A.query.count(),0)
    def test_custom_template_can_be_selected_previewed_and_issued_for_students(self):
        Profile=app.extensions['institute_setup_models']['profile'];db.session.add(Profile(id=1,data={'name':'Fictional School'}));db.session.commit()
        self.assertEqual(self.create().status_code,302);t=self.m['template'].query.one()
        pupil=Student(admission_no='CM-1',name='Fictional Pupil',class_name='One',status='Active');db.session.add(pupil);db.session.flush();db.session.add(self.rm['student'](student_id=pupil.id,data={'campus':'Campus A'}));db.session.commit()
        page=self.c.get('/workspace/certificates?campus=Campus+A');self.assertIn(b'Fictional template',page.data)
        data=dict(_csrf=self.csrf,action='preview',template_id=str(t.id),student_ids=str(pupil.id),copy_type='Original',token='fictional-template-token-12345',campus='Campus A')
        self.assertEqual(self.c.post('/workspace/certificates/documents',data=data).status_code,200);self.assertEqual(self.m['issue'].query.count(),0)
        data['action']='issue';self.assertEqual(self.c.post('/workspace/certificates/documents',data=data).status_code,302);issue=self.m['issue'].query.one();self.assertTrue(issue.reference.startswith('DOC-'));saved=issue.html
        self.assertEqual(self.c.post(self.path+'/'+str(t.id)+'/delete',data=dict(_csrf=self.csrf,version=str(t.version),confirm='yes')).status_code,422);self.assertEqual(issue.html,saved)
    def test_edit_stale_delete_confirmation_and_duplicate_names(self):
        self.create();t=self.m['template'].query.one();self.assertEqual(self.create().status_code,422)
        url=self.path+'/'+str(t.id)+'/edit';data=dict(_csrf=self.csrf,version='1',name='Updated custom',campus='Campus A',body='<p>Changed</p>')
        self.assertEqual(self.c.post(url,data=data).status_code,302);self.assertEqual(self.c.post(url,data=data).status_code,422)
        self.assertEqual(self.c.post(self.path+'/'+str(t.id)+'/delete',data=dict(_csrf=self.csrf,version=str(t.version))).status_code,422)
        self.assertEqual(self.c.post(self.path+'/'+str(t.id)+'/delete',data=dict(_csrf=self.csrf,version=str(t.version),confirm='yes')).status_code,302)
    def test_default_copy_and_matching_formula_safe_exports(self):
        self.create(name='=Default template',campus='');t=self.m['template'].query.one()
        self.assertNotIn(b'<option></option>',self.c.get('/workspace/certificates').data)
        response=self.c.get(self.path+'?campus=__default__&export=xlsx&columns=name');self.assertEqual(response.status_code,200);sheet=load_workbook(io.BytesIO(response.data))['Report'];self.assertEqual(sheet['A2'].data_type,'s');self.assertEqual(sheet['A2'].value,'=Default template')
        self.assertEqual(self.c.post(self.path+'/'+str(t.id)+'/copy',data=dict(_csrf=self.csrf,version=str(t.version),campus='Campus B')).status_code,302)
        self.assertEqual(self.m['template'].query.count(),2);self.assertEqual(self.m['issue'].query.count(),0)
    def test_invalid_scope_export_and_csrf_are_rejected(self):
        self.assertEqual(self.create(campus='Unknown').status_code,422)
        for query in ['sort=bad','campus=Unknown','columns=secret','size=3','export=pdf']:self.assertEqual(self.c.get(self.path+'?'+query).status_code,422)
        self.assertEqual(self.c.post(self.path+'/new',data={'name':'No CSRF'}).status_code,400)
