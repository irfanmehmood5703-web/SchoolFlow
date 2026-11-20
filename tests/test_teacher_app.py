"""Teacher isolation, class writes and own HRM request acceptance."""
import re,unittest
from datetime import timedelta
from tests import test_staff_access as fixture
from school_clock import school_today
from flask import g
app,db,Student=fixture.app,fixture.db,fixture.Student
class TeacherAppTests(unittest.TestCase):
    setUp=fixture.StaffAccessTests.setUp
    tearDown=fixture.StaffAccessTests.tearDown
    csrf=fixture.StaffAccessTests.csrf
    token=fixture.StaffAccessTests.token
    login=fixture.StaffAccessTests.login
    tenant=fixture.StaffAccessTests.tenant
    password=fixture.StaffAccessTests.password
    def seed(self):
        def make():
            staff=db.session.get(self.Staff,self.sid);codes=('attendance.view','attendance.update','attendance.own','payroll.self','hrm.self_requests','student_extras.view','student_extras.create','student_extras.update','exam.view','exam.update','exam.create','fees.view')
            staff.data={**staff.data,'permissions':{c:['Campus A'] for c in codes}}
            for category,value,cls in [('class','One',''),('section','A','One'),('subject','Math','One')]:db.session.add(self.rm['settings'](category=category,value=value,class_name=cls))
            for d in self.rm['student'].query.all():d.data={**d.data,'section':'A','subjects':['Math']}
            row=self.ops['workflow'](kind='teacher-classes',status='Active',data=dict(employee_id=str(staff.employee_id),campus='Campus A',class_name='One',section='A',subject='Math'));db.session.add(row);db.session.flush();self.cid=row.id
            pupil=Student.query.filter_by(name='Pupil Campus A').one();self.pupil=pupil.id
            db.session.add(self.ops['daily'](kind='student',person_id=pupil.id,day=school_today(),status='Present',time_in='08:04',time_out='13:30',lectures=3))
        self.tenant(make);self.login()
    def review(self,path):
        page=self.c.get(path);self.assertEqual(page.status_code,200,page.data[:500]);return re.search(rb'name="review" value="([^"]+)"',page.data).group(1).decode()
    def test_all_pages_render_and_other_cohorts_are_denied(self):
        self.seed()
        for path in ('','/classes','/profile','/my-attendance','/my-salary','/requests/advance','/requests/leave','/diaries','/settings','/reminders',f'/classes/{self.cid}/attendance',f'/classes/{self.cid}/diary',f'/classes/{self.cid}/materials',f'/classes/{self.cid}/exams',f'/classes/{self.cid}/exams/new',f'/classes/{self.cid}/absentees',f'/classes/{self.cid}/fee-defaulters'):
            r=self.c.get('/teacher-app'+path);self.assertEqual(r.status_code,200,(path,r.data[:500]));self.assertNotIn(b'Pupil Campus B',r.data)
        self.assertEqual(self.c.get('/teacher-app/classes/999/attendance').status_code,403)
    def test_only_changed_attendance_is_written_and_times_preserved(self):
        self.seed();path=f'/teacher-app/classes/{self.cid}/attendance';review=self.review(path)
        response=self.c.post(path,data={'_csrf':self.token(),'review':review,'day':str(school_today()),f'status_{self.pupil}':'Absent'})
        self.assertEqual(response.status_code,302,response.data)
        def check():
            row=self.ops['daily'].query.filter_by(kind='student',person_id=self.pupil).one();self.assertEqual((row.status,row.time_in,row.time_out,row.lectures),('Absent','08:04','13:30',3))
        self.tenant(check)
        self.assertEqual(self.c.post(path,data={'_csrf':self.token(),'review':review,'day':str(school_today()),f'status_{self.pupil}':'Present'}).status_code,422)
    def test_self_request_cannot_choose_employee_or_approve(self):
        self.seed();path='/teacher-app/requests/advance';review=self.review(path)
        response=self.c.post(path,data={'_csrf':self.token(),'review':review,'employee_id':'999','status':'Approved','amount':'1000','return_amount':'100','date':str(school_today()),'reason':'Fictional test only'})
        self.assertEqual(response.status_code,302,response.data)
        def check():
            row=self.ops['workflow'].query.filter_by(kind='advances').one();self.assertEqual(row.status,'Pending');self.assertEqual(row.data['employee_id'],str(db.session.get(self.Staff,self.sid).employee_id));self.assertEqual(self.ops['salary'].query.count(),0)
        self.tenant(check)
    def test_leave_validation_csrf_and_history(self):
        self.seed();path='/teacher-app/requests/leave';token=self.review(path);data={'_csrf':self.token(),'review':token,'type':'Leave','from_date':str(school_today()),'to_date':str(school_today()-timedelta(days=1)),'reason':'Fictional'}
        self.assertEqual(self.c.post(path,data=data).status_code,422)
        data['to_date']=data['from_date'];self.assertEqual(self.c.post(path,data=data).status_code,302)
        self.assertIn(b'Fictional',self.c.get(path).data)
        self.assertEqual(self.c.post(path,data={}).status_code,400)
    def test_old_diary_is_read_only_and_salary_is_self_only(self):
        self.seed();path=f'/teacher-app/classes/{self.cid}/diary'
        self.assertEqual(self.c.post(path,data={'_csrf':self.token(),'starts':str(school_today()-timedelta(days=1))}).status_code,422)
        def revoke():
            row=db.session.get(self.Staff,self.sid);row.data={**row.data,'permissions':{'attendance.view':['Campus A']}}
        self.tenant(revoke);self.login();self.assertEqual(self.c.get('/teacher-app/my-salary').status_code,403);self.assertEqual(self.c.get('/teacher-app/requests/advance').status_code,403)
    def test_marks_reject_nonfinite_and_foreign_students(self):
        self.seed()
        def make():
            row=self.ops['workflow'](kind='awards',status='Active',data=dict(name='Fictional exam',campus='Campus A',class_name='One',section='A',papers=[dict(subject='Math',grading='Marks',total=37,date=str(school_today()),teacher='1')]))
            db.session.add(row);db.session.flush();return row.id
        aid=self.tenant(make);path=f'/teacher-app/classes/{self.cid}/marks/{aid}/0';token=self.review(path);data={'_csrf':self.token(),'review':token,f'mark_{self.pupil}':'NaN'}
        self.assertEqual(self.c.post(path,data=data).status_code,422)
        data[f'mark_{self.pupil}']='35';data['mark_999']='12';self.assertEqual(self.c.post(path,data=data).status_code,403)
        data.pop('mark_999');self.assertEqual(self.c.post(path,data=data).status_code,302)
        self.tenant(lambda:self.assertEqual(self.ops['score'].query.one().obtained,35))
    def test_material_publication_and_files_stay_assigned(self):
        self.seed();path=f'/teacher-app/classes/{self.cid}/materials';page=self.c.get(path);token=re.search(rb'name="token" value="([^"]+)"',page.data).group(1).decode()
        data={'_csrf':self.token(),'action':'create','token':token,'kind':'notes','title':'Fictional study','body':'<script>evil()</script><b>Read</b>','starts':str(school_today()),'ends':str(school_today()+timedelta(days=3)),'published':'1'}
        self.assertEqual(self.c.post(path,data=data).status_code,302)
        self.assertEqual(self.c.post(path,data=data).status_code,302)
        def check():
            rows=app.extensions['parent_study_models']['item'].query.all();self.assertEqual(len(rows),1);self.assertEqual((rows[0].campus,rows[0].section,rows[0].subject,rows[0].published),('Campus A','A','Math',True));self.assertNotIn('<script>',rows[0].body)
        self.tenant(check)
    def test_student_leave_scope_and_review(self):
        self.seed()
        def make():
            row=db.session.get(self.Staff,self.sid);row.data={**row.data,'permissions':{**row.data['permissions'],'teacher.leave_view':['Campus A'],'teacher.leave_approve':['Campus A']}}
            L=app.extensions['general_leave_model'];school=db.session.get(self.M['institute'],self.school);db.session.add(L(institute_scope=school.storage_key,student_id=self.pupil,from_date=school_today(),to_date=school_today(),leave_type='Leave',reason='Own leave'));db.session.add(L(institute_scope=school.storage_key,student_id=2,from_date=school_today(),to_date=school_today(),leave_type='Leave',reason='Foreign leave'))
        self.tenant(make);self.login();page=self.c.get('/teacher-app/student-leaves');self.assertEqual(page.status_code,200);self.assertNotIn(b'Foreign leave',page.data);token=re.search(rb'name="review" value="([^"]+)"',page.data).group(1).decode()
        r=self.c.post('/teacher-app/student-leaves',data={'_csrf':self.token(),'review':token,'id':'1','status':'Approved','comment':'Fictional approval'});self.assertEqual(r.status_code,302,r.data)
        self.tenant(lambda:self.assertEqual(db.session.get(app.extensions['general_leave_model'],2).status,'Pending'))
    def test_parent_notice_schedule_and_revoked_assignment(self):
        self.seed();path='/teacher-app/reminders';token=self.review(path);r=self.c.post(path,data={'_csrf':self.token(),'review':token,'action':'create','audience':'parents','cohort':self.cid,'title':'Scheduled fiction','note':'Fictional homework notice','due':str(school_today()-timedelta(days=1))+'T08:00','repeat':'none'})
        self.assertEqual(r.status_code,302,r.data)
        def check():
            pupil=db.session.get(Student,self.pupil);details=db.session.get(self.rm['student'],1).data;values=app.extensions['teacher_app_helpers']['parent_reminders'](pupil,details);self.assertEqual(len(values),1);self.assertEqual(values[0]['title'],'Scheduled fiction');row=db.session.get(self.ops['workflow'],self.cid);row.status='Inactive';db.session.flush();self.assertEqual(app.extensions['teacher_app_helpers']['parent_reminders'](pupil,details),[])
        self.tenant(check)
    def test_qr_is_one_use_and_reissuing_or_revoking_invalidates_it(self):
        self.seed();self.login('owner@example.invalid');version=self.tenant(lambda:db.session.get(self.Staff,self.sid).version)
        page=self.c.post(f'/workspace/core/users/{self.sid}/teacher-qr',data={'_csrf':self.token(),'version':str(version)});self.assertEqual(page.status_code,200,page.data[:500]);token=re.search(rb'/teacher-sign-in/STAFF-TEST#([A-Za-z0-9_-]{43})',page.data).group(1).decode();guest=app.test_client();guest.get('/teacher-sign-in/STAFF-TEST')
        with guest.session_transaction() as session:csrf=session['record_csrf']
        self.assertEqual(guest.post('/teacher-sign-in/STAFF-TEST',data={'_csrf':csrf,'credential':token}).status_code,302);self.assertEqual(guest.get('/teacher-app').status_code,200)
        with guest.session_transaction() as session:csrf=session['record_csrf']
        self.assertEqual(guest.post('/teacher-sign-in/STAFF-TEST',data={'_csrf':csrf,'credential':token}).status_code,403)
