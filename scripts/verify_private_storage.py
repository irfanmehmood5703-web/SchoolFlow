"""CI-only process restart check using a disposable PostgreSQL service."""
import os,subprocess,sys
from pathlib import Path
if os.environ.get('SCHOOLFLOW_PRIVATE_STORAGE_QA')!='1':raise SystemExit('Run only against the disposable private-account CI database.')
root=Path(__file__).resolve().parent.parent
common="""
import os
os.environ['DATABASE_URL']='sqlite:///:memory:'
from app import app,db
from flask import g
"""
create=common+"""
with app.app_context():
 h=app.extensions['identity_helpers']
 assert h['control_engine']().dialect.name=='postgresql'
 s=h['provision']('RESTART-QA','Persistent private school','qa@example.invalid','Fictional-restart-password')
 with app.test_request_context('/'):
  g.institute_engine=h['engine'](s.id)
  Student=__import__('app').Student
  db.session.add(Student(name='Fictional retained student',admission_no='RETAIN-1'));db.session.commit()
 print('First process: private school and student saved.')
"""
read=common+"""
with app.app_context():
 h=app.extensions['identity_helpers'];School=app.extensions['identity_models']['institute']
 s=School.query.filter_by(code='RESTART-QA').one()
 with app.test_request_context('/'):
  g.institute_engine=h['engine'](s.id)
  Student=__import__('app').Student
  assert Student.query.filter_by(admission_no='RETAIN-1').one().name=='Fictional retained student'
 print('New process: private account and school data retained.')
"""
for code in (create,read):subprocess.run([sys.executable,'-W','ignore','-c',code],cwd=root,check=True)
