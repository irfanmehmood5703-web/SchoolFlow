import unittest
from datetime import datetime
from school_clock import SCHOOL_TIMEZONE
from automatic_reports import period,REPORTS
from tests import test_parents_ptm as fixture
from app import app,db

class AutomaticReportTests(unittest.TestCase):
    password=fixture.ParentsPtmTests.password
    setUp=fixture.ParentsPtmTests.setUp
    tearDown=fixture.ParentsPtmTests.tearDown
    tenant=fixture.ParentsPtmTests.tenant
    token=fixture.ParentsPtmTests.token
    owner=fixture.ParentsPtmTests.owner
    post=fixture.ParentsPtmTests.post
    def test_configuration_owner_only_and_existing_inbox(self):
        path='/workspace/core/automatic-reports'
        self.assertEqual(self.c.get(path).status_code,200)
        self.assertNotEqual(app.test_client().get(path).status_code,200)
        data={'version':'0'}
        for k,_,f,t in REPORTS:
            data[k+'_frequency']=f;data[k+'_time']='00:00'
        data['fee-due_enabled']='on'
        self.assertEqual(self.post(path,data).status_code,302)
        self.assertEqual(self.post(path,data).status_code,409)
        self.assertIn(b'Generated challans',self.c.get(path).data)
        notices=self.c.get('/workspace/notifications').get_json()['events']
        self.assertTrue(any(e['key']=='auto-report:fee-due' for e in notices))
        self.assertFalse(any(e['key']=='auto-report:salary-due' for e in notices))
    def test_period_uses_local_time_and_stable_week_start(self):
        now=datetime(2026,11,23,7,59,tzinfo=SCHOOL_TIMEZONE)
        self.assertIsNone(period(now,'daily','08:00'))
        self.assertIsNone(period(now,'weekly','08:00'))
        self.assertEqual(str(period(now.replace(hour=8),'weekly','08:00')[0]),'2026-11-23')
        self.assertEqual(str(period(now,'monthly','08:00')[0]),'2026-11-01')
