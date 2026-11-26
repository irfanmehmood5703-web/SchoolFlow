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
    def teacher_entry(self):
        school=db.session.get(self.M['institute'],self.school)
        return '/mobile/teacher?school='+school.code+'&scope='+school.storage_key
    def app_login(self,login='teacher.one',password=None,client=None):
        c=client or self.c
        with c.session_transaction() as session:token=session['record_csrf']
        return c.post('/auth/login',data={'_csrf':token,'email':login,'password':password if password is not None else self.password})
    def test_public_mobile_entry_documents_are_marked(self):
        for path in ('/','/mobile/teacher','/mobile/parents','/mobile/owner'):
            page=app.test_client().get(path)
            self.assertEqual(page.status_code,200,path)
            self.assertIn(b'<meta name="schoolflow-document" content="1">',page.data,path)
    def test_teacher_login_generic_school_selection_and_existing_session(self):
        self.assertEqual(self.c.get('/mobile/teacher').status_code,200)
        self.assertEqual(self.c.post('/mobile/teacher',data={'code':'STAFF-TEST'}).status_code,400)
        r=self.c.post('/mobile/teacher',data={'_csrf':self.token(),'code':'NOT-A-SCHOOL'})
        self.assertIn(b'Institute code not recognised',r.data)
        r=self.c.post('/mobile/teacher',data={'_csrf':self.token(),'code':'staff-test'})
        self.assertTrue(r.location.endswith('/auth/login'))
        page=self.c.get(r.location)
        self.assertIn(b'Fictional school',page.data)
        self.assertIn(b'Use the active Teacher account',page.data)
        self.assertIn(b'class="teacher-auth-card"',page.data)
        self.assertIn(b'<meta name="schoolflow-document" content="1">',page.data)
        self.assertEqual(page.data.count(b'<h1>Fictional school</h1>'),1)
        self.assertNotIn(b'class="public-header"',page.data)
        self.assertIn(b'data-password-icon',page.data)
        self.assertIn(b'aria-label="Show password"',page.data)
        self.assertIn(b'teacher-auth.css',page.data)
        self.assertIn(b'teacher password',self.c.get('/auth/forgot-password').data)
        for login in ('teacher.one','teacher@example.invalid'):
            r=self.app_login(login)
            self.assertTrue(r.location.endswith('/teacher-app'))
            dashboard=self.c.get(r.location);self.assertEqual(dashboard.status_code,200)
            self.assertIn(b'<meta name="schoolflow-document" content="1">',dashboard.data)
            r=self.c.get('/mobile/teacher',follow_redirects=True)
            self.assertEqual(r.request.path,'/teacher-app')
            r=self.c.post('/auth/logout',data={'_csrf':self.token()},follow_redirects=True)
            self.assertEqual(r.request.path,'/auth/login')
            with self.c.session_transaction() as session:self.assertNotIn('staff_id',session)
    def test_teacher_login_wrong_password_owner_non_teacher_and_inactive_rejected(self):
        entry=self.teacher_entry()
        self.assertEqual(self.c.get(entry).status_code,302)
        for username,password in [('teacher.one','wrong'),('owner@example.invalid',self.password)]:
            r=self.app_login(username,password)
            self.assertEqual(r.status_code,200)
            self.assertIn(b'Teacher username, email, mobile or password is incorrect',r.data)
            with self.c.session_transaction() as session:
                self.assertNotIn('staff_id',session);self.assertNotIn('owner_id',session)
        def change():
            r=db.session.get(self.Staff,self.sid)
            r.data={**r.data,'role':'Admin'}
        self.tenant(change)
        self.assertEqual(self.app_login().status_code,200)
        with self.c.session_transaction() as session:self.assertNotIn('staff_id',session)
        # The same authorized account can still sign in on the normal desktop site.
        desktop=app.test_client();desktop.get('/auth/institute')
        with desktop.session_transaction() as session:token=session['record_csrf']
        desktop.post('/auth/institute',data={'_csrf':token,'code':'STAFF-TEST'})
        self.assertTrue(self.app_login(client=desktop).location.endswith('/workspace/dashboard'))
        def inactive():
            r=db.session.get(self.Staff,self.sid);r.data={**r.data,'role':'Teacher'};r.active=False
        self.tenant(inactive)
        self.assertEqual(self.app_login().status_code,200)
        with self.c.session_transaction() as session:self.assertNotIn('staff_id',session)
    def test_teacher_login_phone_and_revoked_session_recovery(self):
        from app import Employee
        def contact():
            r=db.session.get(self.Staff,self.sid)
            r.data={**r.data,'contact':'03001234567'}
        self.tenant(contact)
        self.c.get(self.teacher_entry())
        self.assertTrue(self.app_login('+92 300 1234567').location.endswith('/teacher-app'))
        self.assertEqual(self.c.get('/teacher-app').status_code,200)
        def deactivate():
            staff=db.session.get(self.Staff,self.sid);db.session.get(Employee,staff.employee_id).status='Inactive'
        self.tenant(deactivate)
        r=self.c.get('/teacher-app',follow_redirects=True)
        self.assertEqual(r.request.path,'/auth/login')
        self.assertEqual(self.app_login().status_code,200)
        with self.c.session_transaction() as session:self.assertNotIn('staff_id',session)
    def test_teacher_login_school_binding_and_csrf(self):
        school=db.session.get(self.M['institute'],self.school)
        self.assertEqual(self.c.get('/mobile/teacher?school='+school.code+'&scope='+'0'*32).status_code,403)
        self.c.get(self.teacher_entry())
        self.assertEqual(self.c.post('/auth/login',data={'email':'teacher.one','password':self.password}).status_code,400)
        other=app.extensions['identity_helpers']['provision']('OTHER-SCHOOL','Other school','owner@example.invalid',self.password)
        self.assertEqual(self.c.post('/auth/institute',data={'_csrf':self.token(),'code':other.code}).status_code,403)
        self.assertEqual(self.c.get('/mobile/teacher?school=OTHER-SCHOOL').status_code,403)
        self.assertTrue(self.app_login().location.endswith('/teacher-app'))
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
    def test_home_separates_distinct_classes_from_subject_assignments(self):
        self.seed()
        def assign():
            W=self.ops['workflow'];row=db.session.get(W,self.cid)
            staff=db.session.get(self.Staff,self.sid)
            staff.data={**staff.data,'campuses':['Campus A']}
            row.data={**row.data,'subject':''}
            for cls,subject in [('Three','General Knowledge'),('Three','History'),('Three','History')]:
                db.session.add(W(kind='teacher-classes',status='Active',data={**row.data,'class_name':cls,'subject':subject}))
            db.session.add(W(kind='teacher-classes',status='Active',data={**row.data,'campus':'Campus B','class_name':'Four','subject':'English'}))
            db.session.add(W(kind='teacher-classes',status='Voided',data={**row.data,'class_name':'Five','subject':'Urdu'}))
        self.tenant(assign);self.login()
        page=self.c.get('/teacher-app')
        self.assertEqual(page.status_code,200)
        summary=re.search(rb'<a class="metric teacher-assignment-metric".*?</a>',page.data).group()
        self.assertIn(b'<span>Assigned classes</span><strong>2</strong>',summary)
        self.assertIn(b'1 full class',summary)
        self.assertIn(b'2 subject assignments',summary)
        self.assertIn(b'href="/teacher-app/classes"',summary)
        self.assertNotIn(b'Assigned classes / subjects',page.data)
    def test_active_teacher_without_matrix_gets_only_assigned_class_tools(self):
        self.seed()
        def class_only():
            W=self.ops['workflow'];row=db.session.get(W,self.cid);row.data={**row.data,'subject':''}
            staff=db.session.get(self.Staff,self.sid);staff.data={**staff.data,'campuses':['Campus A'],'permissions':{}}
            db.session.add(W(kind='teacher-classes',status='Active',data={**row.data,'campus':'Campus B'}))
            db.session.add(self.rm['settings'](category='subject',value='English',class_name='One'))
            db.session.add(self.rm['settings'](category='subject',value='Other class subject',class_name='Two'))
        self.tenant(class_only);self.login()
        root=f'/teacher-app/classes/{self.cid}'
        home=self.c.get('/teacher-app')
        self.assertEqual(home.status_code,200)
        self.assertIn(b'Class only',home.data)
        self.assertIn((root+'/attendance').encode(),home.data)
        self.assertIn((root+'/subjects/diary').encode(),home.data)
        self.assertIn((root+'/exams').encode(),home.data)
        self.assertNotIn(b'Campus B',home.data)
        page=self.c.get(root+'/attendance')
        self.assertEqual(page.status_code,200);self.assertIn(b'Pupil Campus A',page.data);self.assertNotIn(b'Pupil Campus B',page.data)
        review=self.review(root+'/attendance')
        self.assertEqual(self.c.post(root+'/attendance',data={'_csrf':self.token(),'review':review,'day':str(school_today()),f'status_{self.pupil}':'Absent'}).status_code,302)
        for feature,route in [('diary','diary'),('materials','materials'),('exam_list','exams')]:
            page=self.c.get(root+'/subjects/'+feature)
            self.assertEqual(page.status_code,200);self.assertIn(b'Math',page.data);self.assertIn(b'English',page.data);self.assertNotIn(b'Other class subject',page.data)
            self.assertEqual(self.c.get(root+'/'+route+'?subject=Math').status_code,200)
            self.assertEqual(self.c.get(root+'/'+route+'?subject=Other+class+subject').status_code,403)
            self.assertEqual(self.c.post(root+'/'+route+'?subject=Unknown',data={'_csrf':self.token()}).status_code,403 if route!='exams' else 405)
        day=str(school_today());path=root+'/diary?subject=Math'
        page=self.c.get(path);token=re.search(rb'name="submission" value="([^"]+)"',page.data).group(1).decode()
        data={'_csrf':self.token(),'submission':token,'subject_slot':'0','subjects':'Math','subject_name_0':'Math','channel':'app','campus':'Campus A','class_name':'One','section':'A','starts':day,'action':'save','classwork_0':'Fictional classwork','homework_0':'Fictional homework'}
        self.assertEqual(self.c.post(path,data={**data,'subject_name_0':'English'}).status_code,403)
        r=self.c.post(path,data=data);self.assertEqual(r.status_code,302);self.assertIn('subject=Math',r.location)
        self.assertIn(b'Fictional homework',self.c.get(path).data)
        self.assertNotIn(b'Fictional homework',self.c.get(root+'/diary?subject=English').data)
        for route in ('/absentees','/fee-defaulters'):
            self.assertEqual(self.c.get(root+route).status_code,200,route)
        for path in ('/teacher-app/diaries','/teacher-app/my-attendance','/teacher-app/my-salary','/teacher-app/requests/leave','/teacher-app/requests/advance','/teacher-app/student-leaves','/teacher-app/meetings','/teacher-app/notifications','/teacher-app/tool/messages','/workspace/conversations'):
            self.assertEqual(self.c.get(path).status_code,200,path)
        for path in ('/workspace/attendance/student','/workspace/core/users','/workspace/finance/ledger','/workspace/conversations/report','/workspace/conversations/settings'):
            self.assertEqual(self.c.get(path).status_code,403,path)
        # Revoking assignment blocks class routes immediately, even with a session.
        self.tenant(lambda:setattr(db.session.get(self.ops['workflow'],self.cid),'status','Voided'))
        self.assertEqual(self.c.get(root+'/attendance').status_code,403)
        self.assertEqual(self.c.get(root+'/diary?subject=Math').status_code,403)
    def test_compact_exam_views_keep_all_subjects_and_saved_marks(self):
        self.seed()
        names=('English','Urdu','Science','Computer','Islamiyat','General Knowledge','Social Studies')
        def make():
            row=db.session.get(self.ops['workflow'],self.cid)
            row.data={**row.data,'subject':''}
            for name in names:
                db.session.add(self.rm['settings'](category='subject',value=name,class_name='One'))
            award=self.ops['workflow'](kind='awards',status='Active',data=dict(name='Fictional compact test',campus='Campus A',class_name='One',section='A',papers=[dict(subject='Math',grading='Marks',total=50,date=str(school_today()))]))
            db.session.add(award);db.session.flush()
            db.session.add(self.ops['score'](award_id=award.id,student_id=self.pupil,paper=0,obtained=35,state=''))
            return award.id
        aid=self.tenant(make);root=f'/teacher-app/classes/{self.cid}'
        page=self.c.get(root+'/subjects/exam_list')
        self.assertEqual(page.status_code,200)
        self.assertIn(b'class="teacher-exam-compact"',page.data)
        self.assertEqual(page.data.count(b'class="button secondary" href="'),8)
        for name in (*names,'Math'):self.assertIn(name.encode(),page.data)
        page=self.c.get(root+'/exams?subject=Math&q=compact')
        self.assertIn(b'name="subject" value="Math"',page.data)
        self.assertIn(b'class="panel exam-search"',page.data)
        path=root+f'/marks/{aid}/0?subject=Math'
        page=self.c.get(path)
        self.assertEqual(page.status_code,200)
        self.assertIn(b'class="panel exam-marks"',page.data)
        self.assertRegex(page.data,rb'name="mark_\d+"[^>]+max="50"[^>]+value="35\.0"')
        self.assertNotIn(b'Pupil Campus B',page.data)
        self.assertNotIn(b'class="teacher-exam-compact"',self.c.get(root+'/attendance').data)
        self.assertEqual(self.c.post(path,data={'_csrf':self.token(),'review':self.review(path),f'mark_{self.pupil}':'42',f'state_{self.pupil}':''}).status_code,302)
        self.tenant(lambda:self.assertEqual(self.ops['score'].query.one().obtained,42))
    def test_weekly_timetable_class_only_periods_and_access(self):
        self.seed()
        root='/workspace/core/automatic-reports';path=root+'/periods'
        def setup():
            W=self.ops['workflow'];row=db.session.get(W,self.cid)
            row.data={**row.data,'subject':''}
            staff=db.session.get(self.Staff,self.sid)
            staff.data={**staff.data,'permissions':{},'campuses':['Campus A']}
            db.session.add(self.rm['settings'](category='subject',value='Urdu',class_name='One'))
            db.session.add(self.rm['settings'](category='subject',value='Forbidden subject',class_name='Two'))
            other=W(kind='teacher-classes',status='Active',data={**row.data,'campus':'Campus B','subject':'Math'})
            db.session.add(other);db.session.flush()
            db.session.add(W(kind='automatic-period-reminder',status='Active',data=dict(assignment_id=other.id,assignment=dict(other.data),weekday=1,time='09:31',lead=5)))
        self.tenant(setup)
        self.login('owner@example.invalid')
        page=self.c.get(root)
        self.assertEqual(page.status_code,200)
        self.assertIn(f'value="{self.cid}:Urdu"'.encode(),page.data)
        self.assertNotIn(f'value="{self.cid}:Forbidden subject"'.encode(),page.data)
        data={'_csrf':self.token(),'action':'add','assignment_id':f'{self.cid}:Urdu','weekday':'0','time':'09:00','lead':'5'}
        self.assertEqual(self.c.post(path,data={**data,'assignment_id':f'{self.cid}:Forbidden subject'}).status_code,422)
        self.assertEqual(self.c.post(path,data=data).status_code,302)
        self.assertEqual(self.c.post(path,data=data).status_code,409)
        self.assertEqual(self.c.post(path,data={**data,'assignment_id':str(self.cid),'weekday':'5','time':'11:00'}).status_code,302)
        self.assertEqual(self.c.get('/teacher-app/timetable').status_code,403)
        self.login()
        home=self.c.get('/teacher-app');self.assertIn(b'Class Timetable',home.data)
        page=self.c.get('/teacher-app/timetable')
        self.assertEqual(page.status_code,200)
        for expected in (b'Urdu',b'Monday',b'9:00 AM',b'Saturday',b'Class period',b'11:00 AM',b'2 periods'):self.assertIn(expected,page.data)
        for forbidden in (b'Campus B',b'09:31',b'Forbidden subject'):self.assertNotIn(forbidden,page.data)
        self.assertEqual(self.c.post(path,data={**data,'_csrf':self.token()}).status_code,403)
        self.tenant(lambda:setattr(db.session.get(self.ops['workflow'],self.cid),'status','Voided'))
        page=self.c.get('/teacher-app/timetable')
        self.assertIn(b'No timetable scheduled yet',page.data)
        self.assertNotIn(b'9:00 AM',page.data)
    def test_teacher_full_class_and_lectures_coexist(self):
        from datetime import datetime
        from school_clock import SCHOOL_TIMEZONE
        self.seed();root='/workspace/core/automatic-reports';path=root+'/periods'
        def setup():
            W=self.ops['workflow'];row=db.session.get(W,self.cid)
            row.data={**row.data,'subject':''}
            staff=db.session.get(self.Staff,self.sid)
            staff.data={**staff.data,'permissions':{},'campuses':['Campus A']}
            lecture=W(kind='teacher-classes',status='Active',data={**row.data,'class_name':'Two','section':'B','subject':'English'})
            other=W(kind='teacher-classes',status='Active',data={**row.data,'class_name':'Three','section':'A'})
            db.session.add_all([lecture,other]);db.session.flush()
            return lecture.id,other.id
        lecture,other=self.tenant(setup)
        self.login('owner@example.invalid')
        page=self.c.get(root)
        self.assertIn(b'Full Class (all day)',page.data)
        self.assertIn(b'Lecture / Period',page.data)
        data={'_csrf':self.token(),'action':'add_full_class','assignment_id':str(self.cid),'weekdays':['0','1','2','3','4']}
        self.assertEqual(self.c.post(path,data={**data,'weekdays':[]}).status_code,422)
        self.assertEqual(self.c.post(path,data={**data,'weekdays':['0','99']}).status_code,422)
        self.assertEqual(self.c.post(path,data={**data,'assignment_id':str(lecture)}).status_code,422)
        self.assertEqual(self.c.post(path,data=data).status_code,302)
        self.assertEqual(self.c.post(path,data=data).status_code,302)
        self.assertEqual(self.c.post(path,data={**data,'assignment_id':str(other),'weekdays':['0','5']}).status_code,409)
        lecture_data={'_csrf':self.token(),'action':'add','assignment_id':str(lecture),'weekday':'0','time':'10:00','lead':'5'}
        self.assertEqual(self.c.post(path,data=lecture_data).status_code,302)
        self.assertEqual(self.c.post(path,data=lecture_data).status_code,409)
        self.assertEqual(self.c.post(path,data={**lecture_data,'assignment_id':f'{self.cid}:Math','time':'09:00'}).status_code,302)
        def check():
            W=self.ops['workflow'];rows=W.query.filter_by(kind='automatic-period-reminder',status='Active').all()
            self.assertEqual(len(rows),7)
            self.assertEqual(sum(r.data.get('mode')=='full-class' for r in rows),5)
            cohorts=[db.session.get(W,cid) for cid in (self.cid,lecture)]
            helper=app.extensions['automatic_report_helpers']
            monday=[p for p in helper['teacher_timetable'](cohorts) if p['weekday']==0]
            self.assertEqual([(p['mode'],p['time'],p['subject']) for p in monday],[('full-class','All day','Full Class'),('lecture','09:00','Math'),('lecture','10:00','English')])
            upcoming=helper['teacher_periods'](cohorts,datetime(2026,11,23,8,56,tzinfo=SCHOOL_TIMEZONE))
            self.assertEqual([p['subject'] for p in upcoming],['Math','English'])
            self.assertTrue(upcoming[0]['due'])
            self.assertFalse(upcoming[1]['due'])
        self.tenant(check)
        self.login()
        page=self.c.get('/teacher-app/timetable')
        self.assertEqual(page.status_code,200)
        for expected in (b'5 full-class days',b'2 lectures',b'All day',b'Class teacher',b'Two',b'English',b'Math'):self.assertIn(expected,page.data)
        self.assertEqual(page.data.count(b'timetable-full-class'),5)
        self.assertEqual(self.c.post(path,data={**data,'_csrf':self.token()}).status_code,403)
        self.tenant(lambda:setattr(db.session.get(self.ops['workflow'],self.cid),'status','Voided'))
        page=self.c.get('/teacher-app/timetable')
        self.assertNotIn(b'timetable-full-class',page.data)
        self.assertIn(b'English',page.data)
        self.assertNotIn(b'9:00 AM',page.data)
    def test_background_lecture_feed_dated_scope_and_sync(self):
        from datetime import datetime
        from unittest.mock import patch
        from types import SimpleNamespace
        from school_clock import SCHOOL_TIMEZONE
        self.seed()
        self.login('owner@example.invalid')
        path='/workspace/core/automatic-reports/periods'
        data={'_csrf':self.token(),'action':'add','assignment_id':str(self.cid),'time':'10:30','lead':'5'}
        for day in ('0','1'):
            self.assertEqual(self.c.post(path,data={**data,'weekday':day}).status_code,302)
        self.login()
        feed_path='/teacher-app/notification-feed'
        now=datetime(2026,11,23,10,20,tzinfo=SCHOOL_TIMEZONE)
        holidays=app.extensions['holiday_calendar_helpers']
        with patch('automatic_reports.datetime') as clock, patch('teacher_app.school_today',return_value=now.date()), patch.dict(holidays,{'rows':lambda:[]}):
            clock.now.return_value=now
            response=self.c.get(feed_path)
            self.assertEqual(response.status_code,200)
            future=response.get_json()
            alerts=future['lecture_alerts']
            self.assertEqual(len(alerts),2)
            self.assertEqual(alerts[0]['due_at'],int(now.replace(minute=25).timestamp()*1000))
            self.assertEqual(alerts[0]['starts_at'],int(now.replace(minute=30).timestamp()*1000))
            self.assertNotEqual(alerts[0]['id'],alerts[1]['id'])
            self.assertNotIn(alerts[0]['id'],[e['id'] for e in future['events']])
            clock.now.return_value=now.replace(minute=25)
            due=self.c.get(feed_path).get_json()
            self.assertIn(alerts[0]['id'],[e['id'] for e in due['events']])
            self.assertEqual(due['lecture_alerts'][0]['id'],alerts[0]['id'])
            holiday=SimpleNamespace(scope='Campus A',data={'date':'2026-11-24','repeats':False})
            with patch.dict(holidays,{'rows':lambda:[holiday]}):
                self.assertEqual(len(self.c.get(feed_path).get_json()['lecture_alerts']),1)
            self.tenant(lambda:setattr(db.session.get(self.ops['workflow'],self.cid),'status','Voided'))
            self.assertEqual(self.c.get(feed_path).get_json()['lecture_alerts'],[])
        self.assertNotEqual(app.test_client().get(feed_path).status_code,200)
    def test_weekly_lecture_multiple_days_preserve_full_class_and_reject_conflicts(self):
        self.seed();path='/workspace/core/automatic-reports/periods'
        def setup():
            W=self.ops['workflow'];row=db.session.get(W,self.cid);row.data={**row.data,'subject':''}
            other=W(kind='teacher-classes',status='Active',data={**row.data,'class_name':'Two','subject':'English'})
            db.session.add(other);db.session.flush();return other.id
        other=self.tenant(setup);self.login('owner@example.invalid')
        page=self.c.get('/workspace/core/automatic-reports')
        self.assertEqual(page.status_code,200)
        self.assertIn(b'Teaching days (weekly)',page.data)
        self.assertEqual(page.data.count(b'name="weekdays"'),14)
        csrf=self.token()
        def post(**fields):return self.c.post(path,data={'_csrf':csrf,**fields})
        self.assertEqual(post(action='add_full_class',assignment_id=str(self.cid),weekdays=['0','1','2','3','4']).status_code,302)
        # Existing single-day lecture remains compatible with the weekly form.
        data=dict(action='add',assignment_id=str(other),time='10:00',lead='5')
        self.assertEqual(post(**data,weekday='0').status_code,302)
        self.assertEqual(post(**data,weekday='0').status_code,409)
        self.assertEqual(post(**data,weekdays=[]).status_code,422)
        self.assertEqual(post(**data,weekdays=['0','7']).status_code,422)
        self.assertEqual(post(**data,weekdays=['0','1','2','3','4']).status_code,302)
        self.assertEqual(post(**data,weekdays=['0','1','2','3','4']).status_code,302)
        # A conflict on Tuesday means Saturday is not partially inserted.
        self.assertEqual(post(action='add',assignment_id=f'{self.cid}:Math',time='10:00',lead='5',weekdays=['1','5']).status_code,409)
        def check():
            W=self.ops['workflow'];records=W.query.filter_by(kind='automatic-period-reminder',status='Active').all()
            self.assertEqual(len(records),10)
            self.assertEqual(sorted(r.data['weekday'] for r in records if r.data.get('mode')=='lecture'),list(range(5)))
        self.tenant(check);self.login()
        page=self.c.get('/teacher-app/timetable')
        self.assertEqual(page.status_code,200)
        self.assertIn(b'5 full-class days',page.data)
        self.assertIn(b'5 lectures',page.data)
        self.assertEqual(page.data.count(b'class="timetable-time">10:00 AM'),5)
        self.assertEqual(self.c.post(path,data={'_csrf':self.token(),**data,'weekdays':['5']}).status_code,403)
    def test_multiple_subject_lectures_saved_atomically_with_individual_times(self):
        self.seed();path='/workspace/core/automatic-reports/periods'
        def setup():
            W=self.ops['workflow'];row=db.session.get(W,self.cid);row.data={**row.data,'subject':''}
            for subject in ('Urdu','Computer'):
                db.session.add(self.rm['settings'](category='subject',value=subject,class_name='One'))
            other=W(kind='teacher-classes',status='Active',data={**row.data,'class_name':'Two','subject':'English'})
            db.session.add(other);db.session.flush();return other.id
        other=self.tenant(setup);self.login('owner@example.invalid')
        page=self.c.get('/workspace/core/automatic-reports')
        self.assertEqual(page.status_code,200)
        self.assertIn(b'data-add-lecture',page.data)
        self.assertIn(b'automatic-reports.js',page.data)
        csrf=self.token()
        def post(**fields):return self.c.post(path,data={'_csrf':csrf,**fields})
        self.assertEqual(post(action='add_full_class',assignment_id=str(self.cid),weekdays=['0','1']).status_code,302)
        data=dict(action='add',assignment_id=[f'{self.cid}:Math',f'{self.cid}:Urdu',str(other)],time=['09:00','10:00','11:00'],lead='5',weekdays=['0','1','2'])
        self.assertEqual(post(**{**data,'time':['09:00','09:00','11:00']}).status_code,409)
        self.assertEqual(post(**{**data,'time':['09:00','10:00']}).status_code,422)
        self.assertEqual(post(**{**data,'assignment_id':[f'{self.cid}:Math',f'{self.cid}:Unauthorized',str(other)]}).status_code,422)
        self.tenant(lambda:self.assertEqual(self.ops['workflow'].query.filter_by(kind='automatic-period-reminder',status='Active').count(),2))
        self.assertEqual(post(**data).status_code,302)
        self.assertEqual(post(**data).status_code,302)
        # Conflicting batch cannot insert even the otherwise-free third lecture.
        self.assertEqual(post(**{**data,'time':['08:00','09:00','12:00']}).status_code,409)
        def check():
            W=self.ops['workflow'];records=W.query.filter_by(kind='automatic-period-reminder',status='Active').all()
            self.assertEqual(len(records),11)
            tt=app.extensions['automatic_report_helpers']['teacher_timetable']([db.session.get(W,self.cid),db.session.get(W,other)])
            monday=[(r['subject'],r['time']) for r in tt if r['weekday']==0]
            self.assertEqual(monday,[('Full Class','All day'),('Math','09:00'),('Urdu','10:00'),('English','11:00')])
        self.tenant(check);self.login()
        page=self.c.get('/teacher-app/timetable')
        self.assertEqual(page.status_code,200)
        self.assertIn(b'2 full-class days',page.data);self.assertIn(b'9 lectures',page.data)
        for subject in (b'Math',b'Urdu',b'English'):self.assertEqual(page.data.count(b'<strong>'+subject+b'</strong>'),3)
    def test_teacher_period_clock_display_uses_12_hour_time(self):
        from unittest.mock import patch
        from datetime import datetime
        from school_clock import SCHOOL_TIMEZONE
        self.seed();path='/workspace/core/automatic-reports/periods'
        self.login('owner@example.invalid')
        for clock in ('00:00','09:00','12:00','13:15','23:30'):
            self.assertEqual(self.c.post(path,data={'_csrf':self.token(),'action':'add','assignment_id':str(self.cid),'time':clock,'lead':'5','weekdays':['0']}).status_code,302)
        self.login()
        page=self.c.get('/teacher-app/timetable')
        self.assertEqual(page.status_code,200)
        for value in (b'12:00 AM',b'9:00 AM',b'12:00 PM',b'1:15 PM',b'11:30 PM'):
            self.assertIn(b'class="timetable-time">'+value,page.data)
        for value in (b'00:00',b'09:00',b'13:15',b'23:30'):
            self.assertNotIn(b'class="timetable-time">'+value,page.data)
        # Home and notification feeds use 12-hour labels, not stored clock keys.
        with patch('automatic_reports.datetime') as clock:
            clock.now.return_value=datetime(2026,11,23,13,11,tzinfo=SCHOOL_TIMEZONE)
            self.assertIn(b'1:15 PM',self.c.get('/teacher-app').data)
            self.assertIn(b'1:15 PM',self.c.get('/teacher-app/notifications').data)
        def check():
            rows=app.extensions['automatic_report_helpers']['teacher_timetable']([db.session.get(self.ops['workflow'],self.cid)])
            self.assertEqual([r['time'] for r in rows],['00:00','09:00','12:00','13:15','23:30'])
            self.assertEqual([r['time_label'] for r in rows],['12:00 AM','9:00 AM','12:00 PM','1:15 PM','11:30 PM'])
        self.tenant(check)

    def test_edit_weekly_timetable_and_single_day_with_conflicts(self):
        self.seed();root='/workspace/core/automatic-reports';path=root+'/periods'
        def setup():
            W=self.ops['workflow'];row=db.session.get(W,self.cid);row.data={**row.data,'subject':''}
            db.session.add(self.rm['settings'](category='subject',value='History',class_name='One'))
        self.tenant(setup);self.login('owner@example.invalid')
        def post(**fields):return self.c.post(path,data={'_csrf':self.token(),**fields})
        self.assertEqual(post(action='add_full_class',assignment_id=str(self.cid),weekdays=['0','1','2','3','4']).status_code,302)
        self.assertEqual(post(action='add',assignment_id=f'{self.cid}:History',time='23:30',lead='5',weekdays=['0','1','2','3','4','5']).status_code,302)
        self.assertEqual(post(action='add',assignment_id=f'{self.cid}:Math',time='10:30',lead='5',weekdays=['0','1','2','3','4','5']).status_code,302)
        def saved():
            return [(r.id,r.status,dict(r.data)) for r in self.ops['workflow'].query.filter_by(kind='automatic-period-reminder').order_by(self.ops['workflow'].id)]
        initial=self.tenant(saved)
        full=next(id for id,status,d in initial if d['mode']=='full-class')
        history=next(id for id,status,d in initial if d.get('subject')=='History')
        edit=f'{path}/{history}/edit'
        page=self.c.get(root);self.assertEqual(page.status_code,200)
        self.assertEqual(page.data.count(b'Edit weekly'),3)
        self.assertIn(b'11:30 PM',page.data);self.assertIn(b'10:30 AM',page.data)
        def review(url):
            page=self.c.get(url);self.assertEqual(page.status_code,200)
            return re.search(rb'name="revision" value="([^"]+)"',page.data).group(1).decode()
        token=review(edit)
        self.assertIn(b'<option value="PM" selected>',self.c.get(edit).data)
        data=dict(_csrf=self.token(),revision=token,weekdays=['0','1','2','3','4'],hour='11',minute='30',meridiem='AM',lead='10')
        self.assertEqual(self.c.post(edit,data={**data,'hour':'10'}).status_code,409)
        self.assertEqual(self.c.post(edit,data={**data,'meridiem':'XX'}).status_code,422)
        self.assertEqual(self.c.post(edit,data={**data,'weekdays':[]}).status_code,422)
        self.assertEqual(self.c.post(edit,data={**data,'revision':'stale'}).status_code,409)
        self.assertEqual(self.c.post(edit,data={**data,'_csrf':'bad'}).status_code,400)
        self.assertEqual(initial,self.tenant(saved))
        self.assertEqual(self.c.post(edit,data=data).status_code,302)
        self.assertEqual(self.c.post(edit,data=data).status_code,409)
        after=self.tenant(saved)
        retained=[(id,d) for id,status,d in after if status=='Active' and d.get('subject')=='History']
        self.assertEqual(len(retained),5)
        self.assertTrue(all(d['time']=='11:30' and d['lead']==10 for _,d in retained))
        self.assertEqual({id for id,d in retained},{id for id,status,d in initial if d.get('subject')=='History' and d['weekday']<5})
        self.assertEqual(sum(status=='Voided' for _,status,_ in after),1)
        # Edit only Wednesday; preserve all remaining weekly history lectures.
        day=next(id for id,d in retained if d['weekday']==2);single=f'{path}/{day}/edit?scope=day'
        self.assertEqual(self.c.post(single,data={**data,'revision':review(single),'weekdays':['2'],'hour':'12','meridiem':'PM'}).status_code,302)
        # Add Saturday to full-class without affecting subject lectures.
        full_url=f'{path}/{full}/edit'
        self.assertEqual(self.c.post(full_url,data={'_csrf':self.token(),'revision':review(full_url),'weekdays':['0','1','2','3','4','5']}).status_code,302)
        def check():
            W=self.ops['workflow'];current=W.query.filter_by(kind='automatic-period-reminder',status='Active').all()
            self.assertEqual(len(current),17)
            self.assertEqual(W.query.filter_by(kind='teacher-classes',status='Active').count(),1)
            self.assertEqual(self.ops['audit'].query.filter_by(action='Edit teacher timetable').count(),3)
            tt=app.extensions['automatic_report_helpers']['teacher_timetable']([db.session.get(W,self.cid)])
            self.assertEqual([p['time'] for p in tt if p['subject']=='History'],['11:30','11:30','12:30','11:30','11:30'])
            self.assertEqual(sum(p['mode']=='full-class' for p in tt),6)
        self.tenant(check)
        self.login()
        page=self.c.get('/teacher-app/timetable');self.assertEqual(page.status_code,200)
        self.assertIn(b'11:30 AM',page.data);self.assertIn(b'12:30 PM',page.data);self.assertNotIn(b'23:30',page.data)
        self.assertEqual(self.c.get(edit).status_code,403)
        self.assertEqual(self.c.post(edit,data={**data,'_csrf':self.token()}).status_code,403)

    def test_direct_cross_class_lecture_assignment_and_timetable(self):
        self.seed();root='/workspace/core/automatic-reports';path=root+'/periods'
        def setup():
            W=self.ops['workflow'];row=db.session.get(W,self.cid);row.data={**row.data,'subject':''}
            staff=db.session.get(self.Staff,self.sid)
            staff.data={**staff.data,'permissions':{},'campuses':['Campus A']}
            for category,value,cls in [('class_name','One',''),('class_name','Two',''),('class_name','Nine',''),('section','B',''),('subject','English','Two'),('subject','Urdu','Nine'),('subject','Computer','Nine')]:
                db.session.add(self.rm['settings'](category=category,value=value,class_name=cls))
            Map=app.extensions['institute_setup_models']['mapping']
            for cls,section in [('One','A'),('Two','B'),('Nine','A')]:
                db.session.add(Map(campus='Campus A',class_name=cls,active=True,data=dict(sections=[section],academic_session='2027')))
            return str(staff.employee_id)
        eid=self.tenant(setup);self.login('owner@example.invalid')
        page=self.c.get(root);self.assertEqual(page.status_code,200)
        for field in (b'lecture_teacher',b'lecture_campus',b'lecture_class',b'lecture_section',b'lecture_subject'):
            self.assertIn(b'name="'+field+b'"',page.data)
        self.assertIn(b'Two',page.data);self.assertIn(b'Nine',page.data)
        csrf=self.token()
        def post(**fields):return self.c.post(path,data={'_csrf':csrf,**fields})
        self.assertEqual(post(action='add_full_class',assignment_id=str(self.cid),weekdays=['0','1','2','3','4']).status_code,302)
        data=dict(action='add',lecture_teacher=[eid,eid],lecture_campus=['Campus A']*2,lecture_class=['Two','Nine'],lecture_section=['B','A'],lecture_subject=['subject:English','subject:Urdu'],time=['09:00','10:00'],lead='5',weekdays=['0','1','2','3','4'])
        for bad in ({'lecture_campus':['Campus A','Campus B']},{'lecture_section':['A','A']},{'lecture_subject':['subject:English','subject:Math']},{'lecture_subject':['class-period','subject:Urdu']},{'lecture_teacher':[eid,'987654']},{'lecture_class':['Two','Unconfigured']},{'time':['09:00','09:00']}):
            self.assertIn(post(**{**data,**bad}).status_code,(409,422))
            self.tenant(lambda:self.assertEqual(self.ops['workflow'].query.filter_by(kind='teacher-classes',status='Active').count(),1))
            self.tenant(lambda:self.assertEqual(self.ops['workflow'].query.filter_by(kind='automatic-period-reminder',status='Active').count(),5))
        self.assertEqual(post(**data).status_code,302)
        self.assertEqual(post(**data).status_code,302)
        # A conflict with an existing period must not create a new subject assignment.
        self.assertEqual(post(**{**data,'lecture_subject':['subject:English','subject:Computer'],'time':['09:00','09:00']}).status_code,409)
        def check():
            W=self.ops['workflow'];cohorts=W.query.filter_by(kind='teacher-classes',status='Active').all()
            self.assertEqual({(r.data['class_name'],r.data['section'],r.data.get('subject')) for r in cohorts},{('One','A',''),('Two','B','English'),('Nine','A','Urdu')})
            rows=W.query.filter_by(kind='automatic-period-reminder',status='Active').all();self.assertEqual(len(rows),15)
            tt=app.extensions['automatic_report_helpers']['teacher_timetable'](cohorts)
            self.assertEqual([(r['class_name'],r['section'],r['subject'],r['time']) for r in tt if r['weekday']==0],[('One','A','Full Class','All day'),('Two','B','English','09:00'),('Nine','A','Urdu','10:00')])
            return next(r.id for r in cohorts if r.data['class_name']=='Nine')
        nine=self.tenant(check);self.login()
        page=self.c.get('/teacher-app/timetable');self.assertEqual(page.status_code,200)
        self.assertIn(b'5 full-class days',page.data);self.assertIn(b'10 lectures',page.data)
        self.assertIn(b'Nine',page.data);self.assertIn(b'Two',page.data)
        self.assertEqual(self.c.get(f'/teacher-app/classes/{nine}/diary?subject=Computer').status_code,403)
        self.assertEqual(self.c.get(f'/teacher-app/classes/{nine}/diary?subject=Urdu').status_code,200)
        self.assertEqual(self.c.post(path,data={'_csrf':self.token(),**data}).status_code,403)
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
        self.tenant(revoke);self.login();self.assertEqual(self.c.get('/teacher-app/my-salary').status_code,200);self.assertEqual(self.c.get('/teacher-app/requests/advance').status_code,200)
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
    def test_teacher_marks_sync_to_school_multi_subject_award(self):
        self.seed()
        def make():
            W=self.ops['workflow'];teacher=str(db.session.get(self.Staff,self.sid).employee_id)
            detail=self.rm['student'].query.filter_by(student_id=self.pupil).one()
            detail.data={**detail.data,'academic_session':'2027'}
            papers=[dict(subject=subject,grading='Marks',total=maximum,date=str(school_today()),type='Written',teacher=teacher,time='',syllabus='') for subject,maximum in [('English',40),('Math',50),('Urdu',50)]]
            scope=dict(campus='Campus A',class_name='One',section='A',academic_session='2027',exam_test_type='Monthly Test')
            sheet=W(kind='date-sheets',status='Active',data=dict(name='Fictional monthly sheet',papers=papers,**scope))
            db.session.add(sheet);db.session.flush()
            award=W(kind='awards',status='Active',data=dict(name='Fictional imported award',source_date_sheet_id=sheet.id,assessment_category='Monthly',student_filter='class',papers=papers,**scope))
            db.session.add(award);db.session.flush()
            db.session.add(self.ops['score'](award_id=award.id,student_id=self.pupil,paper=0,obtained=30,state=''))
            return award.id
        aid=self.tenant(make)
        root=f'/teacher-app/classes/{self.cid}'
        listing=self.c.get(root+'/exams')
        self.assertEqual(listing.status_code,200)
        self.assertIn(f'/marks/{aid}/1'.encode(),listing.data)
        for i in (0,2):
            self.assertNotIn(f'/marks/{aid}/{i}'.encode(),listing.data)
            self.assertEqual(self.c.get(root+f'/marks/{aid}/{i}').status_code,403)
        path=root+f'/marks/{aid}/1'
        token=self.review(path)
        data={'_csrf':self.token(),'review':token,f'mark_{self.pupil}':'51'}
        self.assertEqual(self.c.post(path,data=data).status_code,422)
        data[f'mark_{self.pupil}']='44'
        self.assertEqual(self.c.post(path,data=data).status_code,302)
        def check():
            rows=self.ops['score'].query.filter_by(award_id=aid).order_by(self.ops['score'].paper).all()
            self.assertEqual([(r.student_id,r.paper,r.obtained) for r in rows],[(self.pupil,0,30),(self.pupil,1,44)])
        self.tenant(check)
        self.assertEqual(self.login('owner@example.invalid').status_code,302)
        page=self.c.get(f'/workspace/marks/{aid}')
        self.assertEqual(page.status_code,200)
        self.assertRegex(page.data,rb'name="mark_'+str(self.pupil).encode()+rb'_1" value="44(?:\.0)?"')
        self.assertRegex(page.data,rb'name="mark_'+str(self.pupil).encode()+rb'_0" value="30(?:\.0)?"')

    def test_combined_award_all_assigned_subjects_atomic_save_and_publication_lock(self):
        self.seed()
        def make():
            W=self.ops['workflow'];assignment=db.session.get(W,self.cid);assignment.data={**assignment.data,'subject':''}
            for name in ('English','Urdu','Computer'):
                db.session.add(self.rm['settings'](category='subject',value=name,class_name='One'))
            teacher=str(db.session.get(self.Staff,self.sid).employee_id)
            papers=[dict(subject='Math',grading='Marks',total=50,teacher=teacher),dict(subject='English',grading='Marks',total=40,teacher=teacher),dict(subject='Urdu',grading='Marks',total=30,teacher='9999'),dict(subject='Computer',grading='Checkbox',total=0,teacher=teacher)]
            a=W(kind='awards',status='Active',data=dict(name='Fictional class test',campus='Campus A',class_name='One',section='A',papers=papers))
            db.session.add(a);db.session.flush()
            db.session.add(self.ops['score'](award_id=a.id,student_id=self.pupil,paper=0,obtained=35,state=''))
            return a.id
        aid=self.tenant(make);root=f'/teacher-app/classes/{self.cid}';path=root+f'/award/{aid}'
        page=self.c.get(root+'/exams');self.assertEqual(page.status_code,200);self.assertEqual(page.data.count(f'/award/{aid}'.encode()),1);self.assertIn(b'3 subjects',page.data)
        page=self.c.get(path);self.assertEqual(page.status_code,200)
        self.assertIn(b'Maximum marks',page.data);self.assertIn(b'Save all marks',page.data);self.assertIn(b'English',page.data);self.assertIn(b'Computer',page.data)
        self.assertNotIn(b'Urdu',page.data);self.assertNotIn(b'Pupil Campus B',page.data)
        token=self.review(path)
        mark=lambda i:f'mark_{i}_{self.pupil}'
        data={'_csrf':self.token(),'review':token,mark(0):'42',mark(1):'41',mark(3):'1'}
        self.assertEqual(self.c.post(path,data=data).status_code,422)
        self.tenant(lambda:self.assertEqual([(r.paper,r.obtained) for r in self.ops['score'].query.all()],[(0,35)]))
        data[mark(1)]='39'
        self.assertEqual(self.c.post(path,data={**data,mark(2):'25'}).status_code,403)
        self.assertEqual(self.c.post(path,data={**data,'mark_0_99999':'12'}).status_code,403)
        self.assertEqual(self.c.post(path,data=data).status_code,302)
        def check():
            self.assertEqual([(r.paper,r.obtained) for r in self.ops['score'].query.order_by(self.ops['score'].paper).all()],[(0,42),(1,39)])
            self.assertEqual(self.ops['qualitative'].query.one().value,'1')
        self.tenant(check)
        self.assertNotEqual(self.c.post(path,data=data).status_code,302)
        token=self.review(path)
        self.tenant(lambda:db.session.add(app.extensions['parent_exam_release_model'](award_id=aid,published=True)))
        self.assertEqual(self.c.post(path,data={**data,'review':token}).status_code,403)
        self.assertNotIn(b'Save all marks',self.c.get(path).data)

    def test_combined_award_subject_teacher_multiple_assignments_and_stale_review(self):
        self.seed()
        def make():
            W=self.ops['workflow'];assignment=db.session.get(W,self.cid)
            db.session.add(self.rm['settings'](category='subject',value='English',class_name='One'))
            other=W(kind='teacher-classes',status='Active',data={**assignment.data,'subject':'English'})
            db.session.add(other);db.session.flush()
            papers=[dict(subject='Math',grading='Marks',total=50),dict(subject='English',grading='Marks',total=40),dict(subject='Urdu',grading='Marks',total=30)]
            a=W(kind='awards',status='Active',data=dict(name='Fictional lecture test',campus='Campus A',class_name='One',section='A',papers=papers))
            db.session.add(a);db.session.flush()
            return a.id,other.id
        aid,cid2=self.tenant(make);root=f'/teacher-app/classes/{self.cid}';path=root+f'/award/{aid}'
        page=self.c.get('/teacher-app/classes?feature=exam_list');self.assertEqual(page.status_code,200);self.assertEqual(page.data.count(b'Award lists'),1)
        page=self.c.get(path);self.assertIn(b'English',page.data);self.assertIn(b'Math',page.data);self.assertNotIn(b'Urdu',page.data)
        token=self.review(path)
        data={'_csrf':self.token(),'review':token,f'mark_0_{self.pupil}':'32',f'mark_1_{self.pupil}':'37'}
        self.tenant(lambda:setattr(db.session.get(self.ops['workflow'],cid2),'status','Voided'))
        self.assertEqual(self.c.post(path,data=data).status_code,422)
        self.tenant(lambda:self.assertEqual(self.ops['score'].query.count(),0))
        page=self.c.get(path);self.assertNotIn(b'English',page.data);self.assertIn(b'Math',page.data)

    def test_create_one_award_with_multiple_subject_totals(self):
        self.seed()
        def full():
            row=db.session.get(self.ops['workflow'],self.cid);row.data={**row.data,'subject':''}
            db.session.add(self.rm['settings'](category='subject',value='English',class_name='One'))
            db.session.add(self.rm['settings'](category='subject',value='Other class',class_name='Two'))
        self.tenant(full)
        root=f'/teacher-app/classes/{self.cid}';path=root+'/exams/new';page=self.c.get(path)
        self.assertIn(b'English',page.data);self.assertIn(b'Math',page.data);self.assertNotIn(b'Other class',page.data)
        data=dict(_csrf=self.token(),review=self.review(path),name='Fictional combined monthly',exam_date=str(school_today()),return_date=str(school_today()+timedelta(days=1)),test_type='Written',sort_order='roll',student_filter='class',subjects=['0','1'],total_0='40',total_1='50')
        self.assertEqual(self.c.post(path,data={**data,'subjects':['0','1','2']}).status_code,422)
        self.assertEqual(self.c.post(path,data={**data,'total_1':'NaN'}).status_code,422)
        self.assertEqual(self.c.post(path,data=data).status_code,302)
        def check():
            a=self.ops['workflow'].query.filter_by(kind='awards').one()
            self.assertEqual([(p['subject'],p['total']) for p in a.data['papers']],[('English',40),('Math',50)])
            return a.id
        aid=self.tenant(check)
        self.assertIn(b'Maximum marks',self.c.get(root+f'/award/{aid}').data)

    def test_material_publication_and_files_stay_assigned(self):
        self.seed();path=f'/teacher-app/classes/{self.cid}/materials';page=self.c.get(path);token=re.search(rb'name="token" value="([^"]+)"',page.data).group(1).decode()
        data={'_csrf':self.token(),'action':'create','token':token,'kind':'notes','title':'Fictional study','body':'<script>evil()</script><b>Read</b>','starts':str(school_today()),'ends':str(school_today()+timedelta(days=3)),'published':'1'}
        self.assertEqual(self.c.post(path,data=data).status_code,302)
        self.assertEqual(self.c.post(path,data=data).status_code,302)
        def check():
            rows=app.extensions['parent_study_models']['item'].query.all();self.assertEqual(len(rows),1);self.assertEqual((rows[0].campus,rows[0].section,rows[0].subject,rows[0].published),('Campus A','A','Math',True));self.assertNotIn('<script>',rows[0].body)
        self.tenant(check)
    def test_vacation_word_file_retry_save_and_download(self):
        import io
        from tests.word_attachment_fixture import word_attachment
        from student_extras import DOCX_MIME
        self.seed()
        path=f'/teacher-app/classes/{self.cid}/materials?kind=vacation'
        page=self.c.get(path);self.assertIn(b'.docx',page.data)
        token=re.search(rb'name="token" value="([^"]+)"',page.data).group(1).decode()
        start=str(school_today());end=str(school_today()+timedelta(days=3))
        data={'_csrf':self.token(),'action':'create','token':token,'kind':'vacation','title':'Fictional worksheet','body':'Read chapter one','starts':start,'ends':end,'due':end,'published':'1'}
        wrong=self.c.post(path,data={**data,'attachments':(io.BytesIO(b'not a Word document'),'fake.docx')})
        self.assertEqual(wrong.status_code,422)
        for expected in (b'Your text and dates are kept',b'Fictional worksheet',b'Read chapter one',b'value="vacation" selected',b'name="published" value="1" checked'):
            self.assertIn(expected,wrong.data)
        M=app.extensions['parent_study_models']
        self.tenant(lambda:self.assertEqual(M['item'].query.count(),0))
        content=word_attachment()
        saved=self.c.post(path,data={**data,'attachments':(io.BytesIO(content),'چھٹیوں کا کام.docx','application/octet-stream')})
        self.assertEqual(saved.status_code,302);self.assertIn('kind=vacation',saved.location)
        def check():
            row=M['item'].query.one();file=M['file'].query.one()
            self.assertEqual((row.kind,row.published,file.mime,file.content),('vacation',True,DOCX_MIME,content))
            self.assertTrue(file.filename.endswith('.docx'))
            return row.id,file.id
        iid,fid=self.tenant(check)
        downloaded=self.c.get(f'/teacher-app/classes/{self.cid}/materials/{iid}/files/{fid}')
        self.assertEqual(downloaded.status_code,200);self.assertEqual(downloaded.data,content)
        self.assertIn('attachment',downloaded.headers['Content-Disposition'])
        self.assertIn(DOCX_MIME,downloaded.headers['Content-Type'])
    def test_assignment_response_attachments_are_class_and_subject_scoped(self):
        from tests.word_attachment_fixture import word_attachment
        from student_extras import DOCX_MIME
        from secrets import token_urlsafe
        self.seed();M=app.extensions['parent_study_models'];content=word_attachment()
        def seed_response():
            W=self.ops['workflow'];cohort=db.session.get(W,self.cid);cohort.data={**cohort.data,'subject':''}
            item=M['item'](kind='assignments',title='Worksheet',campus='Campus A',class_name='One',section='A',subject='Math',body='Solve this',starts=school_today(),ends=school_today()+timedelta(days=1),published=True,token=token_urlsafe(32))
            db.session.add(item);db.session.flush()
            sub=M['submission'](item_id=item.id,student_id=self.pupil,family_id=1,body='')
            db.session.add(sub);db.session.flush()
            file=M['submission_file'](submission_id=sub.id,filename='response.docx',mime=DOCX_MIME,content=content);db.session.add(file);db.session.flush()
            foreign=Student.query.filter_by(name='Pupil Campus B').one()
            outside=M['submission'](item_id=item.id,student_id=foreign.id,family_id=2,body='Foreign answer');db.session.add(outside);db.session.flush()
            other=M['submission_file'](submission_id=outside.id,filename='foreign.docx',mime=DOCX_MIME,content=content);db.session.add(other);db.session.flush()
            return item.id,sub.id,file.id,outside.id,other.id
        iid,rid,fid,other_rid,other_fid=self.tenant(seed_response);self.login()
        root=f'/teacher-app/classes/{self.cid}/materials'
        path=f'{root}/{iid}/responses/{rid}/files/{fid}?subject=Math'
        page=self.c.get(root+'?subject=Math')
        self.assertEqual(page.status_code,200);self.assertIn(b'response.docx',page.data);self.assertIn(path.encode(),page.data);self.assertNotIn(b'foreign.docx',page.data)
        r=self.c.get(path);self.assertEqual(r.status_code,200);self.assertEqual(r.data,content);self.assertIn(DOCX_MIME,r.headers['Content-Type'])
        self.assertEqual(self.c.get(path.replace(f'responses/{rid}/files/{fid}',f'responses/{other_rid}/files/{other_fid}')).status_code,404)
        self.assertEqual(self.c.get(path.replace('subject=Math','subject=English')).status_code,403)
        self.assertEqual(self.c.post(root+'?subject=Math',data={'_csrf':self.token(),'action':'grade','item':iid,'submission':rid,'version':1,'marks':'8/10','feedback':'Good work'}).status_code,302)
        self.assertEqual(self.tenant(lambda:db.session.get(M['submission'],rid).marks),'8/10')
        self.assertEqual(self.c.get(path).data,content)
        self.tenant(lambda:setattr(db.session.get(self.ops['workflow'],self.cid),'status','Voided'))
        self.assertEqual(self.c.get(path).status_code,403)
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
    def test_today_diary_edits_same_record_without_duplicate(self):
        self.seed();path=f'/teacher-app/classes/{self.cid}/diary';page=self.c.get(path);token=re.search(rb'name="submission" value="([^"]+)"',page.data).group(1).decode();data={'_csrf':self.token(),'submission':token,'subject_slot':['0'],'subjects':['Math'],'subject_name_0':'Math','channel':'app','campus':'Campus A','class_name':'One','section':'A','starts':str(school_today()),'action':'save','classwork_0':'Read chapter one','homework_0':'Exercise one'}
        result=self.c.post(path,data=data);self.assertEqual(result.status_code,302,result.data)
        page=self.c.get(path);review=re.search(rb'name="review" value="([^"]+)"',page.data).group(1).decode();eid=re.search(rb'name="entry" value="([^"]+)"',page.data).group(1).decode();data.update(action='update',entry=eid,review=review,homework_0='Exercise two')
        result=self.c.post(path,data=data);self.assertEqual(result.status_code,302,result.data)
        def check():
            E=app.extensions['student_extras_models']['entry'];self.assertEqual(E.query.filter_by(kind='diary').count(),1);self.assertEqual(E.query.first().data['homework'],'Exercise two')
        self.tenant(check)
    def test_class_wise_marks_include_class_and_subject_wise_respects_enrollment(self):
        self.seed()
        def make():
            details=self.rm['student'].query.filter_by(student_id=self.pupil).one();details.data={**details.data,'subjects':['Urdu']}
            row=self.ops['workflow'](kind='awards',status='Active',data=dict(name='Fictional class exam',campus='Campus A',class_name='One',section='A',student_filter='class',papers=[dict(subject='Math',grading='Marks',total=37,date=str(school_today()),teacher='1')]))
            db.session.add(row);db.session.flush();return row.id
        aid=self.tenant(make);path=f'/teacher-app/classes/{self.cid}/marks/{aid}/0';self.assertIn(b'Pupil Campus A',self.c.get(path).data)
        def filter_subject():
            row=db.session.get(self.ops['workflow'],aid);row.data={**row.data,'student_filter':'subject'}
        self.tenant(filter_subject);self.assertNotIn(b'Pupil Campus A',self.c.get(path).data)
