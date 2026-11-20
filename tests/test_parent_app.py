"""Parent summaries, real requests and publication isolation in private fictional schools."""
import html,io,re,secrets,unittest,json
from datetime import timedelta
from unittest.mock import patch
from tests import test_parents_ptm as fixture
from app import app,db,Student
from school_clock import school_today

class ParentAppTests(unittest.TestCase):
    setUp=fixture.ParentsPtmTests.setUp
    tearDown=fixture.ParentsPtmTests.tearDown
    tenant=fixture.ParentsPtmTests.tenant
    token=fixture.ParentsPtmTests.token
    owner=fixture.ParentsPtmTests.owner
    post=fixture.ParentsPtmTests.post
    credential=fixture.ParentsPtmTests.credential
    parent=fixture.ParentsPtmTests.parent
    password=fixture.ParentsPtmTests.password
    base='/parents/PARENT-TEST'
    def seed_app(self):
        day=school_today()
        def seed():
            s=Student(admission_no='S3',name='Fictional Sibling',class_name='One',status='Active');db.session.add(s);db.session.flush();db.session.add(self.rm['student'](student_id=s.id,family_id=1,data=dict(campus='North',section='A',roll_no='003')))
            db.session.add(self.ops['daily'](kind='student',person_id=1,day=day,status='Absent'))
            db.session.add(self.ops['daily'](kind='student',person_id=1,day=day-timedelta(days=1),status='Late',time_in='08:35'))
            bill=self.ops['bill'](student_id=1,month=day.strftime('%Y-%m'),due=day,lines=[dict(particular='Tuition',amount=170000),dict(particular='Books',amount=30000)],paid=50000,discount=10000);db.session.add(bill);db.session.flush()
            db.session.add(self.ops['receipt'](student_id=1,bill_id=bill.id,day=day,amount=50000,discount=10000,account='Cash',token='parent-fixture'))
            db.session.add(self.ops['receipt'](student_id=1,bill_id=bill.id,day=day,amount=990000,account='Cash',token='void-fixture',voided=True))
            I=app.extensions['parent_study_models']['item']
            for kind in ('learning','notes','assignments','vacation'):
                item=I(kind=kind,title='Published '+kind,campus='North',class_name='One',section='A',subject='Math',body='Reviewed class resource',resource_url='https://example.invalid/lesson',starts=day-timedelta(days=1),ends=day+timedelta(days=3),due=day+timedelta(days=1),published=True,token=secrets.token_urlsafe(32));db.session.add(item);db.session.flush()
                if kind=='assignments':self.assignment=item.id
                if kind=='notes':
                    db.session.add(app.extensions['parent_study_models']['file'](item_id=item.id,filename='notes.pdf',mime='application/pdf',content=b'%PDF-1.4\nfictional'))
            db.session.add(I(kind='notes',title='SECRET DRAFT',campus='North',class_name='One',body='Hidden',starts=day,ends=day,published=False,token=secrets.token_urlsafe(32)))
            db.session.add(I(kind='notes',title='SECRET OTHER CAMPUS',campus='South',class_name='One',body='Hidden',starts=day,ends=day,published=True,token=secrets.token_urlsafe(32)))
        self.tenant(seed)
    def page(self,p,view,sid=1):return p.get(f'{self.base}/app/{view}?sid={sid}')
    def action(self,p,kind,data,sid=1):return self.post(f'{self.base}/app/students/{sid}/{kind}',{**dict(token=secrets.token_urlsafe(32)),**data},p)
    def test_all_tabs_family_switch_and_no_other_family(self):
        self.seed_app();p=self.parent()
        r=p.get(self.base);self.assertEqual(r.status_code,200);self.assertIn(b'Fictional Sibling',r.data);self.assertNotIn(b'Fictional Child 2',r.data)
        for view in ['student','overview','academics','results','attendance','fees','connect','profile','contact','leave','complaints','ptm','notifications','learning','notes','assignments','vacation','dates','rollslip']:
            r=self.page(p,view);self.assertEqual(r.status_code,200,(view,r.data[:100]));self.assertNotIn(b'SECRET',r.data)
            self.assertEqual(self.page(p,view,2).status_code,404,view)
        self.assertEqual(self.page(p,'fees',3).status_code,200);self.assertIn(b'Fictional Sibling',p.get(self.base+'/app/profile').data)
        self.assertEqual(self.page(p,'fees','bad').status_code,404)
    def test_attendance_real_counts_and_unmarked(self):
        self.seed_app();p=self.parent();r=self.page(p,'attendance');self.assertIn(b'50%',r.data);self.assertIn(b'08:35',r.data);self.assertIn(b'Absent',r.data)
        self.assertIn(b'Not marked',self.page(p,'attendance',3).data)
        self.assertEqual(p.get(self.base+'/app/attendance?sid=1&month=2026-99').status_code,422)
        self.assertEqual(p.get(self.base+'/app/attendance?sid=1&month=bad').status_code,422)
        for month in ['0001-01','9999-12']:self.assertEqual(p.get(self.base+'/app/attendance?sid=1&month='+month).status_code,422)
    def test_partial_fees_receipts_discounts_and_guarded_print(self):
        self.seed_app();p=self.parent();r=self.page(p,'fees')
        for value in [b'Rs 2,000.00',b'Rs 500.00',b'Rs 100.00',b'Rs 1,400.00',b'Partly paid']:self.assertIn(value,r.data)
        self.assertNotIn(b'9,900.00',r.data)
        self.assertEqual(p.get(self.base+'/app/students/1/challans/1').status_code,200)
        self.assertEqual(p.get(self.base+'/app/students/2/challans/1').status_code,404)
        self.assertEqual(p.get(self.base+'/app/students/3/challans/1').status_code,404)
    def test_parent_requests_are_idempotent_scoped_and_csrf_protected(self):
        p=self.parent();data=dict(token=secrets.token_urlsafe(32),**{'from':str(school_today()),'to':str(school_today()),'reason':'Fictional illness','type':'Sick Leave','campus':'South'})
        self.assertEqual(self.action(p,'leave',data).status_code,302);self.assertEqual(self.action(p,'leave',data).status_code,302)
        self.assertEqual(self.tenant(lambda:app.extensions['general_leave_model'].query.count()),1)
        self.assertEqual(self.action(p,'leave',dict(data,reason='Changed')).status_code,409)
        self.assertEqual(p.post(self.base+'/app/students/1/leave',data=data).status_code,400)
        self.assertEqual(self.action(p,'leave',data,2).status_code,404)
        payload=dict(kind='complaint',category='Academic',message='Fictional concern',campus='South',submitted_by='Spoofed')
        self.assertEqual(self.action(p,'feedback',payload).status_code,302)
        saved=self.tenant(lambda:app.extensions['general_feedback_model'].query.one().campus);self.assertEqual(saved,'North')
        self.assertIn(b'Fictional concern',self.page(p,'complaints').data)
        self.tenant(lambda:db.session.add(app.extensions['general_feedback_model'](institute_scope=self.H['school'](self.school).storage_key if 'school' in self.H else 'other',kind='complaint',category='Academic',message='SECRET OTHER FEEDBACK',submitted_by='Other',campus='North')))
        self.assertNotIn(b'SECRET OTHER FEEDBACK',self.page(p,'complaints').data)
    def test_assignment_response_ownership_grade_and_no_replay(self):
        self.seed_app();p=self.parent();data=dict(token=secrets.token_urlsafe(32),item=self.assignment,body='Fictional homework response')
        self.assertEqual(self.action(p,'submission',data).status_code,302);self.assertEqual(self.action(p,'submission',data).status_code,302)
        self.assertEqual(self.action(p,'submission',dict(data,token=secrets.token_urlsafe(32))).status_code,409)
        self.assertEqual(self.action(p,'submission',data,2).status_code,404)
        self.assertIn(b'Response submitted',self.page(p,'assignments').data)
        self.assertEqual(self.post('/workspace/general/parent-study',dict(action='grade',id=1,version=1,marks='100'),p).status_code,302)
        self.assertEqual(self.post('/workspace/general/parent-study',dict(action='grade',id=1,version=1,marks='8 / 10',feedback='Good work')).status_code,302)
        p=self.parent();self.assertIn(b'8 / 10',self.page(p,'assignments').data)
    def test_published_resources_files_revoked_and_not_foreign_child(self):
        self.seed_app();p=self.parent();file=self.tenant(lambda:app.extensions['parent_study_models']['file'].query.one().id)
        path=f'{self.base}/app/students/1/study/files/{file}';self.assertEqual(p.get(path).status_code,200)
        self.assertEqual(p.get(path.replace('students/1/','students/2/')).status_code,404)
        def hide():app.extensions['parent_study_models']['item'].query.filter_by(kind='notes',published=True,campus='North').one().published=False
        self.tenant(hide);self.assertEqual(p.get(path).status_code,404)
    def test_publication_ui_validates_unsafe_link_and_real_scope(self):
        self.assertEqual(self.c.get('/workspace/general/parent-study').status_code,200)
        data=dict(action='publish',token=secrets.token_urlsafe(32),kind='learning',campus='North',class_name='One',section='A',title='Test lesson',starts=str(school_today()),ends=str(school_today()),body='<script>secret</script><b>Safe</b>',published='1')
        self.assertEqual(self.post('/workspace/general/parent-study',dict(data,resource_url='javascript:alert(1)')).status_code,422)
        self.assertEqual(self.post('/workspace/general/parent-study',dict(data,campus='Fake')).status_code,422)
        self.assertEqual(self.post('/workspace/general/parent-study',data).status_code,302)
        page=self.page(self.parent(),'learning');self.assertIn(b'Safe',page.data);self.assertNotIn(b'<script>secret',page.data)
    def test_fee_rules_hide_summary_results_study_and_files(self):
        self.seed_app();fixture.ParentsPtmTests.seed_debt(self)
        self.assertEqual(self.post('/workspace/general/parents/privileges',dict(version='0',action='rules',attendance_3='block',diary_3='block',marks_3='block',results_3='block')).status_code,302)
        p=self.parent();home=p.get(self.base);self.assertIn(b'Restricted',home.data)
        for view in ['attendance','academics','results','learning','assignments','notes']:self.assertEqual(self.page(p,view).status_code,403,view)
        self.assertEqual(p.get(self.base+'/app/students/1/study/files/1').status_code,403)
        notices=self.page(p,'notifications');self.assertNotIn(b'data-notice-key="attendance:',notices.data);self.assertIn(b'Challan',notices.data)
        self.assertEqual(self.page(p,'fees').status_code,200)
    def test_notification_ack_only_current_revision_and_revocation(self):
        self.seed_app();p=self.parent();page=self.page(p,'notifications');items=[dict(key=k.decode(),revision=r.decode()) for k,r in re.findall(rb'data-notice-key="([^"]+)" data-notice-revision="([^"]+)"',page.data)];self.assertTrue(items)
        self.assertEqual(self.action(p,'read',dict(items=json.dumps(items))).status_code,204)
        self.assertIn(b'0 unread',self.page(p,'notifications').data)
        def changed():self.ops['daily'].query.filter_by(person_id=1,day=school_today()).one().status='Present'
        self.tenant(changed);self.action(p,'read',dict(items=json.dumps(items)));self.assertIn(b'1 unread',self.page(p,'notifications').data)
        self.post('/workspace/general/parents/links/1',dict(action='revoke'));self.assertEqual(self.page(p,'fees').status_code,302)
    def test_ptm_feedback_keeps_staff_notes_private_and_rejects_stale_version(self):
        def seed():
            E=self.P['event'];M=self.P['meeting'];e=E(title='Class PTM',campus='North',starts=school_today(),ends=school_today(),notes='SECRET EVENT NOTE',token='ptm-event');db.session.add(e);db.session.flush();db.session.add(M(event_id=e.id,student_id=1,employee_id=1,campus='North',day=school_today(),time='10:30',notes='SECRET STAFF NOTE',token='ptm-one'))
        self.tenant(seed);p=self.parent();r=self.page(p,'ptm');self.assertIn(b'Class PTM',r.data);self.assertNotIn(b'SECRET',r.data)
        self.assertEqual(self.action(p,'ptm',dict(id=1,version=1,feedback='Helpful meeting')).status_code,302)
        self.assertEqual(self.action(p,'ptm',dict(id=1,version=1,feedback='stale')).status_code,409)
        self.assertEqual(self.action(p,'ptm',dict(id=1,version=2,feedback='foreign'),2).status_code,404)
    def test_reviewed_exam_document_snapshot_and_changed_roster(self):
        def seed():
            w=self.ops['workflow'](kind='date-sheets',data=dict(name='Class exam',campus='North',class_name='One',papers=[dict(subject='Math',date=str(school_today()),time='09:00',type='Written',total=75,teacher='SECRET TEACHER ID')]));db.session.add(w);db.session.flush();return w.id
        wid=self.tenant(seed);review=self.c.get('/workspace/general/parent-study?workflow='+str(wid));self.assertEqual(review.status_code,200);digest=re.search(rb'name="fingerprint" value="([^"]+)"',review.data)[1].decode()
        data=dict(action='publish',kind='dates',workflow=wid,fingerprint=digest,token=secrets.token_urlsafe(32),campus='North',class_name='One',title='Class schedule',starts=str(school_today()),ends=str(school_today()),published='1')
        self.assertEqual(self.post('/workspace/general/parent-study',dict(data,fingerprint='🔥')).status_code,422)
        self.assertEqual(self.post('/workspace/general/parent-study',data).status_code,302)
        p=self.parent();page=self.page(p,'dates');self.assertIn(b'Class schedule',page.data);self.assertNotIn(b'SECRET',page.data)
        def change():self.ops['workflow'].query.filter_by(id=wid).one().data=dict(name='Changed',campus='North',class_name='One',papers=[])
        self.tenant(change);self.assertEqual(self.post('/workspace/general/parent-study',dict(data,token=secrets.token_urlsafe(32))).status_code,422)
    def test_colliding_ids_in_another_school_cannot_share_resources_or_sessions(self):
        self.seed_app();p=self.parent();other=self.H['provision']('PARENT-OTHER','Other Private School','owner@example.invalid',self.password).id
        def seed():
            f=self.rm['family'](id=1,number='OTHER1',data=dict(phone='03000000009'));db.session.add(f);db.session.add(Student(id=1,admission_no='OTHER1',name='Other private child',class_name='One',status='Active'));db.session.flush();db.session.add(self.rm['student'](student_id=1,family_id=1,data=dict(campus='North',section='A')))
            I=app.extensions['parent_study_models']['item'];db.session.add(I(id=1,kind='notes',title='Other private notes',campus='North',class_name='One',body='OTHER PRIVATE CONTENT',starts=school_today(),ends=school_today(),published=True,token=secrets.token_urlsafe(32)))
        self.tenant(seed,other);owner=self.owner('PARENT-OTHER');response=self.post('/workspace/general/parents/links/1',dict(action='issue'),owner);credential=html.unescape(re.search(rb'<strong data-parent-credential>(.*?)</strong>',response.data)[1].decode()).split('#')[1]
        q=app.test_client();self.token(q,'/parents/PARENT-OTHER/enter');self.assertEqual(self.post('/parents/PARENT-OTHER/enter',dict(credential=credential),q).status_code,302)
        self.assertNotIn(b'OTHER PRIVATE CONTENT',self.page(p,'notes').data)
        page=q.get('/parents/PARENT-OTHER/app/notes?sid=1');self.assertIn(b'OTHER PRIVATE CONTENT',page.data);self.assertNotIn(b'Reviewed class resource',page.data)
        self.assertEqual(q.get(self.base+'/app/notes?sid=1').status_code,302)
    def test_private_profile_never_exposes_school_owner_or_staff_notes(self):
        p=self.parent()
        def seed():
            r=self.rm['student'].query.filter_by(student_id=1).one();r.data={**r.data,'notes':'SECRET STAFF NOTES','medical':'SECRET HEALTH'}
            P=app.extensions['institute_setup_models']['profile'];r=db.session.get(P,1);r.data=dict(name='Updated Private School',owner_contact='SECRET OWNER',contact='03000000000',address='School address')
        self.tenant(seed)
        for view in ['profile','contact','student']:
            page=self.page(p,view);self.assertNotIn(b'SECRET',page.data);self.assertIn(b'Updated Private School',page.data)
        self.assertIn(b'tel:03000000000',self.page(p,'contact').data)

if __name__=='__main__':unittest.main()
