"""Explicit fictional-only bootstrap for the isolated Gate trial service.

Not imported or invoked by the normal SchoolFlow server startup.
Credentials are supplied privately through the service environment.
"""
import hashlib
import re
from flask import g
from attendance_devices import DEFAULTS

CODE = 'GATE-TRIAL'
EMAIL = 'owner@gate-trial.invalid'
NAME = 'SchoolFlow Gate — Fictional Trial Only'
CAMPUS = 'Fictional Gate Campus'


def bootstrap(app, db, Student, Employee, environ):
    if environ.get('SCHOOLFLOW_GATE_TRIAL') != '1' or app.config['PUBLIC_DEMO_ENABLED']:
        raise RuntimeError('Trial startup requires explicit opt-in and disabled public demo.')
    password = environ.get('GATE_TRIAL_PASSWORD', '')
    key = environ.get('GATE_TRIAL_KEY', '')
    if not 20 <= len(password) <= 128 or not re.fullmatch(r'[A-Za-z0-9_-]{43}', key):
        raise RuntimeError('Supply private trial credentials in the service environment.')
    if len(environ.get('SECRET_KEY', '')) < 40:
        raise RuntimeError('Supply a persistent private trial server secret.')
    Institute = app.extensions['identity_models']['institute']
    # Refuse an existing control store belonging to anything else. The trial
    # launcher must never repurpose the main deployment's school databases.
    schools = Institute.query.all()
    if schools:
        if len(schools) != 1 or schools[0].code != CODE or schools[0].name != NAME:
            raise RuntimeError('Refusing to seed a store containing other institutes.')
        return schools[0].id
    helpers = app.extensions['identity_helpers']
    school = helpers['provision'](CODE, NAME, EMAIL, password)
    school_id = school.id
    engine = helpers['engine'](school_id)
    rm = app.extensions['record_models']
    Item = app.extensions['school_settings_models']['item']
    Setting = app.extensions['school_settings_models']['setting']
    Device = app.extensions['attendance_device_models']['device']
    # A request context owns tenant routing, so no tenant engine survives into
    # subsequent control-store queries or the Gunicorn startup process.
    with app.test_request_context('/'):
        g.institute_engine = engine
        db.session.remove()
        try:
            db.session.add_all([
                rm['settings'](category='campus', value=CAMPUS, class_name=''),
                rm['settings'](category='class_name', value='Trial Class', class_name=''),
            ])
            student = Student(admission_no='TRIAL-001', name='Fictional Gate Trial Person', class_name='Trial Class', status='Active')
            employee = Employee(employee_no='TRIAL-E01', name='Fictional Gate Trial Staff', role='Teacher', status='Active')
            db.session.add_all([student, employee])
            db.session.flush()
            db.session.add_all([
                rm['student'](student_id=student.id, data={'campus': CAMPUS}),
                rm['employee'](employee_id=employee.id, data={'campus': CAMPUS}),
                Item(kind='student-shift', scope=CAMPUS, name='Fictional all-day trial shift', data={'classes': ['Trial Class'], 'section': '', 'days': {str(i): {'off': False, 'in': '00:00', 'out': '23:59'} for i in range(7)}}),
                Setting(key='attendance-devices', data={**DEFAULTS, 'student_channel': 'none', 'staff_channel': 'none'}),
                Device(kind='face', serial='fictional-gate-trial', name='Fictional Android Trial Gate', campus=CAMPUS, status='Pending', marks='both', token_digest=hashlib.sha256(key.encode()).hexdigest()),
            ])
            db.session.commit()
        finally:
            db.session.remove()
    return school_id
