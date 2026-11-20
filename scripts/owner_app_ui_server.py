"""Disposable private-school fixture for Owner UI checks. Never run against live data."""
import os,sys,tempfile
from pathlib import Path
if os.environ.get('SCHOOLFLOW_UI_QA')!='1':raise SystemExit('SCHOOLFLOW_UI_QA=1 required')
tmp=tempfile.TemporaryDirectory(prefix='owner-ui-')
os.environ['DATABASE_URL']='sqlite:///'+str(Path(tmp.name)/'control.db')
os.environ.pop('IDENTITY_DATABASE_URL',None);os.environ.pop('SCHOOLFLOW_PRIVATE_STORAGE_QA',None)
sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parents[1]/'tests')]
from test_owner_app import OwnerAppTests
from flask import redirect
from app import app
fixture=OwnerAppTests();fixture.setUp()
@app.get('/qa/owner-entry')
def qa_entry():
    return redirect('/mobile/owner?school=OWNER-A&scope='+fixture.schools[0][1])
app.run('127.0.0.1',5057,threaded=True,use_reloader=False)
