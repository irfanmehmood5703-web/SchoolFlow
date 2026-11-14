"""Disposable PostgreSQL QA: restart persistence and typed logical restore.

Never a production backup command. Requires the CI-only flag AND exact disposable
current_database() name; only newly provisioned fictional schools are written.
"""
import os,subprocess,sys,tempfile
from pathlib import Path
if os.environ.get('SCHOOLFLOW_PRIVATE_STORAGE_QA')!='1':raise SystemExit('Run only against the disposable private-account CI database.')
root=Path(__file__).resolve().parent.parent
common=r'''
import os,json,hashlib
from datetime import date,datetime
from decimal import Decimal
from pathlib import Path
os.environ['DATABASE_URL']='sqlite:///:memory:'
from app import app,db,Student,Employee
from flask import g
from sqlalchemy import select

def checked_helpers():
 h=app.extensions['identity_helpers']
 assert h['control_engine']().dialect.name=='postgresql'
 with h['control_engine']().connect() as c:
  assert c.execute(db.text('select current_database()')).scalar()=='private_account_qa','Disposable QA database required'
 return h

def encode(value):
 if isinstance(value,Decimal):return {'__qa_type':'decimal','value':str(value)}
 if isinstance(value,bytes):return {'__qa_type':'bytes','value':value.hex()}
 if isinstance(value,datetime):return {'__qa_type':'datetime','value':value.isoformat()}
 if isinstance(value,date):return {'__qa_type':'date','value':value.isoformat()}
 raise TypeError(type(value).__name__)
def decode(value):
 if set(value)=={'__qa_type','value'}:
  kind=value['__qa_type'];raw=value['value']
  if kind=='decimal':return Decimal(raw)
  if kind=='bytes':return bytes.fromhex(raw)
  if kind=='datetime':return datetime.fromisoformat(raw)
  if kind=='date':return date.fromisoformat(raw)
 return value

def snapshot(h,engine):
 with engine.connect() as c:
  return {t.name:[dict(r) for r in c.execute(select(t).order_by(*t.primary_key.columns)).mappings()] for t in h['workspace_tables']()}
'''
create=common+r'''
with app.app_context():
 h=checked_helpers();s=h['provision']('RESTART-QA','Fictional persistence school','qa@example.invalid','Fictional-restart-password')
 with app.test_request_context('/'):
  g.institute_engine=h['engine'](s.id);rm=app.extensions['record_models'];ops=app.extensions['ops_models']
  family=rm['family'](number='QA-FAMILY',data={'father':'Fictional guardian'});db.session.add(family);db.session.flush()
  pupil=Student(name='Fictional retained student',admission_no='RETAIN-1',class_name='One',status='Active');db.session.add(pupil);db.session.flush()
  db.session.add(rm['student'](student_id=pupil.id,family_id=family.id,data={'campus':'QA Campus','section':'A'}))
  employee=Employee(name='Fictional retained teacher',employee_no='QA-E1',role='Teacher',status='Active');db.session.add(employee);db.session.flush()
  db.session.add(rm['employee'](employee_id=employee.id,data={'campus':'QA Campus','joining_date':'2026-01-01'}))
  bill=ops['bill'](student_id=pupil.id,month='2026-10',due=date(2026,10,10),lines=[{'particular':'Tuition','amount':10000}],paid=2500,discount=500);db.session.add(bill);db.session.flush()
  db.session.add(ops['receipt'](student_id=pupil.id,bill_id=bill.id,amount=2500,discount=500,day=date(2026,10,1),account='QA Cash',token='fictional-restart-receipt'))
  db.session.add(ops['daily'](kind='student',person_id=pupil.id,day=date(2026,10,1),status='Present'))
  award=ops['workflow'](kind='awards',status='Active',data={'name':'QA Term','campus':'QA Campus','papers':[{'subject':'Math','total':50}]});db.session.add(award);db.session.flush()
  db.session.add(ops['score'](award_id=award.id,student_id=pupil.id,paper=0,obtained=40,state=''))
  db.session.add(ops['salary'](employee_id=employee.id,month='2026-09',earnings=100000,deductions=10000,net=90000,paid=20000,detail={'basic':100000,'deductions':10000}))
  body=b'%PDF-1.4\nFictional QA attachment only'
  db.session.add(rm['file'](owner_kind='student',owner_id=pupil.id,title='QA document',filename='qa.pdf',mime='application/pdf',photo=False,content=body,sha256=hashlib.sha256(body).hexdigest()))
  db.session.commit()
 print('First process: family, student, attachment, employee, bill/receipt, attendance, exam and salary saved.')
'''
restart_backup=common+r'''
with app.app_context():
 h=checked_helpers();S=app.extensions['identity_models']['institute'];school=S.query.filter_by(code='RESTART-QA').one();source=h['engine'](school.id)
 with app.test_request_context('/'):
  g.institute_engine=source;ops=app.extensions['ops_models'];rm=app.extensions['record_models']
  assert Student.query.filter_by(admission_no='RETAIN-1').one().name=='Fictional retained student'
  assert rm['family'].query.one().number=='QA-FAMILY'
  assert ops['bill'].query.one().remaining==7000 and ops['receipt'].query.one().amount==2500
  assert ops['score'].query.one().obtained==40 and ops['salary'].query.one().net==90000
  assert ops['daily'].query.one().status=='Present' and rm['file'].query.one().content.startswith(b'%PDF')
  db.session.remove()
 g.pop('institute_engine',None)
 payload=snapshot(h,source);path=Path(os.environ['SCHOOLFLOW_QA_BACKUP_FILE'])
 with path.open('x') as f:os.chmod(path,0o600);json.dump(payload,f,default=encode,sort_keys=True)
 print('New process: cross-module records retained; typed logical backup created with private file permissions.')
 restored=h['provision']('RESTORE-QA','Fictional restore target','restore@example.invalid','Fictional-restore-password');target=h['engine'](restored.id)
 data=json.loads(path.read_text(),object_hook=decode)
 with target.begin() as c:
  for t in reversed(h['workspace_tables']()):
   existing=c.execute(select(db.func.count()).select_from(t)).scalar()
   # A new institute has only its generated profile; never overwrite data.
   assert existing==0 or (t is app.extensions['institute_setup_models']['profile'].__table__ and existing==1),(t.name,existing)
   if existing:c.execute(t.delete())
  for t in h['workspace_tables']():
   if data[t.name]:c.execute(t.insert(),data[t.name])
  # Explicit ID restoration must also move each serial sequence forward.
  schema=target.get_execution_options()['schema_translate_map'][None]
  quote=target.dialect.identifier_preparer.quote_identifier
  for t in h['workspace_tables']():
   keys=list(t.primary_key.columns)
   if len(keys)!=1 or not isinstance(keys[0].type,db.Integer):continue
   serial=c.execute(db.text('SELECT pg_get_serial_sequence(:table_name,:column_name)'),{'table_name':quote(schema)+'.'+quote(t.name),'column_name':keys[0].name}).scalar()
   if serial:
    maximum=c.execute(select(db.func.max(keys[0]))).scalar()
    c.execute(db.text('SELECT setval(CAST(:serial AS regclass),:value,:used)'),dict(serial=serial,value=max(maximum or 1,1),used=maximum is not None))
 actual=snapshot(h,target)
 assert json.dumps(actual,default=encode,sort_keys=True)==json.dumps(payload,default=encode,sort_keys=True)
 print('Logical restore: all tenant tables, relationships, binary files and financial totals match the source snapshot.')
 with app.test_request_context('/'):
  g.institute_engine=target
  db.session.add(Student(name='Fictional after restore',admission_no='AFTER-RESTORE',status='Active'));db.session.commit();db.session.remove()
  assert Student.query.count()==2
  db.session.remove()
 g.pop('institute_engine',None)
 with source.connect() as c:assert c.execute(select(db.func.count()).select_from(Student.__table__)).scalar()==1
 print('Post-restore create: restored serial IDs accept new records; the source school is unchanged.')
'''
with tempfile.TemporaryDirectory(prefix='schoolflow-disposable-qa-') as folder:
    env={**os.environ,'SCHOOLFLOW_QA_BACKUP_FILE':str(Path(folder)/'fictional-backup.json')}
    for code in (create,restart_backup):subprocess.run([sys.executable,'-W','ignore','-c',code],cwd=root,env=env,check=True)
