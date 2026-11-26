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
    def test_new_school_default_daily_fee_notice_and_explicit_opt_out(self):
        from unittest.mock import patch
        Setting=app.extensions['school_settings_models']['setting']
        path='/owner-app/notification-feed'
        def due(hour):
            with patch('automatic_reports.datetime') as clock:
                clock.now.return_value=datetime(2026,11,25,hour,0,tzinfo=SCHOOL_TIMEZONE)
                return self.c.get(path).get_json()['events']
        self.assertFalse(any(e['title']=='Fee Collection' for e in due(19)))
        self.assertTrue(any(e['title']=='Fee Collection' and 'No fee received' in e['body'] for e in due(20)))
        self.tenant(lambda:db.session.add(Setting(key='automatic-owner-reports',data={'fee-received':dict(enabled=False,frequency='daily',time='20:00')})))
        self.assertFalse(any(e['title']=='Fee Collection' for e in due(20)))
    def test_zero_fee_default_and_authentication_for_native_owner_feed(self):
        Setting=app.extensions['school_settings_models']['setting']
        def seed():
            db.session.add(Setting(key='automatic-owner-reports',data={'fee-received':dict(enabled=True,frequency='daily',time='00:00')}))
        self.tenant(seed)
        path='/owner-app/notification-feed'
        self.assertNotEqual(app.test_client().get(path).status_code,200)
        r=self.c.get(path);self.assertEqual(r.status_code,200)
        event=next(e for e in r.json['events'] if e['title']=='Fee Collection')
        self.assertIn('No fee received',event['body'])
        self.assertIn('Rs. 0.00',event['body'])
        self.assertEqual(next(e for e in self.c.get(path).json['events'] if e['title']=='Fee Collection')['id'],event['id'])
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

    def test_forecast_uses_automatic_timing_and_avoids_double_count(self):
        from datetime import date
        Plan=app.extensions['student_fee_plan_model'];Bill=self.ops['bill'];Setting=app.extensions['school_settings_models']['setting']
        def seed():
            # Active pupils 1 and 2 from the isolated fictional institute.
            def line(name,amount,months):
                return dict(particular=name,net=amount,actual=amount,discount=0,arrears=0,student_custom=True,fee_rules=dict(timing='months',month_override=True,months=months))
            db.session.add(Plan(student_id=1,effective='2026-11',data=dict(lines=[line('QA tuition',350000,[12]),line('QA annual',300000,[3])])))
            db.session.add(Plan(student_id=2,effective='2026-11',data=dict(lines=[line('QA tuition',400000,[12])])))
            db.session.add(Bill(student_id=2,month='2026-12',due=date(2026,12,10),lines=[dict(particular='QA tuition',amount=400000)],paid=100000,discount=50000))
            db.session.add(Setting(key='automatic-owner-reports',data={'fee-forecast':dict(enabled=True,frequency='monthly',time='00:00')}))
        self.tenant(seed)
        now=datetime(2026,11,25,12,0,tzinfo=SCHOOL_TIMEZONE)
        def capture():
            f=app.extensions['automatic_report_helpers']['capture']
            self.assertEqual(f(now),1);self.assertEqual(f(now),0)
            row=self.ops['workflow'].query.filter_by(kind='automatic-report-snapshot').one()
            self.assertIn('Estimated ungenerated Rs. 3,500.00',row.data['detail'])
            self.assertIn('Existing net challans Rs. 3,500.00',row.data['detail'])
            self.assertIn('Estimated total Rs. 7,000.00',row.data['detail'])
            self.assertEqual(Bill.query.count(),1)
        self.tenant(capture)
    def test_period_reminder_only_for_the_matching_active_assignment(self):
        W=self.ops['workflow']
        def seed():
            data=dict(employee_id='1',campus='North',class_name='One',section='A',subject='Math')
            row=W(kind='teacher-classes',status='Active',data=data);db.session.add(row);db.session.flush();return row.id
        aid=self.tenant(seed)
        path='/workspace/core/automatic-reports/periods'
        self.assertEqual(self.post(path,dict(action='add',assignment_id=aid,weekday=0,time='09:00',lead=5)).status_code,302)
        def check():
            row=db.session.get(W,aid);f=app.extensions['automatic_report_helpers']['teacher_periods']
            now=datetime(2026,11,23,8,56,tzinfo=SCHOOL_TIMEZONE)
            self.assertEqual(f([],now),[])
            self.assertTrue(f([row],now)[0]['due'])
            self.assertEqual(f([row],now)[0]['subject'],'Math')
            timetable=app.extensions['automatic_report_helpers']['teacher_timetable']
            self.assertEqual(timetable([row])[0]['weekday'],0)
            self.assertEqual(timetable([row])[0]['time'],'09:00')
            self.assertEqual(timetable([]),[])
            self.assertFalse(f([row],now.replace(minute=50))[0]['due'])
            self.assertEqual(f([row],now.replace(hour=10)),[])
            row.data={**row.data,'subject':'Changed'}
            self.assertEqual(f([row],now),[])
            self.assertEqual(timetable([row]),[])
        self.tenant(check)
    def test_whatsapp_disabled_without_linked_provider(self):
        self.assertEqual(self.post('/workspace/core/automatic-reports/whatsapp',dict(action='enable',version='0',provider=1,device='missing',mobile='923000000001',consent='yes')).status_code,422)
        self.assertEqual(self.tenant(lambda:self.ops['audit'].query.filter_by(action='Change scheduled WhatsApp report consent').count()),0)
