"""Structured diary: atomic subjects, formatting, retry and parent boundaries."""
import io,re,unittest
from datetime import date
from werkzeug.datastructures import MultiDict
from tests import test_student_extras as extras_fixture
from tests import test_parents_ptm as parent_fixture
from app import app,db

class DiaryWorkTests(unittest.TestCase):
    setUp=extras_fixture.StudentExtrasTests.setUp
    tearDown=extras_fixture.StudentExtrasTests.tearDown
    payload=extras_fixture.StudentExtrasTests.payload
    def data(self,**changes):
        data=dict(format='subject-work',class_name='One',section='A',subjects=['Math','English'],subject_slot=['0','1'],subject_name_0='Math',subject_name_1='English',classwork_0='<b onclick="evil()">Math work</b><img src=x onerror=evil()>',homework_0='<i>Math home</i>',classwork_1='English work',homework_1='English home',channel='app',action='save')
        data.update(changes);return self.payload(**data)
    def test_subjects_atomic_safe_html_files_and_retry(self):
        data=self.data();token=data['submission']
        data.add('classwork_files_0',(io.BytesIO(b'%PDF-1.4 fictional'),'cw.pdf'))
        data.add('homework_files_1',(io.BytesIO(b'%PDF-1.4 fictional'),'hw.pdf'))
        self.assertEqual(self.c.post('/workspace/general/diary',data=data).status_code,302)
        rows=self.models['entry'].query.order_by(self.models['entry'].id).all();self.assertEqual(len(rows),2)
        self.assertEqual(rows[0].data['classwork'],'<b>Math work</b>')
        self.assertEqual(len(rows[0].data['classwork_attachments']),1);self.assertEqual(rows[0].data['homework_attachments'],[])
        self.assertEqual(len(rows[1].data['homework_attachments']),1)
        page=self.c.get('/workspace/general/diary');self.assertIn(b'<b>Math work</b>',page.data);self.assertNotIn(b'onclick="evil',page.data)
        retry=self.data(submission=token);retry.add('classwork_files_0',(io.BytesIO(b'%PDF-1.4 fictional'),'cw.pdf'));retry.add('homework_files_1',(io.BytesIO(b'%PDF-1.4 fictional'),'hw.pdf'))
        self.assertEqual(self.c.post('/workspace/general/diary',data=retry).status_code,302)
        self.assertEqual(self.c.post('/workspace/general/diary',data=self.data(submission=token)).status_code,422)
        self.assertEqual(self.models['entry'].query.count(),2)
    def test_invalid_second_subject_or_file_saves_nothing(self):
        for changes in [dict(subject_name_1='Missing'),dict(homework_1='',classwork_1=''),dict(subject_slot=['0','0']),dict(section='Missing')]:
            self.assertEqual(self.c.post('/workspace/general/diary',data=self.data(**changes)).status_code,422)
        data=self.data();data.add('homework_files_1',(io.BytesIO(b'bad'),'fake.png'))
        self.assertEqual(self.c.post('/workspace/general/diary',data=data).status_code,422)
        self.assertEqual(self.models['entry'].query.count(),0);self.assertEqual(self.models['attachment'].query.count(),0)
    def test_options_honor_subject_and_class_mapping(self):
        row=self.Settings.query.filter_by(category='subject',value='English').one();row.class_name='Two';db.session.commit()
        options=self.c.get('/workspace/general/diary/options?campus=North&class_name=One');self.assertEqual(options.status_code,200);self.assertEqual(options.json['subjects'],['Math'])
        self.assertEqual(self.c.post('/workspace/general/diary',data=self.data()).status_code,422)

class ParentDiaryWorkTests(unittest.TestCase):
    setUp=parent_fixture.ParentsPtmTests.setUp
    tearDown=parent_fixture.ParentsPtmTests.tearDown
    tenant=parent_fixture.ParentsPtmTests.tenant
    token=parent_fixture.ParentsPtmTests.token
    owner=parent_fixture.ParentsPtmTests.owner
    post=parent_fixture.ParentsPtmTests.post
    credential=parent_fixture.ParentsPtmTests.credential
    parent=parent_fixture.ParentsPtmTests.parent
    seed_debt=parent_fixture.ParentsPtmTests.seed_debt
    password=parent_fixture.ParentsPtmTests.password

    def test_parent_sees_only_enrolled_subject_and_scoped_files(self):
        data=MultiDict([('_csrf',self.token()),('submission','d'*43),('format','subject-work'),('campus','North'),('class_name','One'),('section','A'),('starts',str(date.today())),('subjects','Math'),('subject_slot','0'),('subject_name_0','Math'),('classwork_0','<b>Parent classwork</b>'),('homework_0','<i>Parent homework</i>'),('channel','app'),('action','save'),('classwork_files_0',(io.BytesIO(b'%PDF-1.4 fictional'),'cw.pdf'))])
        self.assertEqual(self.c.post('/workspace/general/diary',data=data).status_code,302)
        p=self.parent();page=p.get('/parents/PARENT-TEST/students/1/diary');self.assertIn(b'<b>Parent classwork</b>',page.data)
        path=re.search(rb'href="([^"]+/diary/[^\"]+/files/[^\"]+)"',page.data)[1].decode()
        self.assertEqual(p.get(path).status_code,200);self.assertEqual(p.get(path.replace('/students/1/','/students/2/')).status_code,404)
        self.seed_debt();self.post('/workspace/general/parents/privileges',{'version':'0','action':'rules','diary_3':'block'})
        self.assertEqual(p.get(path).status_code,403)
