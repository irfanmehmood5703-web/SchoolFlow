"""Disposable Teacher browser fixture. No live credentials, students or SMS."""
import os,sys,json
from pathlib import Path
if os.environ.get('SCHOOLFLOW_UI_QA')!='1':raise SystemExit('SCHOOLFLOW_UI_QA=1 required')
os.environ['DATABASE_URL']='sqlite:///:memory:'
os.environ.pop('IDENTITY_DATABASE_URL',None);os.environ.pop('SCHOOLFLOW_PRIVATE_STORAGE_QA',None)
sys.path[:0]=[str(Path(__file__).resolve().parents[1])]
from tests.test_teacher_app import TeacherAppTests,app,db
fixture=TeacherAppTests();fixture.setUp();fixture.seed()
# Multiple assigned exam subjects in the same class, with independent totals.
def seed_award():
    W=fixture.ops['workflow'];assignment=db.session.get(W,fixture.cid)
    papers=[dict(subject='Math',grading='Marks',total=50)]
    for subject,total in [('English',40),('Urdu',50),('Computer',25),('General Knowledge',50)]:
        db.session.add(fixture.rm['settings'](category='subject',value=subject,class_name='One'))
        db.session.add(W(kind='teacher-classes',status='Active',data={**assignment.data,'subject':subject}))
        papers.append(dict(subject=subject,grading='Marks',total=total))
    row=W(kind='awards',status='Active',data=dict(name='Fictional combined test',campus='Campus A',class_name='One',section='A',papers=papers))
    db.session.add(row);db.session.flush()
    return row.id
aid=fixture.tenant(seed_award)
school=db.session.get(fixture.M['institute'],fixture.school)
Path('/tmp/teacher-ui-entry.json').write_text(json.dumps(dict(entry='/mobile/teacher?school='+school.code+'&scope='+school.storage_key,username='teacher.one',password=fixture.password,cid=fixture.cid,pupil=fixture.pupil,award=aid)))
app.run('127.0.0.1',5059,threaded=True,use_reloader=False)
