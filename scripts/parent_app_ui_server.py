"""Disposable Parent UI fixture. Never use a live database or actual credentials."""
import os,sys,tempfile
from pathlib import Path
if os.environ.get('SCHOOLFLOW_UI_QA')!='1':raise SystemExit('SCHOOLFLOW_UI_QA=1 required')
root=tempfile.TemporaryDirectory(prefix='parent-ui-')
os.environ['DATABASE_URL']='sqlite:///'+str(Path(root.name)/'control.db')
os.environ.pop('IDENTITY_DATABASE_URL',None);os.environ.pop('SCHOOLFLOW_PRIVATE_STORAGE_QA',None)
sys.path[:0]=[str(Path(__file__).resolve().parents[1])]
from tests.test_parent_app import ParentAppTests
from app import app
fixture=ParentAppTests();fixture.setUp();fixture.seed_app()
# Two independently issued credentials: one per viewport. A newer credential
# cancels earlier links, so obtain the second through the real authenticated UI.
assert fixture.post('/workspace/general/parents/login-settings',{'version':'0','action':'enable','login_code':'58312694','confirm_code':'58312694','acknowledge':'yes'}).status_code==302
Path('/tmp/parent-ui-entry.json').write_text(__import__('json').dumps(dict(credential=fixture.credential(),password=fixture.password)))
app.run('127.0.0.1',5058,threaded=True,use_reloader=False)
