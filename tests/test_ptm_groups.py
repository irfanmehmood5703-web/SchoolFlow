"""Reference PTM forms: event preferences, cohort selection and durable reports."""
import io,unittest
from werkzeug.datastructures import MultiDict
from tests import test_parents_ptm as fixture
from app import app,db

class PtmGroupTests(unittest.TestCase):
    tearDown=fixture.ParentsPtmTests.tearDown
    tenant=fixture.ParentsPtmTests.tenant
    token=fixture.ParentsPtmTests.token
    owner=fixture.ParentsPtmTests.owner
    post=fixture.ParentsPtmTests.post
    password=fixture.ParentsPtmTests.password

    def setUp(self):
        fixture.ParentsPtmTests.setUp(self)
        def seed():
            db.session.add(self.rm['settings'](category='academic_session',value='2026-27',class_name=''))
            for d in self.rm['student'].query.all():d.data={**d.data,'academic_session':'2026-27'}
        self.tenant(seed)
    def group(self,**changes):
        self.n+=1
        data=dict(_csrf=self.token(),scope_mode='group',submission=str(self.n).zfill(43),campus='North',class_name='One',sessions=['2026-27'],sections=['A'],students=['1','2'],teachers=['1'],day='2026-11-08',notes='Class discussion')
        data.update(changes)
        return MultiDict((k,v) for k,vs in data.items() for v in (vs if isinstance(vs,list) else [vs]))
    def test_standalone_group_retry_reports_update_export(self):
        data=self.group();self.assertEqual(self.c.post('/workspace/general/ptm/create',data=data).status_code,302)
        self.assertEqual(self.c.post('/workspace/general/ptm/create',data=data).status_code,302)
        self.assertEqual(self.tenant(lambda:self.P['group'].query.count()),1)
        self.assertEqual(self.tenant(lambda:self.P['evaluation'].query.count()),2)
        changed=MultiDict(data);changed['notes']='Different';self.assertEqual(self.c.post('/workspace/general/ptm/create',data=changed).status_code,422)
        self.assertEqual(self.post('/workspace/general/ptm/evaluations/1',{'version':'1','status':'Attended','feedback':'Discussed homework'}).status_code,302)
        self.assertEqual(self.post('/workspace/general/ptm/evaluations/1',{'version':'1','status':'Absent'}).status_code,422)
        page=self.c.get('/workspace/general/ptm/reports');self.assertIn(b'Discussed homework',page.data);self.assertIn(b'Fictional Child 2',page.data)
        from openpyxl import load_workbook
        x=self.c.get('/workspace/general/ptm/reports?export=xlsx');self.assertEqual(x.status_code,200);self.assertIn('Discussed homework',str(list(load_workbook(io.BytesIO(x.data)).active.values)))
        self.assertNotIn(b'Discussed homework',self.c.get('/workspace/general/ptm/reports?status=Absent').data)
    def test_options_and_forged_roster_teacher_filters(self):
        r=self.c.get('/workspace/general/ptm/options?campus=North&class_name=One&sessions=2026-27&sections=A');self.assertEqual(r.status_code,200);self.assertEqual(len(r.json['students']),2);self.assertEqual(len(r.json['teachers']),1)
        for changes in [dict(students=['999']),dict(sessions=['Missing']),dict(sections=['B']),dict(teachers=['999']),dict(exam_from='bad'),dict(exam_from='2026-11-08',exam_to='2026-11-07'),dict(subjects=['Missing']),dict(test_type='Missing')]:
            r=self.c.post('/workspace/general/ptm/create',data=self.group(**changes));self.assertEqual(r.status_code,422,changes)
        self.assertEqual(self.tenant(lambda:self.P['group'].query.count()),0)
        self.assertEqual(self.c.post('/workspace/general/ptm/create',data=self.group(teachers=[])).status_code,302)
    def test_event_preferences_validation_and_name_scope(self):
        def payload(**changes):
            self.n+=1;data=dict(submission=str(self.n).zfill(43),title='Term meeting',starts='2026-11-07',ends='2026-11-09',campus='North',event_preferences='1',term='Term 1',academic_year='2026-27',notify_parents='1',voice_notes='1',feedback_opens='2026-11-07T09:00',feedback_closes='2026-11-09T13:00');data.update(changes);return data
        self.assertEqual(self.post('/workspace/general/ptm/events',payload(feedback_closes='2026-11-06T12:00')).status_code,422)
        self.assertEqual(self.post('/workspace/general/ptm/events',payload()).status_code,302)
        meta=self.tenant(lambda:self.P['event_config'].query.one().data);self.assertTrue(meta['notify_parents']);self.assertTrue(meta['voice_notes'])
        self.assertEqual(self.post('/workspace/general/ptm/events',payload()).status_code,409)
        self.assertEqual(self.post('/workspace/general/ptm/events',payload(academic_year='2027-28')).status_code,302)
        self.assertEqual(self.post('/workspace/general/ptm/events',payload(campus='South')).status_code,302)
        self.assertEqual(self.c.post('/workspace/general/ptm/create',data=self.group(event_id='1')).status_code,302)
        self.assertEqual(self.c.post('/workspace/general/ptm/create',data=self.group(event_id='1',day='2026-12-01')).status_code,422)

    def test_marks_snapshot_respects_filters_and_remains_unchanged(self):
        def seed():
            w=self.ops['workflow'](kind='awards',status='Active',data=dict(name='Fictional exam',campus='North',class_name='One',papers=[dict(subject='Math',grading='Marks',total=100,date='2026-11-08',type='Written')]))
            db.session.add(w);db.session.flush();db.session.add(self.ops['score'](award_id=w.id,student_id=1,paper=0,obtained=80,state=''))
        self.tenant(seed)
        self.assertEqual(self.c.post('/workspace/general/ptm/create',data=self.group(subjects=['Math'],exam_from='2026-11-07',exam_to='2026-11-09')).status_code,302)
        marks=self.tenant(lambda:self.P['group'].query.one().data['marks']);self.assertEqual(float(marks[0]['obtained']),80)
        def change():self.ops['score'].query.one().obtained=90
        self.tenant(change)
        self.assertEqual(self.tenant(lambda:self.P['group'].query.one().data['marks']),marks)
        self.assertIn(b'Evaluation marks',self.c.get('/workspace/general/ptm/reports').data)

    def test_teacher_only_sees_assigned_groups_and_update_requires_permission(self):
        from werkzeug.security import generate_password_hash
        def seed():
            model=app.extensions['staff_account_model']
            db.session.add(model(employee_id=1,username='teacher',password_hash=generate_password_hash(self.password),active=True,data=dict(role='Teacher',campuses=['North'],permissions={'ptm.view':['North'],'ptm.update':['North'],'ptm.create':['North']})))
        self.tenant(seed)
        self.assertEqual(self.c.post('/workspace/general/ptm/create',data=self.group(notes='Assigned group')).status_code,302)
        self.assertEqual(self.c.post('/workspace/general/ptm/create',data=self.group(teachers=[],notes='Private manager group')).status_code,302)
        teacher=app.test_client();teacher.get('/auth/institute');self.post('/auth/institute',{'code':'PARENT-TEST'},teacher);self.post('/auth/login',{'email':'teacher','password':self.password},teacher)
        page=teacher.get('/workspace/general/ptm/meetings');self.assertEqual(page.status_code,200);self.assertIn(b'Assigned group',page.data);self.assertNotIn(b'Private manager group',page.data)
        self.assertEqual(self.post('/workspace/general/ptm/evaluations/1',{'version':'1','status':'Attended'},teacher).status_code,302)
        self.assertEqual(self.post('/workspace/general/ptm/evaluations/3',{'version':'1','status':'Attended'},teacher).status_code,403)
        data=self.group(subjects=['Math']);data['_csrf']=self.token(teacher)
        self.assertEqual(teacher.post('/workspace/general/ptm/create',data=data).status_code,403)
