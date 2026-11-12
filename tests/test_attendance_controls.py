"""Alert timing, status policy and self-only geofence security regressions."""
import hashlib,json
from datetime import timedelta
from unittest.mock import patch
import unittest
from flask import g
from werkzeug.security import generate_password_hash
import tests.test_attendance_devices as fixture
from app import app,db,Student,Employee
from module_catalog import STATUSES

class AttendanceControlsTests(unittest.TestCase):
    password=fixture.AttendanceDeviceTests.password
    key=fixture.AttendanceDeviceTests.key
    tenant=fixture.AttendanceDeviceTests.tenant
    login=fixture.AttendanceDeviceTests.login
    token=fixture.AttendanceDeviceTests.token
    headers=fixture.AttendanceDeviceTests.headers
    daily=fixture.AttendanceDeviceTests.daily
    def setUp(self):
        fixture.AttendanceDeviceTests.setUp(self);self.controls=app.extensions['attendance_control_models'];self.timepatch=patch('attendance_controls.utc_now',side_effect=lambda:self.stamp);self.timepatch.start()
    def tearDown(self):self.timepatch.stop();fixture.AttendanceDeviceTests.tearDown(self)
    def post(self,path,**data):return self.c.post(path,data={'_csrf':self.token(),**data})
    def alert_settings(self,**changes):return self.post('/workspace/core/attendance-alerts',action='save',version='0',student_enabled='1',staff_enabled='1',student_delay='15',staff_delay='15',**changes)
    def seed_fence(self):
        return self.post('/workspace/core/geo-attendance',campus='Campus A',version='0',latitude='31.4',longitude='73.1',radius='100',enabled='1',within_only='1')
    def staff(self):
        def seed():
            Staff=app.extensions['staff_account_model'];db.session.add(Staff(employee_id=1,username='geo.teacher',password_hash=generate_password_hash(self.password),active=True,data={'campuses':['Campus A'],'permissions':{'attendance.self':['Campus A']}}))
        self.tenant(seed);self.login('geo.teacher')
    def register(self):
        r=self.post('/workspace/attendance/geo-self',action='register',name='Fictional phone');self.assertEqual(r.status_code,200,r.data);return r.json
    def mark(self,device,**changes):
        return self.post('/workspace/attendance/geo-self',action='mark',device=str(device['id']),key=device['key'],event_id='fictional_geo_event_001',direction='in',latitude='31.4',longitude='73.1',accuracy='5',captured_ms=str(self.stamp.timestamp()*1000),**changes)
    def test_core_gets_are_read_only_with_real_reference_controls(self):
        self.login();before=self.tenant(lambda:self.Setting.query.count())
        for path in ('attendance-alerts','attendance-acronyms','geo-attendance','geo-attendance/devices'):
            r=self.c.get('/workspace/core/'+path);self.assertEqual(r.status_code,200,r.data)
        self.assertEqual(before,self.tenant(lambda:self.Setting.query.count()));self.assertEqual(self.tenant(lambda:self.controls['alert'].query.count()),0)
        page=self.c.get('/workspace/core/attendance-acronyms');self.assertIn(b'Sandwich Leave',page.data)
    def test_alert_delays_no_duplicates_and_read_state_survives_checks(self):
        self.login();self.assertEqual(self.alert_settings().status_code,302)
        self.stamp=self.stamp.replace(minute=14)
        self.post('/workspace/core/attendance-alerts',action='check');self.assertEqual(self.tenant(lambda:self.controls['alert'].query.count()),0)
        self.stamp=self.stamp.replace(minute=15)
        self.post('/workspace/core/attendance-alerts',action='check');self.assertEqual(self.tenant(lambda:self.controls['alert'].query.count()),2)
        self.post('/workspace/core/attendance-alerts',action='read-all');self.post('/workspace/core/attendance-alerts',action='check')
        self.assertEqual(self.tenant(lambda:self.controls['alert'].query.filter_by(unread=True).count()),0)
        self.assertEqual(self.tenant(lambda:self.controls['alert'].query.count()),2)
    def test_any_mark_in_section_suppresses_that_sections_alert(self):
        self.login();self.alert_settings()
        def seed():
            db.session.add(self.ops['daily'](kind='student',person_id=1,day=self.stamp.astimezone(__import__('zoneinfo').ZoneInfo('Asia/Karachi')).date(),status='Present'))
        self.tenant(seed);self.post('/workspace/core/attendance-alerts',action='check')
        values=self.tenant(lambda:[(r.kind,r.data) for r in self.controls['alert'].query.all()]);self.assertEqual(len(values),2)
        student=next(x[1] for x in values if x[0]=='student');self.assertEqual({v['campus'] for v in student.values()},{'Campus B'})
    def test_alert_mutations_need_csrf_and_fresh_versions(self):
        self.login();r=self.c.post('/workspace/core/attendance-alerts',data={'action':'check'});self.assertEqual(r.status_code,400)
        self.assertEqual(self.alert_settings().status_code,302);self.assertEqual(self.alert_settings().status_code,422)
    def test_inactive_status_refuses_new_device_mark_without_deleting_history(self):
        self.login();data={'action':'save','version':'0'}
        for k in ('staff','student'):
            for s in STATUSES:
                if s!='Late':data[k+'_'+s]='1'
        self.assertEqual(self.post('/workspace/core/attendance-acronyms',**data).status_code,302)
        r=self.c.post('/api/attendance/devices/1/events',json={'event_id':'inactive_status_001','person_kind':'student','person_id':1,'direction':'in','occurred_at':self.stamp.isoformat()},headers=self.headers())
        self.assertEqual(r.json['outcome'],'Not marked');self.assertEqual(self.daily(),[])
        self.assertNotIn('Late',self.tenant(lambda:app.extensions['attendance_control_helpers']['statuses']('student')))
    def test_geofence_validation_and_stale_save(self):
        self.login();self.assertEqual(self.seed_fence().status_code,302);self.assertEqual(self.seed_fence().status_code,422)
        for lat,lon,radius in [('nan','0','50'),('91','0','50'),('1','181','50'),('1','2','14')]:
            self.assertEqual(self.post('/workspace/core/geo-attendance',campus='Campus A',version='1',latitude=lat,longitude=lon,radius=radius).status_code,422)
        self.assertEqual(self.tenant(lambda:db.session.get(self.controls['fence'],'Campus A').latitude),31.4)
    def test_self_geo_mark_is_scoped_idempotent_and_revocable(self):
        self.login();self.seed_fence();self.staff();device=self.register();r=self.mark(device);self.assertEqual(r.status_code,201,r.data);self.assertEqual(r.json['outcome'],'Marked')
        again=self.mark(device);self.assertEqual(again.status_code,200);self.assertTrue(again.json['replayed']);self.assertEqual(len(self.daily()),1)
        self.assertEqual(self.c.get('/workspace/core/geo-attendance/devices').status_code,403)
        self.login();self.assertEqual(self.post('/workspace/core/geo-attendance/devices',id=str(device['id']),version='1',action='delete').status_code,302)
        self.login('geo.teacher');self.assertEqual(self.mark(device).status_code,401)
        self.assertEqual(len(self.daily()),1)
    def test_outside_inaccurate_stale_and_foreign_keys_cannot_mark(self):
        self.login();self.seed_fence();self.staff();device=self.register()
        base=dict(action='mark',device=str(device['id']),key=device['key'],event_id='fictional_geo_bad_001',direction='in',latitude='31.4',longitude='73.1',accuracy='5',captured_ms=str(self.stamp.timestamp()*1000))
        for change,expected in [({'latitude':'32.4'},403),({'accuracy':'101'},422),({'captured_ms':str((self.stamp-timedelta(minutes=2)).timestamp()*1000)},422),({'key':'x'*43},401)]:
            self.assertEqual(self.post('/workspace/attendance/geo-self',**{**base,**change}).status_code,expected)
        self.assertEqual(self.daily(),[])
    def test_owner_is_not_mistaken_for_an_employee(self):
        self.login();self.seed_fence();self.assertEqual(self.c.get('/workspace/attendance/geo-self').status_code,403)

    def test_holiday_suppresses_all_missing_attendance_alerts(self):
        self.login();self.alert_settings()
        self.tenant(lambda:db.session.add(self.Item(kind='calendar-holiday',scope='',name='fictional-day-off',data={'date':'2026-11-05','repeats':False})))
        self.post('/workspace/core/attendance-alerts',action='check')
        self.assertEqual(self.tenant(lambda:self.controls['alert'].query.count()),0)

    def test_monthly_editor_preserves_historical_inactive_status(self):
        self.login()
        def seed():
            db.session.add(self.Setting(key='attendance-acronyms',data={'staff':{'Late':False}}))
            db.session.add(self.ops['daily'](kind='staff',person_id=1,day=self.stamp.date(),status='Late',time_in='08:35'))
        self.tenant(seed)
        page=self.c.get('/workspace/core/hrm/monthly-attendance?month=2026-11&employee_id=1')
        self.assertEqual(page.status_code,200)
        self.assertIn(b'value="Late">Late (inactive historical status)',page.data)
        self.assertEqual(self.post('/workspace/core/hrm/monthly-attendance',employee_id='1',month='2026-11',**{'status_2026-11-05':'Late'}).status_code,302)
        self.assertEqual(self.post('/workspace/attendance/staff',day='2026-11-06',status_1='Late').status_code,422)
        self.assertEqual(self.daily()[0]['status'],'Late')

    def test_geo_event_id_cannot_be_reused_for_a_different_direction(self):
        self.login();self.seed_fence();self.staff();device=self.register();self.assertEqual(self.mark(device).status_code,201)
        response=self.post('/workspace/attendance/geo-self',action='mark',device=str(device['id']),key=device['key'],event_id='fictional_geo_event_001',direction='out',latitude='31.4',longitude='73.1',accuracy='5',captured_ms=str(self.stamp.timestamp()*1000))
        self.assertEqual(response.status_code,409);self.assertEqual(self.daily()[0]['time_out'],'')

    def test_deleting_employee_preserves_geo_history_without_reactivating_device(self):
        def seed():
            d=self.controls['device'](employee_id=1,campus='Campus A',name='Old fictional phone',digest='d'*64,active=True);db.session.add(d);db.session.flush()
            db.session.add(self.controls['event'](device_id=d.id,event_id='historical_geo_001',fingerprint='f'*64,outcome='Marked',reason='Fictional historical mark',distance=0,accuracy=5))
        self.tenant(seed)
        def remove():
            self.rm['employee'].query.filter_by(employee_id=1).delete();db.session.delete(db.session.get(Employee,1));db.session.flush()
            self.assertIsNone(db.session.get(self.controls['device'],1).employee_id)
            self.assertEqual(self.controls['event'].query.count(),1)
        self.tenant(remove)

    def test_configured_map_views_are_wired_without_loading_tiles_on_get(self):
        self.login();old=app.config.get('GEO_MAP_LAYERS')
        try:
            app.config['GEO_MAP_LAYERS']={'satellite':{'url':'https://tiles.example.invalid/{z}/{x}/{y}.png','attribution':'Fictional provider'},'hybrid':{'url':'https://tiles.example.invalid/{z}/{x}/{y}.png','overlay_url':'https://labels.example.invalid/{z}/{x}/{y}.png','attribution':'Fictional labels'}}
            page=self.c.get('/workspace/core/geo-attendance');self.assertEqual(page.status_code,200,page.data)
            self.assertIn(b'data-map-style="satellite"  title="Configured tile provider"',page.data)
            self.assertIn(b'https://tiles.example.invalid/',page.data);self.assertIn(b'data-geo-map-config',page.data)
        finally:app.config['GEO_MAP_LAYERS']=old

    def test_invalid_map_provider_configuration_does_not_enable_a_view(self):
        self.login();old=app.config.get('GEO_MAP_LAYERS')
        try:
            app.config['GEO_MAP_LAYERS']={'satellite':{'url':'http://127.0.0.1/{z}/{x}/{y}','attribution':'Invalid'}}
            page=self.c.get('/workspace/core/geo-attendance');self.assertEqual(page.status_code,200,page.data)
            self.assertIn(b'data-map-style="satellite" disabled',page.data);self.assertNotIn(b'http://127.0.0.1/',page.data)
        finally:app.config['GEO_MAP_LAYERS']=old
