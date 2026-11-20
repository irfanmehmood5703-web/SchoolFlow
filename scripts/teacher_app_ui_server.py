"""Disposable Teacher browser fixture. No live credentials, students or SMS."""
import os,sys,json
from pathlib import Path
if os.environ.get('SCHOOLFLOW_UI_QA')!='1':raise SystemExit('SCHOOLFLOW_UI_QA=1 required')
os.environ['DATABASE_URL']='sqlite:///:memory:'
os.environ.pop('IDENTITY_DATABASE_URL',None);os.environ.pop('SCHOOLFLOW_PRIVATE_STORAGE_QA',None)
sys.path[:0]=[str(Path(__file__).resolve().parents[1])]
from tests.test_teacher_app import TeacherAppTests,app,db
fixture=TeacherAppTests();fixture.setUp();fixture.seed()
school=db.session.get(fixture.M['institute'],fixture.school)
Path('/tmp/teacher-ui-entry.json').write_text(json.dumps(dict(entry='/mobile/teacher?school='+school.code+'&scope='+school.storage_key,username='teacher.one',password=fixture.password,cid=fixture.cid,pupil=fixture.pupil)))
app.run('127.0.0.1',5059,threaded=True,use_reloader=False)
