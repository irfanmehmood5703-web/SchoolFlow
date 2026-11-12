"""Isolated trial provisioning and Android-compatible protocol, no real data."""
import hashlib
import hmac
import tempfile
import unittest
from datetime import datetime, timezone
from flask import g
from app import app, db, Student, Employee
from gate_trial import bootstrap, CODE, EMAIL, NAME


class GateTrialTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.old = {k: app.config.get(k) for k in ('TESTING', 'PUBLIC_DEMO_ENABLED', 'IDENTITY_ENFORCE_IN_TESTS', 'INSTITUTE_DATABASE_DIR', 'SECRET_KEY')}
        app.config.update(TESTING=True, PUBLIC_DEMO_ENABLED=False, IDENTITY_ENFORCE_IN_TESTS=True, INSTITUTE_DATABASE_DIR=self.directory.name, SECRET_KEY='fictional-trial-server-secret-for-isolated-tests')
        self.ctx = app.app_context(); self.ctx.push(); db.drop_all(); db.create_all()
        self.env = {'SCHOOLFLOW_GATE_TRIAL': '1', 'GATE_TRIAL_PASSWORD': 'fictional-trial-owner-password-12345', 'GATE_TRIAL_KEY': 'f' * 43, 'SECRET_KEY': app.config['SECRET_KEY']}

    def tearDown(self):
        db.session.remove(); db.drop_all(); self.ctx.pop(); app.config.update(self.old); self.directory.cleanup()

    def seed(self):
        return bootstrap(app, db, Student, Employee, self.env)

    def test_requires_explicit_opt_in_no_demo_and_private_secrets(self):
        for changed in ({'SCHOOLFLOW_GATE_TRIAL': ''}, {'GATE_TRIAL_PASSWORD': ''}, {'GATE_TRIAL_KEY': ''}, {'SECRET_KEY': ''}):
            with self.assertRaises(RuntimeError): bootstrap(app, db, Student, Employee, {**self.env, **changed})
        app.config['PUBLIC_DEMO_ENABLED'] = True
        with self.assertRaises(RuntimeError): self.seed()
        self.assertEqual(app.extensions['identity_models']['institute'].query.count(), 0)

    def test_does_not_reseed_existing_enrollment_or_rotate_credentials(self):
        school = self.seed(); self.assertEqual(self.seed(), school)
        with app.test_request_context('/'):
            g.institute_engine = app.extensions['identity_helpers']['engine'](school); db.session.remove()
            self.assertEqual(Student.query.count(), 1)
            self.assertEqual(app.extensions['attendance_device_models']['device'].query.count(), 1)
            self.assertEqual(app.extensions['school_settings_models']['setting'].query.filter_by(key='attendance-devices').one().data['student_channel'], 'none')
            db.session.remove()

    def test_explicit_public_demo_keeps_private_gate_records_separate(self):
        app.config['PUBLIC_DEMO_ENABLED'] = True
        self.env['GATE_TRIAL_ALLOW_PUBLIC_DEMO'] = '1'
        self.seed()
        client = app.test_client()
        landing = client.get('/')
        self.assertIn(b'Explore the test demo', landing.data)
        with client.session_transaction() as session:
            token = session['record_csrf']
        self.assertEqual(client.post('/auth/demo', data={'_csrf': token}).status_code, 302)
        with client.session_transaction() as session:
            self.assertTrue(session['demo'])
            self.assertNotIn('institute_id', session)
        page = client.get('/records/student')
        self.assertEqual(page.status_code, 200)
        self.assertNotIn(b'Fictional Gate Trial Person', page.data)
        self.assertIn(b'SchoolFlow Demo', page.data)
        self.assertEqual(client.get('/workspace/core/institute').status_code, 200)

    def test_refuses_store_belonging_to_other_school(self):
        app.extensions['identity_helpers']['provision']('OTHER-SCHOOL', 'Other fictional school', 'owner@example.invalid', self.env['GATE_TRIAL_PASSWORD'])
        with self.assertRaises(RuntimeError): self.seed()

    def test_native_qr_enrollment_and_exact_event_replay(self):
        self.seed(); school = app.extensions['identity_models']['institute'].query.filter_by(code=CODE).one()
        qr = 'schoolflow:student:' + hmac.new(app.config['SECRET_KEY'].encode(), f'schoolflow:student-qr:{school.storage_key}:1:TRIAL-001'.encode(), hashlib.sha256).hexdigest()
        client = app.test_client(); headers = {'X-Institute-Code': CODE, 'Authorization': 'Bearer ' + self.env['GATE_TRIAL_KEY']}
        heartbeat = client.post('/api/attendance/devices/1/heartbeat', json={}, headers=headers)
        self.assertEqual(heartbeat.status_code, 200, heartbeat.data)
        headers['X-Device-Scope'] = heartbeat.json['scope_id']
        verified = client.post('/api/attendance/devices/1/identity', json={'qr_token': qr}, headers=headers)
        self.assertEqual(verified.status_code, 200, verified.data)
        body = {'event_id': 'fictional_trial_protocol_001', 'qr_token': qr, 'identity_binding': verified.json['identity_binding'], 'direction': 'in', 'occurred_at': datetime.now(timezone.utc).isoformat()}
        response = client.post('/api/attendance/devices/1/events', json=body, headers=headers)
        self.assertEqual(response.status_code, 201, response.data); self.assertEqual(response.json['outcome'], 'Marked')
        replay = client.post('/api/attendance/devices/1/events', json=body, headers=headers)
        self.assertTrue(replay.json['replayed']); self.assertEqual(response.json['id'], replay.json['id'])
