"""Native gate enrollment binds the real record and institute incarnation."""
import unittest,hmac,hashlib,json
from flask import g
import tests.test_attendance_devices as fixture
from app import app,db,Student
class GateIdentityTests(unittest.TestCase):
    password=fixture.AttendanceDeviceTests.password
    key=fixture.AttendanceDeviceTests.key
    setUp=fixture.AttendanceDeviceTests.setUp
    tearDown=fixture.AttendanceDeviceTests.tearDown
    tenant=fixture.AttendanceDeviceTests.tenant
    headers=fixture.AttendanceDeviceTests.headers
    daily=fixture.AttendanceDeviceTests.daily
    def qr(self,typ='student',pid=1,number='D1'):
        namespace=self.tenant(lambda:app.extensions['identity_models']['institute'].query.filter_by(id=self.school).one().storage_key)
        return 'schoolflow:'+typ+':'+hmac.new(str(app.config['SECRET_KEY']).encode(),f'schoolflow:{typ}-qr:{namespace}:{pid}:{number}'.encode(),hashlib.sha256).hexdigest()
    def verify(self,qr=None,**headers):
        return self.c.post('/api/attendance/devices/1/identity',json={'qr_token':qr or self.qr()},headers=self.headers(**headers))
    def test_heartbeat_scope_is_stable_and_does_not_expose_biometric_data(self):
        a=self.c.post('/api/attendance/devices/1/heartbeat',json={},headers=self.headers()).json
        self.tenant(lambda:setattr(db.session.get(self.models['device'],1),'name','Renamed gate'))
        b=self.c.post('/api/attendance/devices/1/heartbeat',json={},headers=self.headers()).json
        self.assertEqual(a['scope_id'],b['scope_id']);self.assertEqual(len(a['scope_id']),64);self.assertNotIn('image',json.dumps(b));self.assertEqual(self.daily(),[])
    def test_exact_qr_verifies_identity_without_creating_attendance(self):
        a=self.verify();self.assertEqual(a.status_code,200,a.data);self.assertEqual(a.json['person_id'],1);self.assertEqual(a.json['name'],'Fictional pupil Campus A');self.assertEqual(len(a.json['identity_binding']),43)
        self.assertEqual(self.verify().json['identity_binding'],a.json['identity_binding']);self.assertEqual(self.daily(),[])
        staff=self.verify(self.qr('employee',1,'E1'));self.assertEqual(staff.status_code,200);self.assertNotEqual(staff.json['identity_binding'],a.json['identity_binding'])
    def test_verification_needs_both_credential_and_current_campus_qr(self):
        self.assertEqual(self.verify(Authorization='Bearer '+'x'*43).status_code,401)
        self.assertEqual(self.verify(self.qr(pid=2,number='D2')).status_code,404)
        self.assertEqual(self.verify('schoolflow:student:'+'a'*64).status_code,404)
        self.assertEqual(self.tenant(lambda:self.models['binding'].query.count()),0)
    def test_verified_binding_marks_and_stale_binding_does_not(self):
        verified=self.verify().json
        body=dict(event_id='bound_identity_001',qr_token=self.qr(),identity_binding='x'*43,direction='in',occurred_at=self.stamp.isoformat())
        url='/api/attendance/devices/1/events';headers=self.headers(**{'X-Device-Scope':verified['scope_id']})
        self.assertEqual(self.c.post(url,json=body,headers=headers).json['outcome'],'Not marked');self.assertEqual(self.daily(),[])
        body.update(event_id='bound_identity_002',identity_binding=verified['identity_binding']);r=self.c.post(url,json=body,headers=headers);self.assertEqual(r.status_code,201,r.data);self.assertEqual(r.json['outcome'],'Marked');self.assertEqual(len(self.daily()),1)
    def test_delete_recreate_same_numeric_id_and_number_invalidates_old_binding(self):
        qr=self.qr();old=self.verify(qr).json
        def recreate():
            self.rm['student'].query.filter_by(student_id=1).delete();db.session.delete(db.session.get(Student,1));db.session.flush()
            self.assertEqual(self.models['binding'].query.count(),0)
            db.session.add(Student(id=1,admission_no='D1',name='Different fictional pupil',class_name='One',status='Active'));db.session.flush();db.session.add(self.rm['student'](student_id=1,data={'campus':'Campus A'}))
        self.tenant(recreate)
        body=dict(event_id='recreated_identity_001',qr_token=qr,identity_binding=old['identity_binding'],direction='in',occurred_at=self.stamp.isoformat())
        r=self.c.post('/api/attendance/devices/1/events',json=body,headers=self.headers(**{'X-Device-Scope':old['scope_id']}));self.assertEqual(r.json['outcome'],'Not marked');self.assertEqual(self.daily(),[])
        current=self.verify(qr).json;self.assertNotEqual(current['identity_binding'],old['identity_binding']);self.assertEqual(current['name'],'Different fictional pupil')
    def test_mismatched_scope_header_refuses_before_any_scan_write(self):
        response=self.c.post('/api/attendance/devices/1/events',json=dict(event_id='scope_mismatch_001',person_kind='student',person_id=1,direction='in',occurred_at=self.stamp.isoformat()),headers=self.headers(**{'X-Device-Scope':'0'*64}))
        self.assertEqual(response.status_code,409);self.assertEqual(self.tenant(lambda:self.models['scan'].query.count()),0)
    def test_suspended_gate_cannot_enroll_new_identity(self):
        self.tenant(lambda:setattr(db.session.get(self.models['device'],1),'status','Suspended'));self.assertEqual(self.verify().status_code,403);self.assertEqual(self.tenant(lambda:self.models['binding'].query.count()),0)
