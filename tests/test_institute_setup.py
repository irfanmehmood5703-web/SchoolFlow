"""Real setup/admission integration with fictional school data only."""
import io,os,re,unittest,json,html,copy
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

    def test_date_sheet_multiple_campuses_classes_sections_and_session(self):
        self.assertEqual(self.mapping(sections=['A','B']).status_code,302)
        self.assertEqual(self.mapping(class_name='Class B',sections=['A']).status_code,302)
        self.assertEqual(self.mapping(campus='Campus B',sections=['B']).status_code,302)
        db.session.add(self.rm['settings'](category='subject',value='Math',class_name=''))
        db.session.commit()
        path='/workspace/examination/date-sheets'
        page=self.c.get(path)
        self.assertEqual(page.status_code,200)
        self.assertIn(b'data-date-all-campuses> All Campuses',page.data)
        self.assertIn(b'data-date-campus-choice value="Campus A"',page.data)
        self.assertIn(b'data-date-campus-choice value="Campus B"',page.data)
        self.assertIn(b'All Classes',page.data)
        self.assertNotIn(b'All Campuses / All Classes / All Sections',page.data)
        self.assertIn(b'Academic Session',page.data)
        token=lambda campus,cls,section,academic='2026-27':json.dumps([campus,cls,section,academic],ensure_ascii=False,separators=(',',':'))
        chosen=[token('Campus A','Class A','A'),token('Campus A','Class B','A'),token('Campus B','Class A','B')]
        args=dict(_csrf=self.csrf,name='Weekly batch',date_scope='mapped',academic_session='2026-27',date_cohort=chosen,subject='Math',exam_date='2026-11-25',test_type='Written',total='20')
        W=app.extensions['ops_models']['workflow']
        self.assertEqual(self.c.post(path,data={**args,'date_cohort':chosen+[token('Campus B','Class B','A')]}).status_code,422)
        self.assertEqual(self.c.post(path,data={**args,'academic_session':'2027-28'}).status_code,422)
        self.assertEqual(W.query.filter_by(kind='date-sheets').count(),0)
        self.assertEqual(self.c.post(path,data=args).status_code,302)
        db.session.expire_all()
        rows=W.query.filter_by(kind='date-sheets').all()
        self.assertEqual(len(rows),3)
        self.assertEqual({(r.data['campus'],r.data['class_name'],r.data['section'],r.data['academic_session']) for r in rows},{('Campus A','Class A','A','2026-27'),('Campus A','Class B','A','2026-27'),('Campus B','Class A','B','2026-27')})
        self.assertTrue(all(r.data['papers'][0]['total']==20 and r.data['batch_name']=='Weekly batch' for r in rows))
        self.assertEqual(self.c.post(path,data=args).status_code,422)
        self.assertEqual(W.query.filter_by(kind='date-sheets').count(),3)
        refreshed=self.c.get(path)
        self.assertIn(b'Weekly batch',refreshed.data)
        self.assertIn(b'Campus B',refreshed.data)
        self.assertIn(b'2026-27',refreshed.data)

    def test_date_sheet_different_class_subjects_are_saved_only_to_assigned_classes(self):
        self.assertEqual(self.mapping().status_code,302)
        self.assertEqual(self.mapping(class_name='Class B').status_code,302)
        Item=app.extensions['school_settings_models']['item']
        for name,subjects in [('Class A',['Math']),('Class B',['Physics'])]:
            db.session.add(Item(kind='class-subjects',scope='Campus A',name=name,data={'subjects':subjects}))
        for name in ['Math','Physics','Urdu']:
            db.session.add(self.rm['settings'](category='subject',value=name,class_name=''))
        db.session.commit()
        path='/workspace/examination/date-sheets'
        page=self.c.get(path)
        self.assertIn(b'<select name="subject" required',page.data)
        self.assertIn(b'Physics',page.data)
        tokens=[json.dumps(['Campus A',cls,'A','2026-27'],separators=(',',':')) for cls in ['Class A','Class B']]
        args=dict(_csrf=self.csrf,name='Mixed subjects',date_scope='mapped',academic_session='2026-27',date_cohort=tokens,subject=['Math','Physics'],exam_date=['2026-11-25','2026-11-26'],test_type=['Written','Written'],total=['20','50'])
        W=app.extensions['ops_models']['workflow']
        self.assertEqual(self.c.post(path,data={**args,'subject':['Math']}).status_code,422)
        self.assertEqual(self.c.post(path,data={**args,'subject':['Math','Urdu']}).status_code,422)
        self.assertEqual(W.query.filter_by(kind='date-sheets').count(),0)
        self.assertEqual(self.c.post(path,data=args).status_code,302)
        db.session.expire_all()
        self.assertEqual({r.data['class_name']:[p['subject'] for p in r.data['papers']] for r in W.query.filter_by(kind='date-sheets').all()},{'Class A':['Math'],'Class B':['Physics']})

    def test_date_sheet_print_edit_delete_and_stale_guard(self):
        self.assertEqual(self.mapping().status_code,302)
        db.session.add(self.rm['settings'](category='subject',value='Math',class_name=''));db.session.commit()
        path='/workspace/examination/date-sheets'
        W=app.extensions['ops_models']['workflow']
        token=json.dumps(['Campus A','Class A','A','2026-27'],separators=(',',':'))
        args=dict(_csrf=self.csrf,name='Proof test',date_scope='mapped',academic_session='2026-27',date_cohort=token,subject='Math',exam_date='2026-11-25',test_type='Written',total='50',include_time='on',exam_time='09:00',include_syllabus='on',syllabus='Chapter 1',recheck='on')
        self.assertEqual(self.c.post(path,data=args).status_code,302)
        row=W.query.filter_by(kind='date-sheets').one();rid=row.id
        import hashlib
        rev=hashlib.sha256(json.dumps(row.data,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        for copy in ['parent','office']:
            page=self.c.get('/workspace/date-sheet/'+str(rid)+'/print?copy='+copy)
            self.assertEqual(page.status_code,200)
            for v in [b'25-11-2026',b'Wednesday',b'Total Marks',b'Chapter 1']:self.assertIn(v,page.data)
            self.assertEqual(b'Recheck / Initials' in page.data,copy=='office')
            columns=dict((key.decode(),float(width)) for key,width in re.findall(rb'<col class="date-sheet-col-([^"]+)" style="width:([0-9.]+)%">',page.data))
            self.assertEqual(len(columns),8 if copy=='office' else 7)
            self.assertAlmostEqual(sum(columns.values()),100,places=1)
            self.assertGreater(columns['syllabus'],2*columns['date'])
            self.assertEqual('recheck' in columns,copy=='office')
        self.assertEqual(self.c.get('/workspace/date-sheet/'+str(rid)+'/edit').status_code,200)
        edit={**args,'action':'edit','sheet_id':rid,'revision':rev,'total':'60'}
        self.assertEqual(self.c.post(path,data=edit).status_code,302)
        db.session.expire_all();self.assertEqual(db.session.get(W,rid).data['papers'][0]['total'],60)
        self.assertEqual(self.c.post(path,data=edit).status_code,422)
        current=db.session.get(W,rid)
        rev=hashlib.sha256(json.dumps(current.data,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        self.assertEqual(self.c.post(path,data=dict(_csrf=self.csrf,action='delete',sheet_id=rid,revision=rev)).status_code,302)
        self.assertIsNone(db.session.get(W,rid))

    def test_student_date_sheet_uses_admission_photo_and_matching_roster(self):
        W=app.extensions['ops_models']['workflow']
        row=W(kind='date-sheets',data=dict(name='Personal test',campus='Campus A',class_name='Class A',section='A',academic_session='2026-27',papers=[dict(subject='Math',date='2026-11-25',type='Written',total=20,time='',syllabus='')]),status='Active')
        pupil=Student(admission_no='PHOTO-1',name='Matching Student',father='Matching Guardian',class_name='Class A',status='Active')
        other=Student(admission_no='PHOTO-2',name='Wrong Section Student',class_name='Class A',status='Active')
        db.session.add_all([row,pupil,other]);db.session.flush()
        rid,sid,oid=row.id,pupil.id,other.id
        for s,sec in [(pupil,'A'),(other,'B')]:db.session.add(self.rm['student'](student_id=s.id,data=dict(campus='Campus A',section=sec,academic_session='2026-27',roll_no='7')))
        buf=io.BytesIO();Image.new('RGB',(20,20),'green').save(buf,format='PNG')
        db.session.add(self.rm['file'](owner_kind='student',owner_id=sid,title='Photo',filename='photo.png',mime='image/png',photo=True,content=buf.getvalue()))
        db.session.commit()
        path='/workspace/date-sheet/'+str(rid)
        select=self.c.get(path+'/print?copy=student')
        self.assertEqual(select.status_code,200);self.assertIn(b'Matching Student',select.data);self.assertNotIn(b'Wrong Section Student',select.data)
        page=self.c.get(path+'/print?copy=student&student_id='+str(sid))
        self.assertEqual(page.status_code,200);self.assertIn(b'Matching Student',page.data);self.assertIn(b'Student admission photo',page.data);self.assertIn(b'PHOTO-1',page.data)
        self.assertIn('no-store',page.headers['Cache-Control'])
        photo=self.c.get(path+'/student-photo/'+str(sid))
        self.assertEqual(photo.status_code,200);self.assertEqual(photo.data,buf.getvalue())
        self.assertEqual(self.c.get(path+'/student-photo/'+str(oid)).status_code,404)
        self.assertEqual(self.c.get(path+'/print?copy=student&student_id='+str(oid)).status_code,404)
        self.assertNotIn(b'Student admission photo',self.c.get(path+'/print?copy=student&photo=0&student_id='+str(sid)).data)
        self.assertNotIn(b'Matching Student',self.c.get(path+'/print?copy=parent').data)

    def test_read_only_page_no_setup_writes_and_legacy_catalog_still_works(self):
        page=self.c.get('/workspace/core/institute');self.assertEqual(page.status_code,200)
        ids=re.findall(rb'\bid="([^"]+)"',page.data);self.assertEqual(len(ids),len(set(ids)))
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

    def test_light_full_mode_is_saved_with_optimistic_version_and_preserves_school_name(self):
        self.assertEqual(self.post(action='profile',version='0',name='Fictional Mode School').status_code,302)
        Profile=self.models['profile'];profile=db.session.get(Profile,1)
        self.assertEqual(self.post(action='ui_mode',version=str(profile.version),mode='light').status_code,302)
        self.assertEqual(profile.data['name'],'Fictional Mode School');self.assertEqual(profile.data['ui_mode'],'light')
        page=self.c.get('/workspace/fees/payments');self.assertIn(b'data-advanced-default="light"',page.data);self.assertIn(b'data-advanced',page.data)
        revision=profile.data['ui_mode_revision'];old=profile.version
        self.assertEqual(self.post(action='ui_mode',version=str(old),mode='full').status_code,302)
        self.assertGreater(profile.data['ui_mode_revision'],revision)
        self.assertEqual(self.post(action='ui_mode',version=str(old),mode='light').status_code,422)
        self.assertEqual(self.post(action='ui_mode',version=str(profile.version),mode='invalid').status_code,422)

    def test_class_map_copy_history_undo_and_stale_source_guard(self):
        self.mapping();Map=self.models['mapping'];source=db.session.get(Map,('Campus A','Class A'))
        data=dict(action='copy_maps',source_campus='Campus A',target_campus='Campus B',copy_classes=['Class A'],**{'source_version_Class A':str(source.version)})
        self.assertEqual(self.post(**data).status_code,302);target=db.session.get(Map,('Campus B','Class A'));self.assertEqual(target.data,source.data)
        self.assertEqual(self.post(**data).status_code,422)
        Audit=app.extensions['ops_models']['audit'];event=Audit.query.filter_by(action='Update class map').order_by(Audit.id.desc()).first()
        self.assertEqual(self.post(action='undo_map',event_id=str(event.id)).status_code,302);self.assertIsNone(db.session.get(Map,('Campus B','Class A')))
        self.assertEqual(self.post(action='undo_map',event_id=str(event.id)).status_code,422)
        self.mapping(version=str(source.version),groups=['Science']);self.assertEqual(self.post(**data).status_code,422)

    def test_map_undo_cannot_overwrite_later_changes(self):
        self.mapping();Audit=app.extensions['ops_models']['audit'];first=Audit.query.filter_by(action='Update class map').one()
        Map=self.models['mapping'];row=db.session.get(Map,('Campus A','Class A'));self.mapping(version=str(row.version),sections=['B'])
        self.assertEqual(self.post(action='undo_map',event_id=str(first.id)).status_code,422)
        last=Audit.query.filter_by(action='Update class map').order_by(Audit.id.desc()).first()
        self.assertEqual(self.post(action='undo_map',event_id=str(last.id)).status_code,302);self.assertEqual(row.data['sections'],['A'])

    def setup_token(self,response):
        import html
        self.assertEqual(response.status_code,200);return html.unescape(re.search(rb'name="setup_review_token" value="([^"]+)"',response.data)[1].decode())
    def make_ready(self):
        Profile=self.models['profile'];Campus=self.models['campus'];Map=self.models['mapping'];Head=app.extensions['fee_setup_models']['head'];Schedule=app.extensions['fee_setup_models']['schedule']
        db.session.add(Profile(id=1,data=dict(name='Fictional ready school',current_session='2026-27',year_start='2026-04-01',year_end='2027-03-31',ui_mode='light')))
        db.session.add(Campus(name='Campus A',active=True));db.session.add(Map(campus='Campus A',class_name='Class A',active=True,data=dict(sections=['A'],groups=['General'],fee_plans=['Plan A'],academic_session='2026-27')))
        db.session.add(Head(key='Tuition Fee',label='Tuition Fee',timing='monthly',months=[],custom=False));db.session.add(Schedule(name='Plan A',campus='Campus A',class_name='Class A',description='',due_day=10,lines=[dict(key='Tuition Fee',amount=100000)]));db.session.commit()
    def test_setup_readiness_checks_actual_saved_data_without_writes(self):
        page=self.c.get('/workspace/core/institute');self.assertIn(b'Needs attention',page.data);self.assertEqual(self.models['profile'].query.count(),0)
        self.assertEqual(self.post(action='complete_setup',version='0',setup_review_token=self.setup_token(page)).status_code,422)
        self.make_ready();page=self.c.get('/workspace/core/institute');self.assertIn(b'Setup readiness',page.data);self.assertNotIn(b'<td>Needs attention</td>',page.data)
    def test_complete_setup_requires_fresh_review_and_preserves_operational_records(self):
        self.make_ready();page=self.c.get('/workspace/core/institute');token=self.setup_token(page)
        response=self.post(action='complete_setup',version='1',setup_review_token=token)
        self.assertEqual(response.status_code,302);self.assertTrue(response.location.endswith('#setup-readiness'))
        completed=self.c.get(response.location);self.assertIn(b'data-setup-completed',completed.data);self.assertIn(b'Institute setup completed.',completed.data)
        profile=self.models['profile'].query.one();self.assertTrue(profile.data['setup_activated_at']);self.assertEqual(profile.data['name'],'Fictional ready school')
        self.assertEqual(Student.query.count(),0);self.assertEqual(app.extensions['ops_models']['bill'].query.count(),0);self.assertEqual(app.extensions['ops_models']['salary'].query.count(),0)
        self.assertEqual(self.post(action='complete_setup',version='1',setup_review_token=token).status_code,422)
    def test_stale_or_cross_session_setup_review_cannot_complete(self):
        self.make_ready();page=self.c.get('/workspace/core/institute');token=self.setup_token(page);head=app.extensions['fee_setup_models']['head'].query.one();head.label='Changed';db.session.commit()
        self.assertEqual(self.post(action='complete_setup',version='1',setup_review_token=token).status_code,422)
        token=self.setup_token(self.c.get('/workspace/core/institute'));other=app.test_client();other.get('/workspace/core/institute')
        with other.session_transaction() as sess:csrf=sess['record_csrf']
        self.assertEqual(other.post('/workspace/core/institute',data=dict(_csrf=csrf,action='complete_setup',version='1',setup_review_token=token)).status_code,422)
    def test_copied_map_without_matching_fee_schedule_is_not_ready(self):
        self.make_ready();Schedule=app.extensions['fee_setup_models']['schedule'];db.session.delete(Schedule.query.one());db.session.commit()
        page=self.c.get('/workspace/core/institute');self.assertIn(b'<td>Needs attention</td>',page.data)
        self.assertEqual(self.post(action='complete_setup',version='1',setup_review_token=self.setup_token(page)).status_code,422)

    def concurrent_saves(self,path,forms,check):
        import tempfile,threading
        from concurrent.futures import ThreadPoolExecutor
        from flask import g,request
        from sqlalchemy import create_engine,select
        db.session.remove()
        with tempfile.TemporaryDirectory() as directory:
            engine=create_engine('sqlite:///'+directory+'/settings.db',connect_args={'timeout':20})
            tables=app.extensions['identity_helpers']['workspace_tables']();db.metadata.create_all(engine,tables=tables)
            with db.engine.connect() as source,engine.begin() as target:
                for table in tables:
                    rows=[dict(r) for r in source.execute(select(table)).mappings().all()]
                    if rows:target.execute(table.insert(),rows)
            barrier=threading.Barrier(2)
            def bind():
                if request.path==path:
                    g.institute_engine=engine
                    if request.method=='POST':barrier.wait(timeout=10)
            app.before_request_funcs.setdefault(None,[]).append(bind)
            try:
                def save(form):
                    client=app.test_client()
                    with client.session_transaction() as session:session['record_csrf']='concurrent-setup'
                    return client.post(path,data={'_csrf':'concurrent-setup',**form}).status_code
                with ThreadPoolExecutor(max_workers=2) as pool:statuses=list(pool.map(save,forms))
                with engine.connect() as connection:check(statuses,connection)
            finally:
                app.before_request_funcs[None].remove(bind);db.session.remove();g.pop('institute_engine',None);engine.dispose()

    def test_concurrent_catalog_forms_create_one_option_and_report_the_duplicate(self):
        from sqlalchemy import select
        table=self.rm['settings'].__table__
        def check(statuses,connection):
            self.assertEqual(sorted(statuses),[302,422])
            rows=connection.execute(select(table.c.value).where(table.c.value=='Concurrent class')).scalars().all()
            self.assertEqual(rows,['Concurrent class'])
        form=dict(category='class_name',value='Concurrent class')
        self.concurrent_saves('/records/settings',[form,form],check)

    def test_concurrent_inline_options_return_one_shared_choice_without_server_error(self):
        from sqlalchemy import select
        table=self.rm['settings'].__table__
        def check(statuses,connection):
            self.assertEqual(statuses,[200,200])
            rows=connection.execute(select(table.c.value).where(table.c.value=='Concurrent class')).scalars().all()
            self.assertEqual(rows,['Concurrent class'])
        form=dict(category='class_name',value='Concurrent class')
        self.concurrent_saves('/records/options',[form,form],check)

    def test_concurrent_profile_and_academic_edits_do_not_erase_each_other(self):
        from sqlalchemy import select
        self.post(action='profile',version='0',name='Original fictional school')
        table=self.models['profile'].__table__
        def check(statuses,connection):
            self.assertEqual(sorted(statuses),[302,422])
            saved=connection.execute(select(table.c.data,table.c.version)).one()
            self.assertEqual(saved.version,2)
            if statuses[0]==302:
                self.assertEqual(saved.data['name'],'Updated fictional school');self.assertNotIn('current_session',saved.data)
            else:
                self.assertEqual(saved.data['name'],'Original fictional school');self.assertEqual(saved.data['current_session'],'2027-28')
        self.concurrent_saves('/workspace/core/institute',[
            dict(action='profile',version='1',name='Updated fictional school'),
            dict(action='academic',version='1',current_session='2027-28',year_start='2027-04-01',year_end='2028-03-31')],check)

    def map_snapshot(self):
        page=self.c.get('/workspace/core/institute')
        return html.unescape(re.search(rb"name=\"map_versions\" value='([^']*)'",page.data)[1].decode())

    def test_bulk_classes_share_one_plan_and_do_not_create_student_fees(self):
        response=self.mapping(class_name=['Class A','Class B'],map_versions=self.map_snapshot())
        self.assertEqual(response.status_code,302)
        Map=self.models['mapping'];rows=Map.query.order_by(Map.class_name).all();self.assertEqual(len(rows),2)
        for row in rows:
            self.assertEqual(row.data,dict(sections=['A'],groups=['General'],fee_plans=['Plan A'],academic_session='2026-27'));self.assertTrue(row.active)
        self.assertEqual(Student.query.count(),0);self.assertEqual(app.extensions['ops_models']['bill'].query.count(),0)
        self.assertEqual(app.extensions['ops_models']['workflow'].query.count(),0)
        self.assertEqual(app.extensions['ops_models']['audit'].query.filter_by(action='Update class map').count(),2)
        payload=self.c.get('/workspace/core/admission-options').json;self.assertEqual({r['class_name'] for r in payload['maps']['Campus A']},{'Class A','Class B'})

    def test_bulk_updates_existing_and_new_rows_and_keeps_other_campus(self):
        self.mapping();self.mapping(campus='Campus B',sections=['B'])
        Map=self.models['mapping'];other=copy.deepcopy(db.session.get(Map,('Campus B','Class A')).data)
        self.assertEqual(self.mapping(class_name=['Class A','Class B'],sections=['B'],fee_plans=['Plan B'],map_versions=self.map_snapshot()).status_code,302)
        for cls in ['Class A','Class B']:
            row=db.session.get(Map,('Campus A',cls));self.assertEqual(row.data['sections'],['B']);self.assertEqual(row.data['fee_plans'],['Plan B'])
        self.assertEqual(db.session.get(Map,('Campus B','Class A')).data,other)
        self.assertEqual(db.session.get(Map,('Campus A','Class A')).version,2)

    def test_stale_one_row_blocks_the_entire_bulk_save(self):
        self.mapping();snapshot=self.map_snapshot();self.mapping(version='1',sections=['B'])
        r=self.mapping(class_name=['Class B','Class A'],fee_plans=['Plan B'],map_versions=snapshot)
        self.assertEqual(r.status_code,422);Map=self.models['mapping'];self.assertIsNone(db.session.get(Map,('Campus A','Class B')))
        self.assertEqual(db.session.get(Map,('Campus A','Class A')).data['sections'],['B']);self.assertEqual(db.session.get(Map,('Campus A','Class A')).data['fee_plans'],['Plan A'])

    def test_bulk_rejects_invalid_selection_and_version_snapshot_atomically(self):
        for changes in [dict(class_name=[]),dict(class_name=['Class A','Class A']),dict(class_name=['Class A','Missing']),dict(class_name=['Class A','Class B']),dict(class_name=['Class A','Class B'],map_versions='{}'),dict(class_name=['Class A','Class B'],map_versions='invalid'),dict(class_name=['Class A','Class B'],map_versions='[["Campus A","Class A",true]]'),dict(class_name=['Class A','Class B'],map_versions='[]',fee_plans=['Missing'])]:
            self.assertEqual(self.mapping(**changes).status_code,422,changes);self.assertEqual(self.models['mapping'].query.count(),0)

    def test_single_edit_after_bulk_preserves_unselected_classes(self):
        self.mapping(class_name=['Class A','Class B'],map_versions=self.map_snapshot());Map=self.models['mapping']
        before=copy.deepcopy(db.session.get(Map,('Campus A','Class B')).data)
        self.assertEqual(self.mapping(class_name=['Class A'],map_versions=self.map_snapshot(),fee_plans=['Plan B']).status_code,302)
        self.assertEqual(db.session.get(Map,('Campus A','Class B')).data,before);self.assertEqual(db.session.get(Map,('Campus A','Class B')).version,1)

    def test_bulk_history_undo_restores_existing_and_removes_only_new_map(self):
        self.mapping();self.mapping(class_name=['Class A','Class B'],map_versions=self.map_snapshot(),fee_plans=['Plan B'])
        Audit=app.extensions['ops_models']['audit'];events=Audit.query.filter_by(action='Update class map').order_by(Audit.id.desc()).limit(2).all()
        for event in events:self.assertEqual(self.post(action='undo_map',event_id=str(event.id)).status_code,302)
        Map=self.models['mapping'];self.assertIsNone(db.session.get(Map,('Campus A','Class B')));self.assertEqual(db.session.get(Map,('Campus A','Class A')).data['fee_plans'],['Plan A'])

    def test_concurrent_bulk_submissions_do_not_partially_overwrite_each_other(self):
        from sqlalchemy import select
        table=self.models['mapping'].__table__
        def check(statuses,connection):
            self.assertEqual(sorted(statuses),[302,422]);rows=connection.execute(select(table)).mappings().all();self.assertEqual(len(rows),2)
            self.assertEqual(rows[0]['data'],rows[1]['data']);self.assertEqual([r['version'] for r in rows],[1,1])
        common=dict(action='map',class_name=['Class A','Class B'],campus='Campus A',map_versions='[]',sections=['A'],groups=['General'],academic_session='2026-27',active='1')
        self.concurrent_saves('/workspace/core/institute',[dict(common,fee_plans=['Plan A']),dict(common,fee_plans=['Plan B'])],check)

    def test_setup_saves_redirect_to_their_own_section(self):
        academic=self.post(action='academic',version='0',current_session='2026-27',year_start='2026-01-01',year_end='2026-12-31')
        self.assertEqual(academic.status_code,302);self.assertTrue(academic.location.endswith('#academic-year'))
        mapping=self.mapping();self.assertEqual(mapping.status_code,302);self.assertTrue(mapping.location.endswith('#class-map'))
        profile=self.models['profile'].query.one()
        mode=self.post(action='ui_mode',version=str(profile.version),mode='light');self.assertTrue(mode.location.endswith('#display-mode'))

    def test_class_map_rejects_multiple_sessions_without_saving(self):
        response=self.mapping(academic_session=['2026-27','2027-28'])
        self.assertEqual(response.status_code,422);self.assertIn(b'Choose exactly one class session',response.data)
        self.assertEqual(self.models['mapping'].query.count(),0)
