"""Disposable private-school pre-admission audit; no production connections."""
import os,sys,tempfile
from pathlib import Path
if os.environ.get('SCHOOLFLOW_UI_QA')!='1':raise SystemExit('Synthetic browser audit requires explicit opt-in')
root=tempfile.TemporaryDirectory(prefix='sf-private-uat-')
os.environ['DATABASE_URL']='sqlite:///'+str(Path(root.name)/'control.db')
os.environ.pop('IDENTITY_DATABASE_URL',None);os.environ.pop('SCHOOLFLOW_PRIVATE_STORAGE_QA',None)
sys.path.insert(0,str(Path(__file__).resolve().parents[1]));sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tests'))
from test_messaging import MessagingTests
from app import app,db,Student
from flask import g,jsonify,session
from datetime import date
fixture=MessagingTests();fixture.setUp()
def seed():
 R=app.extensions['record_models'];M=app.extensions['institute_setup_models'];F=app.extensions['fee_setup_models'];O=app.extensions['ops_models']
 for category,values in {'group_name':['General','Science'],'academic_session':['2027'],'fee_plan':['Common 2027'],'subject':['Math','English']}.items():
  for value in values:db.session.add(R['settings'](category=category,value=value,class_name=''))
 db.session.add(M['profile'](id=1,data=dict(name='Fictional audit school',current_session='2027',year_start='2027-01-01',year_end='2027-12-31',ui_mode='light')))
 for campus in ['North','South']:
  db.session.add(M['campus'](name=campus,active=True))
  for cls in ['One','Two']:
   db.session.add(M['mapping'](campus=campus,class_name=cls,active=True,data=dict(sections=['A'],groups=['General'],fee_plans=['Common 2027'],academic_session='2027')))
   db.session.add(F['schedule'](name='Common 2027',campus=campus,class_name=cls,due_day=10,description='',lines=[dict(key='Tuition Fee',amount=350000),dict(key='Annual Charges',amount=300000),dict(key='Tie and Badge Amount',amount=30000),dict(key='Registration Fee',amount=200000)]))
 for key,timing,months in [('Tuition Fee','monthly',[]),('Annual Charges','months',[3]),('Tie and Badge Amount','first',[]),('Registration Fee','first',[])]:db.session.add(F['head'](key=key,label=key,timing=timing,months=months,custom=False))
 for row in R['student'].query.all():row.data={**row.data,'group_name':'General','academic_session':'2027','fee_plan':'Common 2027'}
 for n,paid in [(1,100000),(2,350000)]:
  b=O['bill'](student_id=n,month='2027-01',due=date(2027,1,10),lines=[dict(particular='Tuition Fee',amount=350000)],paid=paid,discount=0);db.session.add(b);db.session.flush();db.session.add(O['receipt'](student_id=n,bill_id=b.id,amount=paid,discount=0,day=date(2027,1,2),account='Cash',token='fictional-audit-receipt-'+str(n)))
fixture.tenant(seed)
with app.test_request_context('/workspace/how-to'):
 g.school_identity=dict(scope='fictional-audit',demo=False);session['owner_id']=1
 targets=[dict(label=x['title'],url=x['target']) for x in app.extensions['how_to_catalogue']()]
@app.get('/qa/targets')
def audit_targets():return jsonify(targets)
app.run(host='127.0.0.1',port=5058,use_reloader=False)
