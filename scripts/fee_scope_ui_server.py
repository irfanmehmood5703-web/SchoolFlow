"""Disposable fictional fee-scope browser fixture; never connects to school data."""
import os,sys,tempfile
from pathlib import Path
if os.environ.get('SCHOOLFLOW_UI_QA')!='1':raise SystemExit('Explicit synthetic UI QA opt-in required')
root=tempfile.TemporaryDirectory(prefix='sf-fee-scope-ui-')
os.environ['DATABASE_URL']='sqlite:///'+str(Path(root.name)/'fictional.db')
os.environ.pop('IDENTITY_DATABASE_URL',None)
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app import app,db
app.config.update(TESTING=True,SECRET_KEY='fictional-fee-scope-only',IDENTITY_ENFORCE_IN_TESTS=False)
with app.app_context():
 db.create_all();S=app.extensions['record_models']['settings'];H=app.extensions['fee_setup_models']['head']
 for category,values in {'section':['A','B'],'group_name':['Arts','General','Science'],'academic_session':['2027','2028'],'fee_plan':['Plan A','Plan B'],'campus':['North','South'],'class_name':['Montessori','One','Two','A class with a longer display name']}.items():
  for value in values:db.session.add(S(category=category,value=value,class_name=''))
 for key,timing,months in [('Tuition Fee','monthly',[]),('Annual Charges','months',[3]),('Tie and Badge Amount','first',[])]:
  db.session.add(H(key=key,label=key,timing=timing,months=months,custom=False))
 db.session.commit()
app.run(host='127.0.0.1',port=5056,use_reloader=False)
