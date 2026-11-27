"""Follow-up alerts use saved attendance and preserve the call outcome."""
import os
import unittest
from datetime import date
from unittest.mock import patch

os.environ['DATABASE_URL'] = 'sqlite:///:memory:'
from app import app, db, Employee, Student
from student_follow_up import CASE_KIND, absence_streak


class StudentFollowUpTests(unittest.TestCase):
    def setUp(self):
        app.config.update(TESTING=True, IDENTITY_ENFORCE_IN_TESTS=False, SECRET_KEY='follow-up-test')
        self.ctx = app.app_context()
        self.ctx.push()
        db.drop_all()
        db.create_all()
        self.client = app.test_client()
        self.clock = patch('student_follow_up.school_today', return_value=date(2026,11,24))
        self.clock.start()
        self.addCleanup(self.clock.stop)

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def test_unmarked_school_day_breaks_streak_and_holiday_does_not(self):
        start, today = date(2026,11,20), date(2026,11,24)
        marks = {date(2026,11,20):'Absent', date(2026,11,21):'Absent', today:'Absent'}
        self.assertEqual(absence_streak(marks,set(),today,start), ['2026-11-24'])
        self.assertEqual(absence_streak(marks,{date(2026,11,23)},today,start),
                         ['2026-11-20','2026-11-21','2026-11-24'])

    def test_sidebar_detects_absences_assigns_teacher_and_saves_parent_call(self):
        student=Student(admission_no='F-1',name='Fictional Follow-up Student',class_name='One',status='Active')
        teacher=Employee(employee_no='T-1',name='Fictional Teacher',role='Class Teacher',status='Active')
        db.session.add_all([student,teacher])
        db.session.flush()
        ops=app.extensions['ops_models']
        records=app.extensions['record_models']
        db.session.add(records['student'](student_id=student.id,data={'campus':'Campus A','section':'A'}))
        db.session.add(ops['workflow'](kind='teacher-classes',status='Active',
            data={'campus':'Campus A','class_name':'One','section':'A','employee_id':str(teacher.id)}))
        for day in (21,23,24):
            db.session.add(ops['daily'](kind='student',person_id=student.id,day=date(2026,11,day),status='Absent'))
        db.session.commit()
        path='/workspace/student-follow-up'
        page=self.client.get(path)
        self.assertEqual(page.status_code,200)
        self.assertIn(b'<strong>Student Follow-up Center</strong>',page.data)
        self.assertIn(b'Fictional Follow-up Student',page.data)
        self.assertIn(b'Fictional Teacher',page.data)
        self.assertIn(b'2026-11-21, 2026-11-23, 2026-11-24',page.data)
        self.assertEqual(ops['workflow'].query.filter_by(kind=CASE_KIND).count(),0)
        with self.client.session_transaction() as session:
            csrf=session['record_csrf']
            session['demo']=True
        form=dict(_csrf=csrf, case=f'{student.id}:2026-11-21', revision='0',
                  teacher_id=str(teacher.id), outcome='Call again', due='2026-11-25', note='Call after class')
        self.assertEqual(self.client.post(path+'/save',data=form).status_code,302)
        self.assertEqual(self.client.post(path+'/save',data=form).status_code,409)
        case=ops['workflow'].query.filter_by(kind=CASE_KIND).one()
        self.assertIn(b'Next call 2026-11-25',self.client.get(path).data)
        form.update(case=str(case.id),revision='1',outcome='Spoke to parent')
        self.assertEqual(self.client.post(path+'/save',data=form).status_code,302)
        self.assertNotIn(b'Fictional Follow-up Student',self.client.get(path).data)
        self.assertIn(b'Spoke to parent',self.client.get(path+'?show=all').data)
