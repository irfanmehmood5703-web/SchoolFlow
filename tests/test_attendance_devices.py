"""Device isolation, real marks, rule safety, duplicate handling and gate history."""
import hashlib,json,os,re,tempfile,unittest
from datetime import datetime,date,timedelta,timezone
from unittest.mock import patch
from zoneinfo import ZoneInfo
from flask import g
from werkzeug.security import generate_password_hash
os.environ['DATABASE_URL']='sqlite:///:memory:'
from app import app,db,Student,Employee
from attendance_devices import DEFAULTS

class AttendanceDeviceTests(unittest.TestCase):
    password='Fictional-device-owner-password-2026'
    key='FictionalDeviceConnectionKey_1234567890abcde'
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory();app.config.update(TESTING=True,IDENTITY_ENFORCE_IN_TESTS=True,INSTITUTE_DATABASE_DIR=self.directory.name,SECRET_KEY='fictional-device-tests')
        self.ctx=app.app_context();self.ctx.push();db.drop_all();db.create_all();self.models=app.extensions['attendance_device_models'];self.rm=app.extensions['record_models'];self.ops=app.extensions['ops_models'];self.Setting=app.extensions['school_settings_models']['setting'];self.Item=app.extensions['school_settings_models']['item']
        self.school=app.extensions['identity_helpers']['provision']('DEVICE-TEST','Fictional device school','owner@example.invalid',self.password).id
        def seed():
            for c in ('Campus A','Campus B'):db.session.add(self.rm['settings'](category='campus',value=c,class_name=''))
            for c in ('One','Two'):db.session.add(self.rm['settings'](category='class_name',value=c,class_name=''))
            for i,c in enumerate(('Campus A','Campus B'),1):
                person=Student(admission_no='D'+str(i),name='Fictional pupil '+c,class_name='One',status='Active');db.session.add(person);db.session.flush();db.session.add(self.rm['student'](student_id=person.id,data={'campus':c}))
            person=Employee(employee_no='E1',name='Fictional device teacher',role='Teacher',status='Active');db.session.add(person);db.session.flush();db.session.add(self.rm['employee'](employee_id=person.id,data={'campus':'Campus A'}))
            days={str(i):dict(off=False,**{'in':'08:00','out':'13:00'}) for i in range(7)}
            for c in ('Campus A','Campus B'):db.session.add(self.Item(kind='student-shift',scope=c,name='Fictional shift',data=dict(classes=['One'],section='',days=days)))
            a=self.Item(kind='shift-template',scope='',name='Morning IN',data=dict(direction='in',days={str(i):dict(off=False,time='08:00') for i in range(7)}));b=self.Item(kind='shift-template',scope='',name='Morning OUT',data=dict(direction='out',days={str(i):dict(off=False,time='13:00') for i in range(7)}));db.session.add_all([a,b]);db.session.flush();db.session.add(self.Setting(key='hrm:shift-assignment',data={'1':{str(i):{'in':str(a.id),'out':str(b.id)} for i in range(7)}}))
            for c in ('Campus A','Campus B'):db.session.add(self.models['device'](kind='face',serial='fictional-'+c[-1],name='Fictional gate '+c[-1],campus=c,status='Pending',marks='both',token_digest=hashlib.sha256(self.key.encode()).hexdigest()))
        self.tenant(seed);self.c=app.test_client();self.stamp=datetime(2026,11,5,8,35,tzinfo=ZoneInfo('Asia/Karachi')).astimezone(timezone.utc);self.clock=patch('attendance_devices.utc_now',side_effect=lambda:self.stamp);self.clock.start()
    def tearDown(self):
        self.clock.stop();g.staff_principal=None;g.access_campuses=None;db.session.remove();db.drop_all();self.ctx.pop();app.config.update(IDENTITY_ENFORCE_IN_TESTS=False,INSTITUTE_DATABASE_DIR=None);self.directory.cleanup()
    def tenant(self,fn):
        with app.test_request_context('/'):
            g.staff_principal=None;g.access_campuses=None;g.attendance_device_actor=None;g.institute_engine=app.extensions['identity_helpers']['engine'](self.school);db.session.remove();result=fn();db.session.commit();db.session.remove()
        g.pop('institute_engine',None);return result
    def token(self):
        with self.c.session_transaction() as cookie:return cookie['record_csrf']
    def login(self,name='owner@example.invalid'):
        self.c.get('/auth/institute');self.c.post('/auth/institute',data={'_csrf':self.token(),'code':'DEVICE-TEST'});return self.c.post('/auth/login',data={'_csrf':self.token(),'email':name,'password':self.password})
    def headers(self,**changes):
        result={'X-Institute-Code':'DEVICE-TEST','Authorization':'Bearer '+self.key};result.update(changes);return result
    def event(self,did=1,**changes):
        data=dict(event_id='fictional_event_001',person_kind='student',person_id=1,direction='in',occurred_at=self.stamp.isoformat());data.update(changes)
        return self.c.post('/api/attendance/devices/'+str(did)+'/events',json=data,headers=self.headers())
    def daily(self):return self.tenant(lambda:[dict(kind=r.kind,pid=r.person_id,status=r.status,time_in=r.time_in,time_out=r.time_out) for r in self.ops['daily'].query.order_by(self.ops['daily'].id).all()])
    def config(self,**changes):
        def save():
            row=db.session.get(self.Setting,'attendance-devices');data={**DEFAULTS,**changes}
            if row:row.data=data
            else:db.session.add(self.Setting(key='attendance-devices',data=data))
        self.tenant(save)
    def settings_data(self,**changes):
        result={'_csrf':self.token(),'action':'save','version':'0','student_channel':'none','staff_channel':'none','student_absent':'60','student_late':'30','staff_absent':'0','staff_late':'0','early_minutes':'0'};result.update(changes);return result
    def test_settings_and_gate_pages_are_read_only_and_empty_scans_are_honest(self):
        self.login()
        before=self.tenant(lambda:(self.Setting.query.count(),self.ops['audit'].query.count(),self.models['scan'].query.count()))
        for path in ('/workspace/core/qr-attendance','/workspace/core/face-gates','/workspace/core/face-gates/scans'):
            response=self.c.get(path);self.assertEqual(response.status_code,200,response.data)
        self.assertIn(b'No attendance scans',self.c.get('/workspace/core/face-gates/scans').data)
        self.assertEqual(before,self.tenant(lambda:(self.Setting.query.count(),self.ops['audit'].query.count(),self.models['scan'].query.count())))
    def test_save_rules_versions_classes_and_timing_validation(self):
        self.login();url='/workspace/core/qr-attendance';data=self.settings_data(classes=json.dumps(['Campus A','One']),student_only_absent='1',auto_staff_absent='1')
        self.assertEqual(self.c.post(url,data=data).status_code,302);self.assertEqual(self.c.post(url,data=data).status_code,422)
        saved=self.tenant(lambda:dict(db.session.get(self.Setting,'attendance-devices').data));self.assertEqual(saved['classes'],[['Campus A','One']]);self.assertTrue(saved['auto_staff_absent'])
        for values in [dict(version='1',student_late='90'),dict(version='1',classes='{"bad":1}'),dict(version='1',classes='[[1],"One"]'),dict(version='1',early_minutes='-1'),dict(version='1',staff_channel='provider')]:self.assertEqual(self.c.post(url,data=self.settings_data(**values)).status_code,422)
        self.assertEqual(self.c.post(url,data=self.settings_data(_csrf='')).status_code,400)
    def test_heartbeat_requires_per_device_credential_and_records_no_attendance(self):
        url='/api/attendance/devices/1/heartbeat'
        self.assertEqual(self.c.post(url,json={}).status_code,401)
        self.assertEqual(self.c.post(url,json={},headers=self.headers(Authorization='Bearer '+'x'*43)).status_code,401)
        response=self.c.post(url,json={'model':'Fictional tablet','client_version':'test-1'},headers=self.headers());self.assertEqual(response.status_code,200)
        data=self.tenant(lambda:dict(last_seen=self.models['device'].query.filter_by(id=1).one().last_seen,last_marked=self.models['device'].query.filter_by(id=1).one().last_marked,revision=self.models['device'].query.filter_by(id=1).one().revision));self.assertIsNotNone(data['last_seen']);self.assertIsNone(data['last_marked']);self.assertEqual(data['revision'],1);self.assertEqual(self.daily(),[])
    def test_pending_gate_marks_late_once_and_replays_are_idempotent(self):
        response=self.event();self.assertEqual(response.status_code,201,response.data);self.assertEqual(response.json['outcome'],'Marked');self.assertEqual(self.daily()[0]['status'],'Late')
        self.assertEqual(self.event().json['replayed'],True);self.assertEqual(self.tenant(lambda:self.models['scan'].query.count()),1)
        self.assertEqual(self.event(direction='out').status_code,409)
        self.assertEqual(self.event(event_id='fictional_event_002').json['outcome'],'Already marked');self.assertEqual(len(self.daily()),1)
        audit=self.tenant(lambda:self.ops['audit'].query.filter_by(action='Device attendance marked').one().data);self.assertEqual(audit['_activity_actor']['kind'],'Device');self.assertEqual(audit['_activity_actor']['label'],'Fictional gate A')
    def test_cross_campus_unknown_and_inactive_people_never_mark(self):
        self.assertEqual(self.event(person_id=2).json['outcome'],'Not marked');self.assertEqual(self.daily(),[])
        saved=self.tenant(lambda:(self.models['scan'].query.one().person_id,self.models['scan'].query.one().person_name));self.assertIsNone(saved[0]);self.assertEqual(saved[1],'')
        self.assertEqual(self.event(person_id=999,event_id='unknown_999').json['reason'],'Person is unavailable for this gate.')
        self.tenant(lambda:setattr(db.session.get(Student,1),'status','Inactive'));self.assertEqual(self.event(event_id='inactive_001').json['outcome'],'Not marked')
    def test_suspension_and_marking_direction_are_enforced(self):
        self.tenant(lambda:setattr(db.session.get(self.models['device'],1),'status','Suspended'));self.assertEqual(self.event().json['outcome'],'Not marked')
        self.tenant(lambda:(setattr(db.session.get(self.models['device'],1),'status','Approved'),setattr(db.session.get(self.models['device'],1),'marks','out')));self.assertEqual(self.event(event_id='wrong_direction_001').json['outcome'],'Not marked');self.assertEqual(self.daily(),[])
    def test_stale_future_naive_and_biometric_payloads_do_not_mark(self):
        self.assertEqual(self.event(occurred_at=(self.stamp-timedelta(minutes=16)).isoformat()).json['outcome'],'Not marked')
        self.assertEqual(self.event(event_id='future_001',occurred_at=(self.stamp+timedelta(minutes=2)).isoformat()).json['outcome'],'Not marked')
        self.assertEqual(self.event(occurred_at='2026-11-05T08:35:00').status_code,422)
        self.assertEqual(self.event(face_image='never-store-this').status_code,422);self.assertEqual(self.daily(),[])
    def test_manual_attendance_is_preserved_and_out_requires_in(self):
        self.assertEqual(self.event(direction='out').json['outcome'],'Not marked')
        self.tenant(lambda:db.session.add(self.ops['daily'](kind='student',person_id=1,day=date(2026,11,5),status='Leave')))
        self.assertEqual(self.event(event_id='manual_preserved_001').json['outcome'],'Not marked');self.assertEqual(self.daily()[0]['status'],'Leave')
    def test_staff_early_out_becomes_short_leave_and_duplicate_out_is_stable(self):
        self.config(early_short=True,early_minutes=10,staff_channel='none');self.assertEqual(self.event(person_kind='staff').json['outcome'],'Marked')
        self.stamp=self.stamp.replace(hour=7,minute=20) # 12:20 Pakistan
        self.assertEqual(self.event(person_kind='staff',direction='out',event_id='staff_out_001').json['outcome'],'Marked');self.assertEqual(self.daily()[0]['status'],'Short Leave')
        self.assertEqual(self.event(person_kind='staff',direction='out',event_id='staff_out_002').json['outcome'],'Already marked');self.assertEqual(self.daily()[0]['time_out'],'12:20')
    def test_auto_absent_is_opt_in_scoped_today_and_repeat_safe(self):
        self.stamp=self.stamp.replace(hour=4,minute=5) # 09:05 Pakistan
        def run():return app.extensions['attendance_device_helpers']['tick'](self.stamp)
        self.assertEqual(self.tenant(run),0);self.assertEqual(self.daily(),[])
        self.config(classes=[['Campus A','One']],student_channel='none');self.assertEqual(self.tenant(run),1);self.assertEqual(self.daily(),[dict(kind='student',pid=1,status='Absent',time_in='',time_out='')]);self.assertEqual(self.tenant(run),0)
        self.assertEqual(self.event().json['outcome'],'Marked');self.assertEqual(self.daily()[0]['status'],'Late')
    def test_auto_absent_skips_holidays_and_locked_staff_dates(self):
        self.stamp=self.stamp.replace(hour=4,minute=5);self.config(classes=[['Campus A','One']],auto_staff_absent=True,student_channel='none',staff_channel='none')
        def prepare():
            db.session.add(self.Item(kind='calendar-holiday',scope='Campus A',name='fictional holiday',data={'date':'2026-11-05','repeats':False}));db.session.add(self.Setting(key='hrm:attendance-lock',data={'daily':'2026-11-05'}))
        self.tenant(prepare);self.assertEqual(self.tenant(lambda:app.extensions['attendance_device_helpers']['tick'](self.stamp)),0);self.assertEqual(self.daily(),[])
    def test_gate_forms_rotate_keys_remove_without_discarding_history_and_reject_stale(self):
        self.login();url='/workspace/core/attendance-devices/1';token=self.token()
        response=self.c.post(url,data={'_csrf':token,'version':'1','action':'connect','confirm':'yes'});self.assertEqual(response.status_code,200,response.data)
        newkey=re.search(rb'<code[^>]*>([A-Za-z0-9_-]{40,60})</code>',response.data).group(1).decode();self.assertNotEqual(newkey,self.key)
        self.assertEqual(self.event().status_code,401)
        self.assertEqual(self.c.post('/api/attendance/devices/1/heartbeat',json={},headers=self.headers(Authorization='Bearer '+newkey)).status_code,200)
        self.assertEqual(self.c.post(url,data={'_csrf':token,'version':'1','action':'rename','name':'Stale'}).status_code,422)
        self.assertEqual(self.c.post(url,data={'_csrf':token,'version':'2','action':'remove','confirm':'yes'}).status_code,302)
        self.assertEqual(self.c.post('/api/attendance/devices/1/heartbeat',json={},headers=self.headers(Authorization='Bearer '+newkey)).status_code,401);self.assertEqual(self.tenant(lambda:self.models['device'].query.count()),2)
    def test_register_biometric_ids_and_duplicate_face_gate_are_controlled(self):
        self.login();url='/workspace/core/qr-attendance';data={'_csrf':self.token(),'action':'serials','campus':'Campus A','serials':'BIO-1, BIO-2'}
        self.assertEqual(self.c.post(url,data=data).status_code,302);self.assertEqual(self.tenant(lambda:self.models['device'].query.filter_by(kind='biometric').count()),2)
        data['campus']='Campus B';self.assertEqual(self.c.post(url,data=data).status_code,422)
        self.assertEqual(self.c.post('/workspace/core/face-gates',data={'_csrf':self.token(),'name':'Duplicate','serial':'fictional-A','campus':'Campus A','marks':'both'}).status_code,422)
    def test_scan_history_name_person_dates_and_staff_campus_isolation(self):
        self.event();self.event(did=2,person_id=2,event_id='campus_b_scan_001');self.login()
        response=self.c.get('/workspace/core/face-gates/scans?from=2026-11-05&to=2026-11-05&person=1&kind=student');self.assertEqual(response.status_code,200);self.assertIn(b'Fictional pupil Campus A',response.data);self.assertNotIn(b'Fictional pupil Campus B',response.data)
        Staff=app.extensions['staff_account_model']
        self.tenant(lambda:db.session.add(Staff(employee_id=1,username='device.viewer',password_hash=generate_password_hash(self.password),active=True,data={'campuses':['Campus A'],'permissions':{'attendance.view':['Campus A']}})))
        self.assertEqual(self.login('device.viewer').status_code,302)
        response=self.c.get('/workspace/core/face-gates/scans?from=2026-11-05&to=2026-11-05');self.assertEqual(response.status_code,200);self.assertNotIn(b'Fictional pupil Campus B',response.data);self.assertNotIn(b'Fictional gate B',response.data)
        self.assertEqual(self.c.get('/workspace/core/qr-attendance').status_code,403)
    def test_manual_save_after_device_scan_prevents_automatic_overwrite(self):
        self.assertEqual(self.event(person_kind='staff').json['outcome'],'Marked');self.login()
        response=self.c.post('/workspace/attendance/staff',data={'_csrf':self.token(),'day':'2026-11-05','status_1':'Present','time_in_1':'08:00','time_out_1':'','lectures_1':'0'});self.assertEqual(response.status_code,302,response.data)
        self.config(auto_staff_short=True,staff_channel='none');self.stamp=self.stamp.replace(hour=9,minute=0)
        self.assertEqual(self.tenant(lambda:app.extensions['attendance_device_helpers']['tick'](self.stamp,force=True)),0)
        self.assertEqual(self.event(person_kind='staff',direction='out',event_id='after_manual_001').json['outcome'],'Not marked');self.assertEqual(self.daily()[0]['status'],'Present')
    def test_schoolflow_student_and_employee_qr_tokens_resolve_only_in_their_campus(self):
        namespace=self.tenant(lambda:app.extensions['identity_models']['institute'].query.filter_by(id=self.school).one().storage_key)
        def qr(typ,pid,number):return 'schoolflow:'+typ+':'+hmac.new(str(app.config['SECRET_KEY']).encode(),f'schoolflow:{typ}-qr:{namespace}:{pid}:{number}'.encode(),hashlib.sha256).hexdigest()
        import hmac
        body={'event_id':'student_qr_001','qr_token':qr('student',1,'D1'),'direction':'in','occurred_at':self.stamp.isoformat()}
        response=self.c.post('/api/attendance/devices/1/events',json=body,headers=self.headers());self.assertEqual(response.status_code,201,response.data);self.assertEqual(response.json['outcome'],'Marked')
        body.update(event_id='other_campus_qr',qr_token=qr('student',2,'D2'));self.assertEqual(self.c.post('/api/attendance/devices/1/events',json=body,headers=self.headers()).json['outcome'],'Not marked')
        body.update(event_id='employee_qr_001',qr_token=qr('employee',1,'E1'));self.assertEqual(self.c.post('/api/attendance/devices/1/events',json=body,headers=self.headers()).json['outcome'],'Marked');self.assertEqual(len(self.daily()),2)
        self.assertEqual(self.c.post('/api/attendance/devices/1/events',json={**body,'person_id':1},headers=self.headers()).status_code,422)
        self.assertNotIn(body['qr_token'],self.tenant(lambda:json.dumps([s.fingerprint for s in self.models['scan'].query.all()])))
    def test_no_shift_off_day_and_exact_late_boundary(self):
        self.stamp=self.stamp.replace(hour=3,minute=30)
        self.assertEqual(self.event().json['outcome'],'Marked');self.assertEqual(self.daily()[0]['status'],'Present')
        def off():
            row=self.Item.query.filter_by(kind='student-shift',scope='Campus B').one();row.data={**row.data,'days':{'3':{'off':True,'in':'08:00','out':'13:00'}}}
        self.tenant(off);self.assertEqual(self.event(did=2,person_id=2,event_id='off_day_001').json['outcome'],'Not marked')
        self.tenant(lambda:self.Item.query.filter_by(kind='student-shift',scope='Campus B').delete());self.assertEqual(self.event(did=2,person_id=2,event_id='no_shift_001').json['outcome'],'Not marked')
    def test_missing_out_short_leave_is_corrected_by_a_later_real_out(self):
        self.config(auto_staff_short=True,staff_channel='none');self.assertEqual(self.event(person_kind='staff').json['outcome'],'Marked');self.stamp=self.stamp.replace(hour=8,minute=10)
        self.assertEqual(self.tenant(lambda:app.extensions['attendance_device_helpers']['tick'](self.stamp,force=True)),1);self.assertEqual(self.daily()[0]['status'],'Short Leave')
        self.stamp+=timedelta(minutes=1);self.assertEqual(self.event(person_kind='staff',direction='out',event_id='late_out_001').json['outcome'],'Marked');self.assertEqual(self.daily()[0]['status'],'Late')
    def test_only_absent_notifications_are_queued_once_without_provider_delivery(self):
        self.config(classes=[['Campus A','One']]);self.assertEqual(self.event().json['outcome'],'Marked');self.assertEqual(self.tenant(lambda:self.ops['workflow'].query.filter_by(kind='message').count()),0)
        def other():
            p=Student(admission_no='D3',name='Another fictional pupil',class_name='One',status='Active');db.session.add(p);db.session.flush();db.session.add(self.rm['student'](student_id=p.id,data={'campus':'Campus A'}))
        self.tenant(other);self.stamp=self.stamp.replace(hour=4,minute=5)
        self.assertEqual(self.tenant(lambda:app.extensions['attendance_device_helpers']['tick'](self.stamp)),1)
        messages=self.tenant(lambda:[(r.status,r.data['ids'],r.data['preferences']) for r in self.ops['workflow'].query.filter_by(kind='message').all()]);self.assertEqual(len(messages),1);self.assertEqual(messages[0][0],'Provider not configured');self.assertEqual(messages[0][1],[3]);self.assertTrue(messages[0][2]['app_sms'])
        self.assertEqual(self.tenant(lambda:app.extensions['attendance_device_helpers']['tick'](self.stamp,force=True)),0);self.assertEqual(self.tenant(lambda:self.ops['workflow'].query.filter_by(kind='message').count()),1)
    def test_device_key_does_not_authenticate_to_another_institute(self):
        g.institute_engine=None;g.staff_principal=None;g.access_campuses=None;db.session.remove();other=app.extensions['identity_helpers']['provision']('DEVICE-OTHER','Other fictional school','other@example.invalid',self.password).id
        with app.test_request_context('/'):
            g.institute_engine=app.extensions['identity_helpers']['engine'](other);db.session.remove();db.session.add(self.models['device'](kind='face',serial='other',name='Other private gate',campus='Other Campus',status='Pending',token_digest=hashlib.sha256(('z'*43).encode()).hexdigest()));db.session.commit();db.session.remove()
        g.institute_engine=None
        response=self.c.post('/api/attendance/devices/1/heartbeat',json={},headers=self.headers(**{'X-Institute-Code':'DEVICE-OTHER'}));self.assertEqual(response.status_code,401)
        self.assertEqual(self.event().json['outcome'],'Marked');self.assertEqual(len(self.daily()),1)
    def test_scan_filters_invalid_limits_clear_person_and_scanner_page(self):
        self.login()
        self.assertEqual(self.c.get('/workspace/core/qr-attendance/scanner').status_code,200)
        self.assertEqual(self.c.get('/workspace/core/face-gates/scans?person=&kind=').status_code,200)
        for suffix in ('rows=99999','from=bad','from=2026-11-06&to=2026-11-05','person=1','person=-1','kind=owner','from=0001-01-01&to=0001-01-01','from=9999-12-31&to=9999-12-31'):self.assertEqual(self.c.get('/workspace/core/face-gates/scans?'+suffix).status_code,422)
    def test_bulk_auto_absent_reads_are_bounded_and_do_not_load_photos(self):
        def people():
            for i in range(3,103):
                p=Student(admission_no='BULK-'+str(i),name='Fictional bulk '+str(i),class_name='One',status='Active');db.session.add(p);db.session.flush();db.session.add(self.rm['student'](student_id=p.id,data={'campus':'Campus A'}))
        self.tenant(people);self.config(classes=[['Campus A','One']],student_channel='none');self.stamp=self.stamp.replace(hour=4,minute=5)
        from sqlalchemy import event
        engine=app.extensions['identity_helpers']['engine'](self.school);reads=[]
        def tally(conn,cursor,statement,parameters,context,executemany):
            if statement.lstrip().upper().startswith('SELECT'):reads.append(statement)
        event.listen(engine,'before_cursor_execute',tally)
        try:count=self.tenant(lambda:app.extensions['attendance_device_helpers']['tick'](self.stamp))
        finally:event.remove(engine,'before_cursor_execute',tally)
        self.assertEqual(count,101);self.assertLessEqual(len(reads),25,reads);self.assertFalse(any('record_file' in sql for sql in reads))
    def test_simultaneous_same_scan_produces_one_daily_record_and_one_log(self):
        from concurrent.futures import ThreadPoolExecutor
        from sqlalchemy import create_engine,select
        original=db.engines[None];control=create_engine('sqlite:///'+self.directory.name+'/control.db',connect_args={'timeout':20});tables=[t for t in db.metadata.sorted_tables if t.info.get('identity_control')]
        db.session.remove();db.metadata.create_all(control,tables=tables)
        with original.connect() as source,control.begin() as target:
            for table in tables:
                records=[dict(r) for r in source.execute(select(table)).mappings()]
                if records:target.execute(table.insert(),records)
        db.engines[None]=control;body=dict(event_id='concurrent_scan_001',person_kind='student',person_id=1,direction='in',occurred_at=self.stamp.isoformat())
        try:
            def scan(_):return app.test_client().post('/api/attendance/devices/1/events',json=body,headers=self.headers()).status_code
            with ThreadPoolExecutor(max_workers=2) as pool:statuses=list(pool.map(scan,range(2)))
            self.assertEqual(sorted(statuses),[200,201]);self.assertEqual(len(self.daily()),1);self.assertEqual(self.tenant(lambda:self.models['scan'].query.count()),1)
        finally:db.session.remove();db.engines[None]=original;control.dispose()
