"""Cover assignments follow real timetable slots and staff attendance."""
import os
import unittest
from datetime import date
from unittest.mock import patch

os.environ['DATABASE_URL'] = 'sqlite:///:memory:'
from app import app, db, Employee
from class_cover import COVER


class ClassCoverTests(unittest.TestCase):
    day = date(2026, 11, 23)

    def setUp(self):
        app.config.update(TESTING=True, IDENTITY_ENFORCE_IN_TESTS=False, SECRET_KEY='class-cover-test')
        self.ctx = app.app_context()
        self.ctx.push()
        db.drop_all()
        db.create_all()
        self.client = app.test_client()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def test_assign_and_remove_cover_blocks_absent_busy_and_already_booked_teachers(self):
        models = app.extensions['ops_models']
        W, Daily = models['workflow'], models['daily']
        Details = app.extensions['record_models']['employee']
        original, other_absent, busy, available = (
            Employee(employee_no=str(i), name=name, role='Teacher', status='Active')
            for i, name in enumerate(('Absent teacher', 'Second absent teacher', 'Busy teacher', 'Available teacher'), 1))
        db.session.add_all([original, other_absent, busy, available])
        db.session.flush()
        for employee in (original, other_absent, busy, available):
            db.session.add(Details(employee_id=employee.id, data={'campus':'Main'}))
        db.session.add(Daily(kind='staff',person_id=original.id,day=self.day,status='Absent'))
        db.session.add(W(kind='leave-approvals',status='Approved',data={
            'employee_id':str(other_absent.id),'from_date':self.day.isoformat(),'to_date':self.day.isoformat()}))
        periods = []
        for teacher, campus, section in ((original,'Main','A'), (other_absent,'Main','B'), (busy,'Other','C')):
            assignment = W(kind='teacher-classes',status='Active',
                           data=dict(employee_id=str(teacher.id),campus=campus,class_name='One',section=section,subject='Maths'))
            db.session.add(assignment)
            db.session.flush()
            period = W(kind='automatic-period-reminder',status='Active',
                       data=dict(assignment=assignment.data,assignment_id=assignment.id,weekday=0,time='10:00',lead=5))
            db.session.add(period)
            periods.append(period)
        db.session.commit()
        page = self.client.get('/workspace/class-cover?day='+self.day.isoformat())
        self.assertEqual(page.status_code,200)
        self.assertIn(b'Approved leave',page.data)
        self.assertIn(b'Available teacher</option>',page.data)
        self.assertNotIn(b'Busy teacher</option>',page.data)
        with self.client.session_transaction() as session:
            token=session['record_csrf']
        post='/workspace/class-cover/save'
        data=dict(_csrf=token, action='assign', day=self.day.isoformat(), period=periods[0].id, revision=0)
        self.assertEqual(self.client.post(post,data={**data,'substitute':busy.id}).status_code,409)
        self.assertEqual(self.client.post(post,data={**data,'substitute':available.id}).status_code,302)
        self.assertEqual(self.client.post(post,data={**data,'substitute':available.id,'period':periods[1].id}).status_code,409)
        with patch('dashboard.school_today',return_value=self.day):
            self.assertIn(b'Uncovered Periods Today \xc2\xb7 1',self.client.get('/workspace/dashboard').data)
        helper=app.extensions['class_cover_helpers']['teacher_assignments']
        with app.test_request_context('/'):
            self.assertEqual(helper(available.id,{'Main'},self.day)[0]['subject'],'Maths')
            self.assertEqual(helper(available.id,{'Other'},self.day),[])
            self.assertEqual(helper(busy.id,{'Main'},self.day),[])
        self.assertEqual(self.client.post(post,data={**data,'action':'remove','revision':1}).status_code,302)
        self.assertEqual(W.query.filter_by(kind=COVER,status='Active').count(),0)
