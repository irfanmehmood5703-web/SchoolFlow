"""Isolated ready-school fixture for completion and redirect-fragment checks."""
import os,sys,tempfile
from pathlib import Path
if os.environ.get('SCHOOLFLOW_UI_QA')!='1':raise SystemExit('Synthetic UI QA opt-in required')
root=tempfile.TemporaryDirectory(prefix='sf-completion-ui-')
os.environ['DATABASE_URL']='sqlite:///'+str(Path(root.name)/'fictional.db')
os.environ.pop('IDENTITY_DATABASE_URL',None)
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app import app,db,Student
from flask import jsonify
app.config.update(TESTING=True,SECRET_KEY='fictional-completion-only',IDENTITY_ENFORCE_IN_TESTS=False)
with app.app_context():
 db.create_all();R=app.extensions['record_models'];M=app.extensions['institute_setup_models'];F=app.extensions['fee_setup_models']
 for category,values in {'campus':['North'],'class_name':['One'],'section':['A'],'group_name':['General'],'academic_session':['2027'],'fee_plan':['Common Plan']}.items():
  for value in values:db.session.add(R['settings'](category=category,value=value,class_name=''))
 db.session.add(M['profile'](id=1,data=dict(name='Fictional completion school',current_session='2027',year_start='2027-01-01',year_end='2027-12-31',ui_mode='light')))
 db.session.add(M['campus'](name='North',active=True))
 db.session.add(M['mapping'](campus='North',class_name='One',active=True,data=dict(sections=['A'],groups=['General'],fee_plans=['Common Plan'],academic_session='2027')))
 db.session.add(F['head'](key='Tuition Fee',label='Tuition Fee',timing='monthly',months=[],custom=False))
 db.session.add(F['schedule'](name='Common Plan',campus='North',class_name='One',description='',due_day=10,lines=[dict(key='Tuition Fee',amount=350000)]));db.session.commit()
@app.get('/qa/state')
def state():
 O=app.extensions['ops_models'];P=app.extensions['institute_setup_models']['profile'].query.one()
 return jsonify(completions=O['audit'].query.filter_by(action='Complete institute setup').count(),activated=bool(P.data.get('setup_activated_at')),students=Student.query.count(),bills=O['bill'].query.count(),salaries=O['salary'].query.count())
app.run(host='127.0.0.1',port=5057,use_reloader=False)
