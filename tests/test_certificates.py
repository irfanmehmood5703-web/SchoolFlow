"""Certificate issuance, immutability, template sanitisation and QR integration."""
import io,os,re,unittest
from datetime import date
from PIL import Image
from flask import template_rendered
from werkzeug.datastructures import MultiDict
os.environ['DATABASE_URL']='sqlite:///:memory:'
from app import app,db,Student
from certificates import clean_html
from certificate_defaults import CATALOG

class CertificateTests(unittest.TestCase):
    def setUp(self):
        app.config.update(TESTING=True,SECRET_KEY='certificate-test')
        self.ctx=app.app_context();self.ctx.push();db.drop_all();db.create_all()
        self.m=app.extensions['certificate_models'];self.rm=app.extensions['record_models'];self.ops=app.extensions['ops_models']
        self.s=Student(admission_no='TEST-CERT-1',name='Fictional Certificate Pupil',father='Fictional Guardian',class_name='One',status='Active')
        self.s2=Student(admission_no='TEST-CERT-2',name='Second Fictional Pupil',class_name='Two',status='Active')
        db.session.add_all([self.s,self.s2]);db.session.flush()
        for name in ['Demo Campus','Other Campus']:db.session.add(self.rm['settings'](category='campus',value=name,class_name=''))
        for s in [self.s,self.s2]:db.session.add(self.rm['student'](student_id=s.id,data=dict(campus='Demo Campus',section='A',roll_no='00'+str(s.id),academic_session='2026-27',admission_date='2026-01-01',birth_date='2020-01-01')))
        db.session.commit();self.c=app.test_client();self.c.get('/workspace/certificates')
        with self.c.session_transaction() as sess:self.csrf=sess['record_csrf']
        self.assertEqual(self.post('/setup',campus='Demo Campus').status_code,302)
        self.campus=self.m['campus'].query.one();self.campus.data=dict(name='Fictional School',address='Test Address');db.session.commit()
    def tearDown(self):db.session.remove();db.drop_all();self.ctx.pop()
    def post(self,path,**data):return self.c.post('/workspace/certificates'+path,data=dict(_csrf=self.csrf,**data))
    def template(self,key='school-leaving'):return self.m['template'].query.filter_by(key=key,campus_id=self.campus.id).one()
    def action(self,action='preview',key='school-leaving',**changes):
        data=dict(action=action,template_id=self.template(key).id,student_ids=str(self.s.id),token='certificate_token_abcdefghijklmnop',copy_type='Original');data.update(changes)
        return self.post('/documents',**data)
    def capture(self,action='preview',**changes):
        contexts=[]
        def receiver(sender,template,context,**extra):contexts.append((template.name,context))
        template_rendered.connect(receiver,app)
        try:r=self.action(action,**changes)
        finally:template_rendered.disconnect(receiver,app)
        return r,dict(contexts).get('certificate_preview.html',{})
    def test_setup_all_15_in_order_is_idempotent_and_read_only_gets(self):
        self.post('/setup',campus='Demo Campus');self.assertEqual(self.m['template'].query.count(),15)
        for tab in ['cards','logs','qr']:self.assertEqual(self.c.get('/workspace/certificates?tab='+tab).status_code,200)
        self.assertEqual(self.m['batch'].query.count(),0);self.assertEqual(self.m['issue'].query.count(),0)
        self.assertEqual(list(CATALOG),[x.key for x in self.m['template'].query.order_by(self.m['template'].id).all()])
    def test_all_templates_preview_without_issuing_or_unknown_personal_data(self):
        for key in CATALOG:
            r,ctx=self.capture(key=key);self.assertEqual(r.status_code,200,key);self.assertIn('Fictional School',ctx['html'])
            self.assertNotIn('[studentName]',ctx['html']);self.assertNotIn('Bint-e',ctx['html'])
        self.assertEqual(self.m['issue'].query.count(),0);self.assertEqual(self.m['batch'].query.count(),0)
    def test_preview_previous_next_and_fallback_first_student(self):
        r,ctx=self.capture(student_ids=[str(self.s.id),str(self.s2.id)],index='1');self.assertEqual(r.status_code,200)
        self.assertIn('Second Fictional Pupil',ctx['html']);self.assertEqual(ctx['index'],1)
        self.assertEqual(self.action(index='-1').status_code,422)
        self.assertEqual(self.action(student_ids=[]).status_code,200)
        self.assertEqual(self.action('issue',student_ids=[]).status_code,422)
    def test_issue_batch_idempotency_print_and_logs(self):
        self.assertEqual(self.action('issue',student_ids=[str(self.s.id),str(self.s2.id)]).status_code,302)
        issues=self.m['issue'].query.order_by(self.m['issue'].id).all();self.assertEqual([x.reference for x in issues],['SLC-1','SLC-2'])
        self.assertEqual(self.action('issue',student_ids=[str(self.s.id),str(self.s2.id)]).status_code,302)
        self.assertEqual(self.m['issue'].query.count(),2)
        self.assertEqual(self.action('issue',student_ids=str(self.s.id)).status_code,422)
        self.assertEqual(self.c.get('/workspace/certificates/batch/1').status_code,200)
        log=self.c.get('/workspace/certificates?tab=logs&campus=Demo+Campus').data;self.assertIn(b'SLC-1',log)
        self.assertEqual(self.c.get('/workspace/certificates/issued/1').status_code,200);self.assertEqual(self.m['issue'].query.count(),2)
    def test_issued_snapshot_and_embedded_photo_logo_are_immutable(self):
        image=io.BytesIO();Image.new('RGB',(2,2),'green').save(image,format='PNG');content=image.getvalue()
        self.campus.logo=content;self.campus.logo_mime='image/png'
        photo=self.rm['file'](owner_kind='student',owner_id=self.s.id,title='Photo',filename='test.png',mime='image/png',photo=True,content=content,sha256='test');db.session.add(photo);db.session.commit()
        self.assertEqual(self.action('issue').status_code,302);issue=self.m['issue'].query.one();original=issue.html
        self.assertIn('data:image/png;base64',original)
        self.s.name='Changed Name';self.campus.data={'name':'Changed School'};photo.content=b'changed';self.template().body='<p>Changed template</p>';db.session.commit()
        self.assertEqual(self.m['issue'].query.one().html,original)
        printed=self.c.get('/workspace/certificates/issued/1').data;self.assertIn(b'Fictional Certificate Pupil',printed);self.assertNotIn(b'Changed Name',printed)
    def test_template_preview_no_save_and_update_requires_current_version(self):
        t=self.template();original=t.body
        data=dict(name='Edited title',version=str(t.version),header='<h1>[instName]</h1>',body='<p>[studentName] <b>Edited body</b></p>',footer='')
        self.assertEqual(self.post(f'/template/{t.id}/edit',action='preview',**data).status_code,200);self.assertEqual(t.body,original)
        self.assertEqual(self.post(f'/template/{t.id}/edit',action='save',**data).status_code,302);self.assertIn('Edited body',t.body)
        self.assertEqual(self.post(f'/template/{t.id}/edit',action='save',**data).status_code,422)
    def test_unsafe_html_external_images_and_style_do_not_survive(self):
        html=clean_html('<script>alert(1)</script><img src="https://example.invalid/x" onerror="alert(2)"><p style="position:fixed;color:green;background-image:url(https://example.invalid)">Safe</p><a href="javascript:alert(3)">link</a>')
        self.assertNotIn('<script',html);self.assertNotIn('onerror',html);self.assertNotIn('src=',html);self.assertNotIn('javascript:',html);self.assertNotIn('position:',html);self.assertNotIn('background-image',html);self.assertIn('color:green',html)
        self.s.name='<img src=x onerror=alert(1)>';db.session.commit();r,ctx=self.capture();self.assertEqual(r.status_code,200)
        self.assertNotIn('<img src=x',ctx['html']);self.assertIn('&lt;img',ctx['html'])
    def test_cross_campus_students_and_templates_are_rejected(self):
        d=self.rm['student'].query.filter_by(student_id=self.s2.id).one();d.data={**d.data,'campus':'Other Campus'};db.session.commit()
        self.assertEqual(self.action('issue',student_ids=[str(self.s.id),str(self.s2.id)]).status_code,422)
        self.assertEqual(self.m['issue'].query.count(),0);self.assertEqual(self.m['batch'].query.count(),0)
        self.assertEqual(self.c.get('/workspace/certificates?campus=Unknown').status_code,422)
    def test_clearance_blocks_all_outstanding_and_batch_is_atomic(self):
        db.session.add(self.ops['bill'](student_id=self.s2.id,month='2026-01',due=date(2026,1,10),lines=[dict(particular='Tuition',amount=10000)]));db.session.commit()
        self.assertEqual(self.action('issue',key='fee-clearance',student_ids=[str(self.s.id),str(self.s2.id)]).status_code,422)
        self.assertEqual(self.m['issue'].query.count(),0);self.assertEqual(self.m['batch'].query.count(),0)
        r,ctx=self.capture(key='fee-clearance',student_ids=str(self.s2.id));self.assertEqual(r.status_code,200);self.assertIn(b'Clearance pending',r.data)
    def test_qr_read_only_stable_unique_opaque_and_print_selection(self):
        a=self.c.get(f'/workspace/certificates/qr/{self.s.id}.svg');b=self.c.get(f'/workspace/certificates/qr/{self.s2.id}.svg')
        self.assertEqual(a.status_code,200);self.assertEqual(a.mimetype,'image/svg+xml');self.assertIn(b'<svg',a.data);self.assertNotEqual(a.data,b.data)
        self.assertEqual(self.c.get(f'/workspace/certificates/qr/{self.s.id}.svg').data,a.data)
        self.s.name='Renamed';db.session.commit();self.assertEqual(self.c.get(f'/workspace/certificates/qr/{self.s.id}.svg').data,a.data)
        self.assertEqual(self.post('/qr-print',campus='Demo Campus',student_ids=str(self.s.id)).status_code,200)
        self.s.status='Inactive';db.session.commit();self.assertEqual(self.post('/qr-print',campus='Demo Campus',student_ids=str(self.s.id)).status_code,422)
        self.assertEqual(self.m['issue'].query.count(),0)
    def test_school_settings_logo_and_csrf(self):
        self.assertEqual(self.c.post('/workspace/certificates/setup',data={'campus':'Demo Campus'}).status_code,400)
        self.assertEqual(self.post(f'/campus/{self.campus.id}',version=str(self.campus.version),name='Test',color_primary='red').status_code,422)
        image=io.BytesIO();Image.new('RGB',(2,2),'blue').save(image,format='PNG');image.seek(0)
        r=self.c.post(f'/workspace/certificates/campus/{self.campus.id}',data=dict(_csrf=self.csrf,version=str(self.campus.version),name='Test School',color_primary='#123456',logo=(image,'logo.png')))
        self.assertEqual(r.status_code,302);self.assertEqual(self.c.get(f'/workspace/certificates/logo/{self.campus.id}').mimetype,'image/png')
    def test_all_15_templates_can_generate_independent_references(self):
        for i,key in enumerate(CATALOG):self.assertEqual(self.action('issue',key=key,token='unique_certificate_token_'+str(i)+'_abcdefghijkl').status_code,302,key)
        self.assertEqual(self.m['issue'].query.count(),15);self.assertEqual(len({x.reference for x in self.m['issue'].query.all()}),15)
    def test_pagination_filter_export_and_missing_heading(self):
        self.assertEqual(self.c.get('/workspace/certificates?size=999').status_code,422)
        self.assertEqual(self.c.get('/workspace/certificates?tab=qr&q=notfound').status_code,200)
        self.s.name='=CSV name';db.session.commit();export=self.c.get('/workspace/certificates?tab=qr&export=csv').data.decode();self.assertIn("'=CSV name",export)
        self.campus.data={};db.session.commit();self.assertEqual(self.action('issue').status_code,422)

    def test_campus_switch_loads_independent_template_and_qr_column_selection(self):
        self.post('/setup',campus='Other Campus');target=self.m['campus'].query.filter_by(campus='Other Campus').one()
        t=self.template();r=self.post(f'/template/{t.id}/edit',action='switch_campus',campus_id=str(target.id))
        other=self.m['template'].query.filter_by(campus_id=target.id,key=t.key).one();self.assertEqual(r.status_code,302);self.assertIn(f'/template/{other.id}/edit',r.location)
        data=dict(action='save',campus_id=str(target.id),version=str(t.version),name='Do not overwrite',header='',body='<p>Changed</p>',footer='')
        self.assertEqual(self.post(f'/template/{t.id}/edit',**data).status_code,422);self.assertNotEqual(other.name,'Do not overwrite')
        text=self.c.get('/workspace/certificates?tab=qr&export=csv&columns_configured=1&columns=name&columns=qr').data.decode()
        self.assertTrue(text.lstrip('\ufeff').startswith('Student Name,QR Code'));self.assertNotIn('Father Name',text)
        self.assertEqual(self.c.get('/workspace/certificates?tab=qr&columns_configured=1').status_code,422)
        printout=self.post('/qr-print',campus='Demo Campus',student_ids=str(self.s.id),columns=['name','qr'],columns_configured='1')
        self.assertEqual(printout.status_code,200);self.assertNotIn(b'<th>Father Name</th>',printout.data)

    def test_excel_export_keeps_names_as_strings_not_formulas(self):
        from openpyxl import load_workbook
        self.s.name='=1+1';db.session.commit()
        r=self.c.get('/workspace/certificates?tab=qr&export=xlsx&columns_configured=1&columns=name&columns=qr')
        self.assertEqual(r.status_code,200);self.assertIn('spreadsheetml',r.mimetype)
        sheet=load_workbook(io.BytesIO(r.data)).active;self.assertEqual(sheet['A2'].value,'=1+1');self.assertEqual(sheet['A2'].data_type,'s')
        self.assertTrue(sheet['B2'].value.startswith('schoolflow:student:'))
