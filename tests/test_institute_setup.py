"""Real setup/admission integration with fictional school data only."""
import io,os,unittest
os.environ['DATABASE_URL']='sqlite:///:memory:'
from PIL import Image
from app import app,db,Student

class InstituteSetupTests(unittest.TestCase):
    def setUp(self):
        app.config.update(TESTING=True,IDENTITY_ENFORCE_IN_TESTS=False)
        self.ctx=app.app_context();self.ctx.push();db.drop_all();db.create_all()
        self.rm=app.extensions['record_models'];self.models=app.extensions['institute_setup_models']
        for category,values in {'campus':['Campus A','Campus B'],'class_name':['Class A','Class B'],'section':['A','B'],'group_name':['General','Science'],'academic_session':['2026-27','2027-28'],'fee_plan':['Plan A','Plan B']}.items():
            for value in values:db.session.add(self.rm['settings'](category=category,value=value,class_name=''))
        db.session.commit();self.c=app.test_client();self.c.get('/workspace/core/institute')
        with self.c.session_transaction() as session:self.csrf=session['record_csrf']
    def tearDown(self):
        db.session.remove();db.drop_all();self.ctx.pop()
    def post(self,**values):return self.c.post('/workspace/core/institute',data={'_csrf':self.csrf,**values})
    def mapping(self,**changes):
        values=dict(action='map',version='0',campus='Campus A',class_name='Class A',sections=['A'],groups=['General'],fee_plans=['Plan A'],academic_session='2026-27',active='1');values.update(changes);return self.post(**values)
    def student(self,**changes):
        data=dict(_csrf=self.csrf,name='Fictional Pupil',father='Fictional Guardian',father_cnic='TEST-ONLY',phone='00000000000',family_mode='new',gender='Female',guardian_relation='Father',admission_date='2026-10-31',campus='Campus A',class_name='Class A',section='A',group_name='General',academic_session='2026-27',fee_plan='Plan A',status='Active',save_action='view');data.update(changes);return data
    def test_read_only_page_no_setup_writes_and_legacy_catalog_still_works(self):
        self.assertEqual(self.c.get('/workspace/core/institute').status_code,200)
        for model in self.models.values():self.assertEqual(model.query.count(),0)
        self.assertEqual(self.c.get('/workspace/core/admission-options').json,{'campuses':{},'maps':{}})
        self.assertEqual(self.c.post('/records/student/new',data=self.student()).status_code,302)
    def test_map_restricts_every_link_on_server_and_preserves_atomicity(self):
        self.assertEqual(self.mapping().status_code,302)
        for key,value in [('class_name','Class B'),('section','B'),('group_name','Science'),('academic_session','2027-28'),('fee_plan','Plan B')]:
            r=self.c.post('/records/student/new',data=self.student(**{key:value}))
            self.assertEqual(r.status_code,422,key);self.assertEqual(Student.query.count(),0);self.assertEqual(self.rm['family'].query.count(),0)
        self.assertEqual(self.c.post('/records/student/new',data=self.student()).status_code,302)
        p=self.c.get('/workspace/core/admission-options').json
        self.assertEqual(p['maps']['Campus A'][0]['sections'],['A'])
    def test_campuses_have_independent_maps_and_disabled_maps_are_not_fallback(self):
        self.mapping();self.mapping(campus='Campus B',sections=['B'],groups=['Science'],academic_session='2027-28',fee_plans=['Plan B'])
        self.assertEqual(self.c.post('/records/student/new',data=self.student(campus='Campus B')).status_code,422)
        self.assertEqual(self.c.post('/records/student/new',data=self.student(campus='Campus B',section='B',group_name='Science',academic_session='2027-28',fee_plan='Plan B')).status_code,302)
        self.assertEqual(self.mapping(version='1',active='').status_code,302)
        self.assertEqual(self.c.get('/workspace/core/admission-options').json['maps']['Campus A'],[])
        self.assertEqual(self.c.post('/records/student/new',data=self.student()).status_code,422)
    def test_unknown_options_bad_actions_csrf_and_stale_edits_do_not_write(self):
        self.assertEqual(self.mapping(sections=['Unknown']).status_code,422)
        self.assertEqual(self.models['mapping'].query.count(),0)
        self.assertEqual(self.post(action='unknown').status_code,422)
        self.assertEqual(self.c.post('/workspace/core/institute',data={'action':'map'}).status_code,400)
        self.mapping()
        self.assertEqual(self.mapping(sections=['B']).status_code,422)
        self.assertEqual(self.models['mapping'].query.one().data['sections'],['A'])
    def test_historical_edit_retained_but_changed_link_and_reactivation_checked(self):
        self.mapping();self.c.post('/records/student/new',data=self.student());pupil=Student.query.one();sid=pupil.id;fam=self.rm['family'].query.one().id
        self.mapping(version='1',sections=['B'])
        update=self.student(name='Updated Fictional Pupil',family_mode='existing',family_id=str(fam))
        self.assertEqual(self.c.post(f'/records/student/{sid}/edit',data=update).status_code,302)
        update['fee_plan']='Plan B'
        self.assertEqual(self.c.post(f'/records/student/{sid}/edit',data=update).status_code,422)
        pupil.status='Inactive';db.session.commit();update['fee_plan']='Plan A'
        self.assertEqual(self.c.post(f'/records/student/{sid}/edit',data=update).status_code,422)
    def test_inactive_campus_rejects_admissions_and_catalog_reused_across_modules(self):
        self.assertEqual(self.post(action='campus',version='0',campus='Campus A',short_name='A',city='Test City').status_code,302)
        self.assertEqual(self.c.post('/records/student/new',data=self.student()).status_code,422)
        self.assertEqual(self.post(action='campus',version='1',campus='Campus A',active='1').status_code,302)
        self.assertEqual(self.post(action='campus',version='0',campus='New Campus',active='1').status_code,302)
        self.assertEqual(self.rm['settings'].query.filter_by(category='campus',value='New Campus').count(),1)
        for path in ['/records/student/new','/records/employee/new','/workspace/attendance/student','/workspace/examination/awards']:
            page=self.c.get(path);self.assertEqual(page.status_code,200);self.assertIn(b'New Campus',page.data,path)
    def test_academic_year_validates_defaults_and_does_not_move_students(self):
        self.c.post('/records/student/new',data=self.student())
        self.assertEqual(self.post(action='academic',version='0',current_session='2027-28',year_start='2027-04-01',year_end='2027-03-31').status_code,422)
        self.assertEqual(self.models['profile'].query.count(),0)
        self.assertEqual(self.post(action='academic',version='0',current_session='2027-28',year_start='2027-04-01',year_end='2028-03-31').status_code,302)
        page=self.c.get('/records/student/new').data
        self.assertIn(b'value="2027-28" selected',page)
        self.assertEqual(self.rm['student'].query.one().data['academic_session'],'2026-27')
        self.assertEqual(self.post(action='academic',version='0',current_session='2026-27',year_start='2026-04-01',year_end='2027-03-31').status_code,422)
    def test_profile_logo_is_private_and_header_used_by_all_four_modules(self):
        image=io.BytesIO();Image.new('RGB',(24,24),'green').save(image,format='PNG')
        self.assertEqual(self.post(action='profile',version='0',name='Fictional School Name',website='https://example.invalid',logo=(io.BytesIO(image.getvalue()),'school.png')).status_code,302)
        response=self.c.get('/workspace/core/logo');self.assertEqual(response.status_code,200);self.assertEqual(response.mimetype,'image/png');self.assertIn('no-store',response.headers['Cache-Control'])
        for path in ['/workspace/dashboard','/records/student','/workspace/examination/awards','/records/employee']:
            page=self.c.get(path);self.assertIn(b'Fictional School Name',page.data);self.assertIn(b'/workspace/core/logo',page.data)
        self.assertEqual(self.post(action='profile',version='1',name='No overwrite',logo=(io.BytesIO(b'not an image'),'bad.png')).status_code,422)
        self.assertEqual(self.models['profile'].query.one().data['name'],'Fictional School Name')
        self.assertEqual(self.post(action='profile',version='1',name='Fictional School Name',remove_logo='1').status_code,302)
        self.assertEqual(self.c.get('/workspace/core/logo').status_code,404)

    def test_approval_cannot_bypass_disabled_class_map(self):
        self.mapping();self.c.post('/records/student/new',data=self.student(status='Waiting'));sid=Student.query.one().id
        self.mapping(version='1',active='')
        r=self.c.post('/workspace/approve-students',data={'_csrf':self.csrf,'action':'approve','ids':[str(sid)]})
        self.assertEqual(r.status_code,422);self.assertEqual(Student.query.one().status,'Waiting')
        self.assertEqual(self.mapping(version='2',active='1').status_code,302)
        self.assertEqual(self.c.post('/workspace/approve-students',data={'_csrf':self.csrf,'action':'approve','ids':[str(sid)]}).status_code,302)
        self.assertEqual(Student.query.one().status,'Active')

    def test_attendance_keeps_campus_section_and_session_scope_after_save(self):
        self.c.post('/records/student/new',data=self.student());sid=Student.query.one().id
        self.c.post('/records/student/new',data=self.student(name='Outside selection',section='B'))
        page=self.c.get('/workspace/attendance/student?campus=Campus+A&class_name=Class+A&section=A&academic_session=2026-27')
        self.assertIn(b'Fictional Pupil',page.data);self.assertNotIn(b'Outside selection',page.data)
        response=self.c.post('/workspace/attendance/student',data={'_csrf':self.csrf,'day':'2026-10-31','campus':'Campus A','class_name':'Class A','section':'A','academic_session':'2026-27',f'status_{sid}':'Present'})
        self.assertEqual(response.status_code,302);self.assertIn('section=A',response.location);self.assertIn('academic_session=2026-27',response.location)
        rows=app.extensions['ops_models']['daily'].query.all();self.assertEqual(len(rows),1);self.assertEqual(rows[0].person_id,sid)
