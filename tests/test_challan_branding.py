"""Challan branding uses tenant settings and saved financial amounts only."""
import os,re,unittest
from datetime import date
os.environ['DATABASE_URL']='sqlite:///:memory:'
from app import app,db,Student
from challan_branding import DEFAULTS,FLAGS

class ChallanBrandingTests(unittest.TestCase):
    def setUp(self):
        app.config.update(TESTING=True,IDENTITY_ENFORCE_IN_TESTS=False,SECRET_KEY='print-test')
        self.ctx=app.app_context();self.ctx.push();db.drop_all();db.create_all()
        self.Item=app.extensions['school_settings_models']['item'];self.rm=app.extensions['record_models'];self.ops=app.extensions['ops_models'];self.B=self.ops['bill']
        self.c=app.test_client()
        for campus in ('Campus A','Campus B'):db.session.add(self.rm['settings'](category='campus',value=campus,class_name=''))
        profile=app.extensions['institute_setup_models']['profile'];db.session.add(profile(id=1,data=dict(name='Fictional School',address='School address',contact='School contact'),logo_mime='image/png',logo=b'fictional'))
        self.s=self.student('A','Campus A','F-1');self.bill=self.invoice(self.s)
        db.session.commit();self.c.get('/workspace/core/fees/challan-branding')
        with self.c.session_transaction() as sess:self.csrf=sess['record_csrf']
    def tearDown(self):db.session.remove();db.drop_all();self.ctx.pop()
    def student(self,name,campus,family):
        s=Student(admission_no='PRINT-'+name,name='Fictional '+name,father='Guardian '+name,class_name='One',status='Active');db.session.add(s);db.session.flush();db.session.add(self.rm['student'](student_id=s.id,data=dict(campus=campus,family_no=family)));return s
    def invoice(self,s,amount=350000,month='2026-10'):
        b=self.B(student_id=s.id,month=month,due=date(2026,10,10),lines=[dict(particular='Tuition Fee',display_name='Saved Tuition Name',amount=amount),dict(particular='Zero Head',amount=0)],discount=50000,paid=100000);db.session.add(b);db.session.flush();return b
    def row(self,campus=''):return self.Item.query.filter_by(kind='challan-branding',scope=campus).first()
    def post(self,**changes):
        campus=changes.get('campus','');row=self.row(campus)
        data={**DEFAULTS,**{flag:'1' for flag in FLAGS if DEFAULTS[flag]},'_csrf':self.csrf,'action':'save','campus':campus,'version':str(row.version if row else 0)}
        # HTML unchecked boxes do not send False strings.
        for flag in FLAGS:
            if not DEFAULTS[flag]:data.pop(flag,None)
        data.update(changes)
        return self.c.post('/workspace/core/fees/challan-branding',data=data)
    def print(self,**changes):
        data=dict(_csrf=self.csrf,action='branded',ids=str(self.bill.id));data.update(changes);return self.c.post('/workspace/fee-action',data=data)
    def test_get_is_read_only_and_form_ids_unique(self):
        for scope in ('','Campus A'):
            r=self.c.get('/workspace/core/fees/challan-branding',query_string={'campus':scope});self.assertEqual(r.status_code,200)
            ids=re.findall(rb'\bid="([^"]+)"',r.data);self.assertEqual(len(ids),len(set(ids)))
        self.assertEqual(self.Item.query.count(),0)
        self.assertIn(b'Challan Branding',self.c.get('/workspace/core/fees/heads').data)
    def test_csrf_scope_action_and_stale_version_guards(self):
        self.assertEqual(self.post(_csrf='').status_code,400)
        self.assertEqual(self.post(campus='Other').status_code,422)
        self.assertEqual(self.post(action='other').status_code,422)
        self.assertEqual(self.post().status_code,302)
        self.assertEqual(self.post(version='0',note='stale').status_code,422)
        self.assertEqual(self.post(action='reset',version='0').status_code,422)
        self.assertEqual(self.row().data['note'],'')
    def test_invalid_colors_layout_copies_and_text_do_not_save(self):
        for changes in [dict(primary='red'),dict(ink='#fff;display:none'),dict(layout='custom'),dict(copy_1='',copy_2='',copy_3=''),dict(copy_2='student copy'),dict(note='x'*1501),dict(copy_1='x'*61)]:
            self.assertEqual(self.post(**changes).status_code,422,changes);self.assertIsNone(self.row())
    def test_preview_escapes_unsaved_values_and_does_not_write_or_read_people(self):
        r=self.post(action='preview',copy_1='<b>Parent</b>',note='<script>alert(1)</script> [studentName]',bank_name='Example Bank',copy_3='')
        self.assertEqual(r.status_code,200);self.assertIn(b'Unsaved design preview',r.data);self.assertIn(b'&lt;script&gt;',r.data);self.assertIn(b'[studentName]',r.data);self.assertNotIn(b'<script>',r.data)
        self.assertNotIn(self.s.name.encode(),r.data);self.assertEqual(r.data.count(b'class="sf-fee-copy"'),2)
        self.assertIsNone(self.row());self.assertEqual(self.B.query.count(),1);self.assertEqual(self.ops['audit'].query.count(),0)
    def test_full_campus_override_fallback_and_reset(self):
        self.post(note='Default note');self.assertIn(b'Default note',self.print().data)
        self.post(campus='Campus A',note='Campus note');self.assertIn(b'Campus note',self.print().data);self.assertNotIn(b'Default note',self.print().data)
        self.post(note='Changed default');self.assertIn(b'Campus note',self.print().data)
        self.assertEqual(self.post(campus='Campus A',action='reset').status_code,302);self.assertIn(b'Changed default',self.print().data)
        self.post(action='reset');self.assertIsNone(self.row());self.assertEqual(self.print().status_code,200)
    def test_saved_print_uses_school_custom_labels_bank_and_frozen_money(self):
        self.post(copy_1='Parent receipt',copy_2='',copy_3='',primary='#123ABC',address='Campus address',contact='Campus phone',bank_name='Fictional Bank',account_title='School account',account_no='000123',iban='PK-EXAMPLE',note='<img src=x onerror=alert(1)>')
        old=(self.bill.total,self.bill.discount,self.bill.paid,self.bill.remaining,list(self.bill.lines))
        r=self.print();self.assertEqual(r.status_code,200);self.assertIn(b'Fictional School',r.data);self.assertIn(b'Parent receipt',r.data);self.assertIn(b'--fee-primary:#123abc',r.data);self.assertIn(b'000123',r.data);self.assertIn(b'PK-EXAMPLE',r.data)
        self.assertIn(b'Saved Tuition Name',r.data);self.assertIn(b'3,500.00',r.data);self.assertIn(b'2,000.00',r.data);self.assertIn(b'&lt;img',r.data);self.assertNotIn(b'onerror=alert(1)>',r.data)
        self.assertEqual(old,(self.bill.total,self.bill.discount,self.bill.paid,self.bill.remaining,list(self.bill.lines)))
        self.assertEqual(r.data.count(b'class="sf-fee-copy"'),1);self.assertIn(b'/workspace/core/logo',r.data)
    def test_visibility_and_explicit_run_override(self):
        self.post(hide_status='1',show_logo='',show_father='',hide_zero='1')
        r=self.print();self.assertNotIn(b'Status:',r.data);self.assertNotIn(b'Zero Head',r.data);self.assertNotIn(b'Guardian A',r.data);self.assertNotIn(b'alt="School logo"',r.data)
        r=self.print(print_options_present='1');self.assertIn(b'Zero Head',r.data);self.assertIn(b'Status:',r.data)
        self.assertTrue(self.row().data['hide_status']);self.assertTrue(self.row().data['hide_zero'])
    def test_layout_buttons_are_temporary_overrides(self):
        self.post(layout='portrait')
        self.assertIn(b'sf-fee-portrait',self.print().data);self.assertIn(b'sf-fee-landscape',self.print(action='vertical').data);self.assertIn(b'sf-fee-portrait',self.print(action='horizontal').data)
        self.assertEqual(self.row().data['layout'],'portrait')
    def test_family_groups_never_merge_campuses_or_blank_families(self):
        s2=self.student('B','Campus A','F-1');s3=self.student('C','Campus B','F-1');s4=self.student('D','Campus A','');s5=self.student('E','Campus A','')
        bills=[self.bill]+[self.invoice(s) for s in (s2,s3,s4,s5)];db.session.commit()
        r=self.print(action='family',ids=[str(b.id) for b in bills]);self.assertEqual(r.status_code,200)
        self.assertEqual(r.data.count(b'<article class="sf-fee-sheet'),4)
        self.assertEqual(r.data.count(b'Selected remaining total: 4,000.00'),3)
        self.assertEqual(r.data.count(b'Fictional C'),3);self.assertIn(b'Selected challans only',r.data)
        # Ordinary multi-selection prints one separate sheet per bill.
        self.assertEqual(self.print(ids=[str(b.id) for b in bills]).data.count(b'<article class="sf-fee-sheet'),5)
    def test_student_photo_uses_private_route_and_saved_head_is_unchanged(self):
        self.post(show_photo='1');File=self.rm['file'];db.session.add(File(owner_kind='student',owner_id=self.s.id,title='Photo',filename='photo.png',mime='image/png',photo=True,content=b'PRIVATE_IMAGE_BYTES',sha256='x'));db.session.commit()
        r=self.print();self.assertEqual(r.status_code,200);self.assertIn(b'alt="Student photo"',r.data);self.assertNotIn(b'PRIVATE_IMAGE_BYTES',r.data)
        fid=File.query.one().id
        self.assertIn(('/records/files/'+str(fid)).encode(),r.data)
        self.assertEqual(self.bill.lines[0]['display_name'],'Saved Tuition Name')
    def test_audit_before_after_and_preview_of_existing_row(self):
        self.post(note='First');version=self.row().version;self.post(note='Second')
        audit=self.ops['audit'].query.order_by(self.ops['audit'].id.desc()).first();self.assertEqual(audit.data['before']['note'],'First');self.assertEqual(audit.data['after']['note'],'Second')
        self.assertGreater(self.row().version,version)
        saved_version=self.row().version;self.post(action='preview',note='Unsaved');self.assertEqual(self.row().version,saved_version);self.assertEqual(self.row().data['note'],'Second')

    def test_batch_print_reads_photo_metadata_without_loading_image_blobs(self):
        from sqlalchemy import event
        self.post(show_photo='1')
        bills=[self.bill]
        for i in range(15):
            pupil=self.student('Batch'+str(i),'Campus A','F-BATCH');bills.append(self.invoice(pupil))
            db.session.add(self.rm['file'](owner_kind='student',owner_id=pupil.id,title='Photo',filename='p.png',mime='image/png',photo=True,content=b'BATCH_PRIVATE_BYTES',sha256='x'))
        db.session.commit();ids=[str(b.id) for b in bills];queries=[]
        def capture(conn,cursor,statement,parameters,context,executemany):
            if statement.lstrip().lower().startswith('select'):queries.append(statement.lower())
        event.listen(db.engine,'before_cursor_execute',capture)
        try:response=self.print(ids=ids)
        finally:event.remove(db.engine,'before_cursor_execute',capture)
        self.assertEqual(response.status_code,200);self.assertLessEqual(len(queries),16,queries)
        self.assertFalse(any('record_file.content' in q for q in queries));self.assertNotIn(b'BATCH_PRIVATE_BYTES',response.data)
        self.assertEqual(response.data.count(b'alt="Student photo"'),45)
