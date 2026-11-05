"""Saved evidence, privacy, date boundaries, exports and non-mutating history."""
import io,os,unittest
from datetime import datetime
from flask import g,session
from openpyxl import load_workbook
os.environ['DATABASE_URL']='sqlite:///:memory:'
from app import app,db,Student

class UserLoggingTests(unittest.TestCase):
    path='/workspace/core/user-logging'
    def setUp(self):
        app.config.update(TESTING=True,IDENTITY_ENFORCE_IN_TESTS=False)
        self.ctx=app.app_context();self.ctx.push();db.drop_all();db.create_all();self.A=app.extensions['ops_models']['audit'];self.c=app.test_client()
    def tearDown(self):db.session.remove();db.drop_all();self.ctx.pop()
    def log(self,action='Update student',data=None,created=None):
        row=self.A(action=action,data=data or {},created=created or datetime(2026,11,5,10));db.session.add(row);db.session.commit();return row
    def test_read_only_default_hides_routine_and_retains_unknown_actor(self):
        self.log();self.log('Save attendance');self.log('Delete unpaid challans')
        page=self.c.get(self.path);self.assertEqual(page.status_code,200);self.assertIn(b'Update student',page.data);self.assertNotIn(b'Save attendance</td>',page.data);self.assertIn(b'Not recorded',page.data);self.assertEqual(self.A.query.count(),3)
        self.assertIn(b'Save attendance</td>',self.c.get(self.path+'?routine=1').data)
        with self.c.session_transaction() as s:csrf=s['record_csrf']
        self.assertEqual(self.c.post(self.path,data={'_csrf':csrf}).status_code,404)
    def test_karachi_dates_are_inclusive_and_severity_search_is_literal(self):
        self.log('Create student 10%',created=datetime(2026,11,4,19));self.log('Create student earlier',created=datetime(2026,11,4,18,59));self.log('Delete record',created=datetime(2026,11,5,20))
        page=self.c.get(self.path+'?from=2026-11-05&to=2026-11-05&q=%25');self.assertIn(b'Create student 10%',page.data);self.assertNotIn(b'Create student earlier</td>',page.data)
        self.assertIn(b'Delete record</td>',self.c.get(self.path+'?severity=Critical').data)
        self.assertNotIn(b'Create student 10%</td>',self.c.get(self.path+'?severity=Critical').data)
    def test_details_show_real_changes_and_hide_secrets_without_touching_history(self):
        row=self.log(data=dict(before={'name':'Old','phone':'123','password':'SECRET-OLD','token':'PRIVATE'},after={'name':'New','phone':'123','password':'SECRET-NEW','token':'PRIVATE'},nested={'password_hash':'HASH-SECRET'}))
        page=self.c.get(self.path+'/'+str(row.id));self.assertEqual(page.status_code,200);self.assertIn(b'Old',page.data);self.assertIn(b'New',page.data)
        for secret in [b'SECRET-OLD',b'SECRET-NEW',b'PRIVATE',b'HASH-SECRET']:self.assertNotIn(secret,page.data)
        self.assertIn('no-store',page.headers['Cache-Control']);self.assertEqual(row.data['before']['password'],'SECRET-OLD')
    def test_new_actor_is_captured_and_forged_payload_is_overwritten(self):
        with app.test_request_context('/workspace/test',method='POST'):
            g.school_identity={'email':'owner@example.invalid'};session['owner_id']=7
            row=self.log(data={'_activity_actor':{'label':'Forged'}})
            self.assertEqual(row.data['_activity_actor']['label'],'owner@example.invalid')
        page=self.c.get(self.path+'?actor=owner%40example.invalid');self.assertIn(b'owner@example.invalid</td>',page.data)
        with app.test_request_context('/internal/fine-worker'):
            g.school_identity=None;row=self.log('Save settings');self.assertEqual(row.data['_activity_actor']['label'],'System')
    def test_filtered_exports_use_all_rows_not_the_current_page_and_literal_text(self):
        for i in range(28):self.log('=Create student '+str(i))
        self.log('Delete other')
        r=self.c.get(self.path+'?q=Create&size=25&page=2&export=xlsx&columns=summary');self.assertEqual(r.status_code,200)
        book=load_workbook(io.BytesIO(r.data));rows=list(book['Report'].values);self.assertEqual(len(rows),29);self.assertEqual(len(rows[0]),1);self.assertEqual(book['Report']['A2'].data_type,'s')
        csv=self.c.get(self.path+'?q=Create&export=csv&columns=summary');self.assertIn(b"'=Create student",csv.data);self.assertNotIn(b'Delete other',csv.data)
    def test_bad_filters_and_export_columns_do_not_write(self):
        self.log()
        for query in ['severity=Missing','from=bad','from=2026-11-06&to=2026-11-05','size=10','page=0','columns=password','columns=actor&columns=actor','export=pdf']:
            self.assertEqual(self.c.get(self.path+'?'+query).status_code,422,query)
        self.assertEqual(self.A.query.count(),1)
    def test_record_links_use_only_current_institute_objects_and_deleted_records_are_clear(self):
        pupil=Student(admission_no='LOG-1',name='Fictional Pupil',class_name='One');db.session.add(pupil);db.session.commit()
        row=self.log(data={'record_kind':'student','record_id':pupil.id,'record_name':'Fictional Pupil'})
        self.assertIn(('/records/student/'+str(pupil.id)).encode(),self.c.get(self.path+'/'+str(row.id)).data)
        db.session.delete(pupil);db.session.commit();self.assertNotIn(b'Open record</a>',self.c.get(self.path+'/'+str(row.id)).data)
    def test_record_save_audit_has_actual_before_after_values(self):
        from record_schema import DEMO_CHOICES
        rm=app.extensions['record_models']
        for cat,values in DEMO_CHOICES.items():
            for v in values:db.session.add(rm['settings'](category=cat,value=v,class_name=''))
        db.session.commit();self.c.get('/records/student/new')
        with self.c.session_transaction() as s:csrf=s['record_csrf']
        data=dict(_csrf=csrf,name='Fictional first name',father='Guardian',father_cnic='TEST',phone='000',family_mode='new',gender='Female',guardian_relation='Father',admission_date='2026-11-05',campus=DEMO_CHOICES['campus'][0],class_name=DEMO_CHOICES['class_name'][0],section=DEMO_CHOICES['section'][0],group_name=DEMO_CHOICES['group_name'][0],academic_session=DEMO_CHOICES['academic_session'][0],fee_plan=DEMO_CHOICES['fee_plan'][0],status='Active')
        self.assertEqual(self.c.post('/records/student/new',data=data).status_code,302)
        pupil=Student.query.one();detail=rm['student'].query.one();data.update(name='Fictional updated name',family_mode='existing',family_id=str(detail.family_id))
        self.assertEqual(self.c.post('/records/student/'+str(pupil.id)+'/edit',data=data).status_code,302)
        row=self.A.query.filter_by(action='Update student').one();self.assertEqual(row.data['before']['name'],'Fictional first name');self.assertEqual(row.data['after']['name'],'Fictional updated name')
    def test_action_and_area_filters_validate_and_match_recorded_rows(self):
        Audit=app.extensions['ops_models']['audit'];db.session.add_all([Audit(action='Create student',data={}),Audit(action='Fee payment',data={})]);db.session.commit()
        response=self.c.get(self.path+'?action=Created&area=Admissions');self.assertEqual(response.status_code,200);self.assertIn(b'Create student',response.data);self.assertNotIn(b'>Fee payment<',response.data)
        for query in ('action=Forged','area=Unknown'):self.assertEqual(self.c.get(self.path+'?'+query).status_code,422)
