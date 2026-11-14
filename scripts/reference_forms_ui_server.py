import os,sys,tempfile
from pathlib import Path
if os.environ.get("SCHOOLFLOW_UI_QA")!="1":raise SystemExit("Synthetic UI QA requires SCHOOLFLOW_UI_QA=1")
qa_directory=tempfile.TemporaryDirectory(prefix="schoolflow-ui-")
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
os.environ['DATABASE_URL']='sqlite:///'+str(Path(qa_directory.name)/'qa.db')
os.environ.pop('IDENTITY_DATABASE_URL',None)
os.environ.pop('SCHOOLFLOW_PRIVATE_STORAGE_QA',None)
from app import app,db,Student,Employee
app.config.update(TESTING=True,SECRET_KEY='fictional-ui-only',IDENTITY_ENFORCE_IN_TESTS=False)
with app.app_context():
 db.drop_all();db.create_all();rm=app.extensions['record_models']
 for cat,vs in {'campus':['North'],'class_name':['One'],'section':['A'],'academic_session':['2026-27'],'subject':['Math','English']}.items():
  for v in vs:db.session.add(rm['settings'](category=cat,value=v,class_name=''))
 s=Student(admission_no='UI-1',name='Fictional UI Child',class_name='One',status='Active');db.session.add(s);db.session.flush();db.session.add(rm['student'](student_id=s.id,data=dict(campus='North',section='A',academic_session='2026-27')))
 e=Employee(employee_no='UI-E1',name='Fictional Teacher',role='Teacher',status='Active');db.session.add(e);db.session.flush();db.session.add(rm['employee'](employee_id=e.id,data=dict(campus='North')));db.session.commit()
 # An employee-linked, non-production recipient for internal chat UI tests.
 from werkzeug.security import generate_password_hash
 Staff=app.extensions['staff_account_model']
 db.session.add(Staff(employee_id=e.id,username='fictional-ui-teacher',password_hash=generate_password_hash('fictional-ui-password-only'),data=dict(role='Teacher',campuses=['North'],permissions={'messages.view':['North'],'messages.create':['North'],'messages.update':['North']})))
 db.session.commit()
app.run(host='127.0.0.1',port=5055,use_reloader=False)
