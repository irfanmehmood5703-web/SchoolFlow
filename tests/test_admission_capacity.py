"""Seat enforcement through record saves, atomic reviews and concurrent writers."""
import os,tempfile,threading,unittest
from pathlib import Path
from flask import g
from sqlalchemy import create_engine
os.environ['DATABASE_URL']='sqlite:///:memory:'
from app import app,db,Student
from record_schema import DEMO_CHOICES


class AdmissionCapacityTests(unittest.TestCase):
    def setUp(self):
        app.config.update(TESTING=True,SECRET_KEY='admission-fictional',IDENTITY_ENFORCE_IN_TESTS=False)
        self.ctx=app.app_context();self.ctx.push();db.drop_all();db.create_all()
        self.rm=app.extensions['record_models'];self.m=app.extensions['admission_capacity_models'];self.serial=0
        for category,values in DEMO_CHOICES.items():
            for value in values:db.session.add(self.rm['settings'](category=category,value=value,class_name=''))
        for category,value in [('class_name','Other Class'),('campus','Other Campus'),('academic_session','2027-28'),('section','B')]:
            db.session.add(self.rm['settings'](category=category,value=value,class_name=''))
        db.session.commit();self.c=app.test_client();self.c.get('/workspace/admission-capacity')
        with self.c.session_transaction() as sess:self.csrf=sess['record_csrf']

    def tearDown(self):db.session.remove();db.drop_all();self.ctx.pop()

    def limit(self,seats='1',**changes):
        key=tuple(changes.get(k,default) for k,default in [('campus','Demo Campus'),('class_name','Demo Class'),('academic_session','2026-27')])
        row=db.session.get(self.m['capacity'],key)
        data=dict(_csrf=self.csrf,campus=key[0],class_name=key[1],academic_session=key[2],seats=seats,version=str(row.version if row else 0));data.update(changes)
        return self.c.post('/workspace/admission-capacity',data=data)

    def form(self,**changes):
        self.serial+=1
        data=dict(_csrf=self.csrf,name='Fictional Pupil '+str(self.serial),admission_no='CAP-'+str(self.serial),gender='Female',
                  admission_date='2026-10-30',family_mode='new',father='Fictional Father',father_cnic='TEST-ONLY',
                  guardian_relation='Father',phone='00000000000',campus='Demo Campus',class_name='Demo Class',section='A',
                  group_name='General',academic_session='2026-27',fee_plan='Demo Fee Plan',status='Active',save_action='back')
        data.update(changes);return data

    def add(self,**changes):
        data=self.form(**changes);response=self.c.post('/records/student/new',data=data)
        self.assertEqual(response.status_code,302,response.data[:300])
        return Student.query.filter_by(admission_no=data['admission_no']).one()

    def review(self,ids,action='approve',**changes):
        data=dict(_csrf=self.csrf,action=action,ids=[str(id) for id in ids]);data.update(changes)
        return self.c.post('/workspace/approve-students',data=data)

    def test_gets_are_read_only_and_no_limit_preserves_direct_admission(self):
        for path in ['/workspace/admission-capacity','/workspace/admission-approvals','/workspace/dashboard']:
            self.assertEqual(self.c.get(path).status_code,200)
        self.assertEqual(self.m['capacity'].query.count(),0);self.assertEqual(self.m['gate'].query.count(),0)
        self.assertEqual(self.add().status,'Active');self.assertEqual(self.add().status,'Active')

    def test_full_and_zero_seats_queue_new_pupils_across_sections(self):
        self.assertEqual(self.limit().status_code,302)
        first=self.add();second=self.add(section='B')
        self.assertEqual(first.status,'Active');self.assertEqual(second.status,'Waiting')
        detail=self.rm['student'].query.filter_by(student_id=second.id).one();self.assertEqual(detail.data['status'],'Waiting')
        self.assertEqual(self.limit('0',class_name='Other Class').status_code,302)
        self.assertEqual(self.add(class_name='Other Class').status,'Waiting')

    def test_scope_is_campus_class_session_and_not_section(self):
        self.limit('0')
        self.assertEqual(self.add().status,'Waiting')
        for changes in [dict(campus='Other Campus'),dict(class_name='Other Class'),dict(academic_session='2027-28')]:
            self.assertEqual(self.add(**changes).status,'Active')

    def test_batch_approval_never_partially_exceeds_seats(self):
        self.limit('2');self.add();a=self.add(status='Waiting');b=self.add(status='Waiting')
        self.assertEqual(self.review([a.id,b.id]).status_code,422)
        self.assertEqual([a.status,b.status],['Waiting','Waiting']);self.assertEqual(Student.query.filter_by(status='Active').count(),1)
        self.assertEqual(self.review([a.id]).status_code,302)
        self.assertEqual(self.review([b.id]).status_code,422)
        self.assertEqual(self.limit('3').status_code,302)
        self.assertEqual(b.status,'Waiting')  # Limit changes never auto-approve.
        self.assertEqual(self.review([b.id]).status_code,302)
        self.assertEqual(Student.query.filter_by(status='Active').count(),3)

    def test_refusal_has_explicit_status_tabs_and_matching_profile(self):
        waiting=self.add(status='Waiting');self.add(status='Inactive')
        self.assertEqual(self.review([waiting.id],'reject').status_code,302)
        self.assertEqual(waiting.status,'Refused')
        self.assertEqual(self.rm['student'].query.filter_by(student_id=waiting.id).one().data['status'],'Refused')
        page=self.c.get('/workspace/admission-approvals?tab=Refused')
        self.assertIn(waiting.name.encode(),page.data);self.assertIn(b'Refused (1)',page.data)
        self.assertIn(b'Admission refused',self.c.get(f'/records/student/{waiting.id}').data)
        for tab in ['Waiting','Allowed','All']:self.assertEqual(self.c.get('/workspace/admission-approvals?tab='+tab).status_code,200)

    def test_stale_unknown_invalid_actions_and_filter_mismatch_are_atomic(self):
        waiting=self.add(status='Waiting');enrolled=self.add()
        for ids,action,changes in [([waiting.id,enrolled.id],'approve',{}),([waiting.id,99999],'approve',{}),([waiting.id],'unknown',{}),([waiting.id],'approve',{'campus':'Other Campus'})]:
            self.assertEqual(self.review(ids,action,**changes).status_code,422)
            self.assertEqual(waiting.status,'Waiting')
        self.assertEqual(self.c.post('/workspace/approve-students',data={'ids':str(waiting.id),'action':'approve'}).status_code,400)

    def test_capacity_csrf_validation_version_and_occupied_minimum(self):
        self.assertEqual(self.c.post('/workspace/admission-capacity',data={'seats':'1'}).status_code,400)
        for changes in [dict(seats='-1'),dict(seats='NaN'),dict(campus='Unknown')]:
            self.assertEqual(self.limit(**changes).status_code,422)
        self.assertEqual(self.limit('2').status_code,302);self.add()
        self.assertEqual(self.limit('0').status_code,422)
        self.assertEqual(self.limit('3',version='0').status_code,422)
        self.assertEqual(self.limit('',unlimited='on').status_code,302)
        self.assertIsNone(self.m['capacity'].query.one().seats)
        self.assertEqual(self.add().status,'Active')

    def test_enrolled_profile_edit_is_allowed_but_full_transfer_is_rolled_back(self):
        self.limit('1');student=self.add();self.limit('0',class_name='Other Class')
        detail=self.rm['student'].query.filter_by(student_id=student.id).one()
        data=self.form(name='Renamed fictional pupil',admission_no=student.admission_no,family_mode='existing',family_id=str(detail.family_id))
        self.assertEqual(self.c.post(f'/records/student/{student.id}/edit',data=data).status_code,302)
        self.assertEqual(student.status,'Active')
        data.update(class_name='Other Class',name='Must not be saved')
        self.assertEqual(self.c.post(f'/records/student/{student.id}/edit',data=data).status_code,422)
        self.assertEqual((student.name,student.class_name,student.status),('Renamed fictional pupil','Demo Class','Active'))

    def test_inactive_activation_obeys_limit_and_leaving_frees_a_seat(self):
        self.limit('1');active=self.add();inactive=self.add(status='Inactive')
        detail=self.rm['student'].query.filter_by(student_id=inactive.id).one()
        data=self.form(admission_no=inactive.admission_no,family_mode='existing',family_id=str(detail.family_id))
        self.assertEqual(self.c.post(f'/records/student/{inactive.id}/edit',data=data).status_code,302)
        self.assertEqual(inactive.status,'Waiting')
        detail=self.rm['student'].query.filter_by(student_id=active.id).one()
        data=self.form(admission_no=active.admission_no,status='Withdrawn',family_mode='existing',family_id=str(detail.family_id))
        self.assertEqual(self.c.post(f'/records/student/{active.id}/edit',data=data).status_code,302)
        self.assertEqual(self.review([inactive.id]).status_code,302)

    def test_search_paging_dashboard_and_limits_do_not_create_records(self):
        self.limit('4');student=self.add(status='Waiting')
        page=self.c.get('/workspace/admission-approvals?tab=Waiting&q='+student.admission_no)
        self.assertIn(student.name.encode(),page.data)
        for suffix in ['tab=Unknown','size=7','page=bad']:
            self.assertEqual(self.c.get('/workspace/admission-approvals?'+suffix).status_code,422)
        self.assertIn(b'Admission Capacity',self.c.get('/workspace/dashboard').data)
        summary=app.extensions['admission_capacity']['rows']()[0]
        self.assertEqual((summary['occupied'],summary['available']),(0,4))

    def test_two_sqlite_connections_cannot_take_the_last_seat(self):
        with tempfile.TemporaryDirectory() as directory:
            engine=create_engine('sqlite:///'+str(Path(directory)/'concurrent.db'),connect_args={'timeout':15})
            db.metadata.create_all(engine,tables=app.extensions['identity_helpers']['workspace_tables']())
            with engine.begin() as connection:
                connection.execute(self.m['capacity'].__table__.insert().values(campus='Demo Campus',class_name='Demo Class',academic_session='2026-27',seats=1,version=1))
            start=threading.Barrier(2);results=[];errors=[]
            def worker(number):
                try:
                    with app.test_request_context('/'):
                        g.institute_engine=engine
                        start.wait(timeout=5)
                        data=dict(campus='Demo Campus',class_name='Demo Class',academic_session='2026-27',status='Active')
                        app.extensions['admission_capacity']['guard'](data)
                        pupil=Student(admission_no='CONCURRENT-'+str(number),name='Fictional concurrent pupil',class_name='Demo Class',status=data['status'])
                        db.session.add(pupil);db.session.flush()
                        db.session.add(self.rm['student'](student_id=pupil.id,data=data));db.session.commit();results.append(pupil.status)
                        db.session.remove()
                except Exception as error:errors.append(str(error))
            threads=[threading.Thread(target=worker,args=(n,)) for n in (1,2)]
            for thread in threads:thread.start()
            for thread in threads:thread.join(timeout=20)
            self.assertFalse(any(t.is_alive() for t in threads));self.assertFalse(errors,errors)
            self.assertEqual(sorted(results),['Active','Waiting'])
            engine.dispose()


if __name__=='__main__':unittest.main()
