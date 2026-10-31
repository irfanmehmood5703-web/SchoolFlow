"""Dashboard layout persistence, isolation, stale saves and live-data links."""
import os
import unittest
from datetime import date,timedelta
from werkzeug.datastructures import MultiDict
os.environ['DATABASE_URL']='sqlite:///:memory:'
from app import app,db,Student
from dashboard import KEYS, WIDGETS


class DashboardTests(unittest.TestCase):
    def setUp(self):
        app.config.update(TESTING=True,SECRET_KEY='dashboard-fictional',IDENTITY_ENFORCE_IN_TESTS=False)
        self.ctx=app.app_context();self.ctx.push();db.drop_all();db.create_all()
        self.model=app.extensions['dashboard_preference_model']
        self.c=app.test_client();self.c.get('/workspace/dashboard')
        with self.c.session_transaction() as sess:self.csrf=sess['record_csrf']

    def tearDown(self):
        db.session.remove();db.drop_all();self.ctx.pop()

    def payload(self,**changes):
        data=dict(_csrf=self.csrf,widgets=list(KEYS),order=list(KEYS),mode='widgets',columns='3',quick='on',version='0',action='apply')
        data.update(changes)
        return MultiDict((key,value) for key,values in data.items() for value in (values if isinstance(values,list) else [values]))

    def post(self,**changes):
        return self.c.post('/workspace/dashboard/layout',data=self.payload(**changes))

    def owner(self,id=41,client=None):
        with (client or self.c).session_transaction() as sess:
            sess['owner_id']=id;sess.pop('demo',None)
            sess.pop('dashboard_layout',None);sess.pop('dashboard_default',None)

    def test_get_has_controls_and_does_not_write_a_default(self):
        response=self.c.get('/workspace/dashboard')
        self.assertEqual(response.status_code,200)
        for label in [b'Add Widgets',b'Customise',b'Make this my default dashboard',b'Simple Dashboard',b'Advanced settings']:
            self.assertIn(label,response.data)
        self.assertEqual(response.data.count(b'data-dashboard-widget='),len(KEYS))
        self.assertEqual(self.model.query.count(),0)

    def test_apply_preserves_selection_order_and_appearance_until_restore(self):
        order=list(reversed(KEYS))
        self.assertEqual(self.post(widgets=['active','queries'],order=order,columns='1',compact='on',quick='').status_code,302)
        page=self.c.get('/workspace/dashboard').data
        self.assertEqual(page.count(b'data-dashboard-widget='),2)
        self.assertLess(page.index(b'data-dashboard-widget="active"'),page.index(b'data-dashboard-widget="queries"'))
        self.assertIn(b'columns-1 compact',page)
        self.assertNotIn(b'ACTIVE EMPLOYEES',page)
        self.assertEqual(self.model.query.count(),0)
        self.post(action='restore')
        self.assertEqual(self.c.get('/workspace/dashboard').data.count(b'data-dashboard-widget='),len(KEYS))

    def test_owner_default_survives_a_new_session_and_other_owner_is_independent(self):
        self.owner()
        self.assertEqual(self.post(action='default',widgets=['due'],columns='2').status_code,302)
        self.assertEqual(self.model.query.one().owner_key,'owner:41')
        other=app.test_client();self.owner(client=other)
        self.assertEqual(other.get('/workspace/dashboard').data.count(b'data-dashboard-widget='),1)
        self.owner(42,other)
        self.assertEqual(other.get('/workspace/dashboard').data.count(b'data-dashboard-widget='),len(KEYS))

    def test_demo_default_is_session_only_not_shared(self):
        with self.c.session_transaction() as sess:sess['demo']=True
        self.post(action='default',widgets=['active'])
        self.assertEqual(self.c.get('/workspace/dashboard').data.count(b'data-dashboard-widget='),1)
        self.assertEqual(app.test_client().get('/workspace/dashboard').data.count(b'data-dashboard-widget='),len(KEYS))
        self.assertEqual(self.model.query.count(),0)

    def test_stale_default_save_fails_without_overwriting(self):
        self.owner();self.post(action='default',widgets=['active'])
        self.assertEqual(self.post(action='default',widgets=['due'],version='1').status_code,302)
        self.assertEqual(self.post(action='default',widgets=['queries'],version='1').status_code,422)
        self.assertEqual(self.model.query.one().layout['widgets'],['due'])

    def test_simple_mode_preserves_widgets_and_empty_selection_is_usable(self):
        self.post(widgets=['active'],action='apply')
        self.post(action='simple')
        page=self.c.get('/workspace/dashboard').data
        self.assertIn(b'Your daily workspace',page);self.assertNotIn(b'data-dashboard-widget=',page)
        self.post(action='widgets')
        self.assertEqual(self.c.get('/workspace/dashboard').data.count(b'data-dashboard-widget='),1)
        self.post(widgets=[])
        self.assertIn(b'No widgets selected',self.c.get('/workspace/dashboard').data)

    def test_csrf_and_invalid_payloads_do_not_mutate_default(self):
        self.owner()
        self.assertEqual(self.c.post('/workspace/dashboard/layout',data={'action':'restore'}).status_code,400)
        for changes in [dict(widgets=['unknown']),dict(widgets=['active','active']),dict(order=['active']),dict(columns='4'),dict(mode='unknown'),dict(action='unknown'),dict(action='default',version='bad')]:
            self.assertEqual(self.post(**changes).status_code,422,changes)
        self.assertEqual(self.model.query.count(),0)

    def test_widget_reports_are_real_pages_and_counts_read_saved_records(self):
        db.session.add(Student(admission_no='TEST-DASH-01',name='Fictional Dashboard Pupil',status='Active'));db.session.commit()
        self.assertEqual(app.extensions['operation_helpers']['dashboard']()['active'],1)
        for widget in WIDGETS:
            self.assertEqual(self.c.get(widget[5]).status_code,200,widget[5])
            self.assertNotIn(b'Reference pending',self.c.get(widget[5]).data,widget[5])

    def test_pending_report_and_staff_month_ignore_future_attendance(self):
        models=app.extensions['ops_models'];today=date.today()
        db.session.add_all([
            models['workflow'](kind='advances',status='Pending',data={}),
            models['workflow'](kind='leave-approvals',status='Pending',data={}),
            models['workflow'](kind='increments',status='Approved',data={}),
            models['daily'](kind='staff',person_id=1,day=today,status='Present'),
            models['daily'](kind='staff',person_id=1,day=today+timedelta(days=32),status='Absent'),
        ]);db.session.commit()
        stats=app.extensions['operation_helpers']['dashboard']()
        self.assertEqual(stats['pending'],2);self.assertEqual(dict(stats['staff_counts']),{'Present':1})
        page=self.c.get('/workspace/dashboard/pending')
        self.assertEqual(page.status_code,200)
        self.assertIn(b'2 pending records',page.data);self.assertNotIn(b'Approved',page.data)
        self.assertIn(b'/workspace/register/advances',page.data)


if __name__=='__main__':unittest.main()
