"""Durability, targeting, validation and attachment boundaries for Student Extras."""
import io
import os
import unittest
from werkzeug.datastructures import MultiDict
os.environ['DATABASE_URL']='sqlite:///:memory:'
from app import app,db

class StudentExtrasTests(unittest.TestCase):
    def setUp(self):
        app.config.update(TESTING=True,SECRET_KEY='fictional-extras',IDENTITY_ENFORCE_IN_TESTS=False)
        self.ctx=app.app_context();self.ctx.push();db.drop_all();db.create_all()
        self.models=app.extensions['student_extras_models'];self.Settings=app.extensions['record_models']['settings']
        for cat,values in {'campus':['North','South'],'class_name':['One','Two'],'section':['A'],'subject':['Math','English']}.items():
            for value in values:db.session.add(self.Settings(category=cat,value=value,class_name=''))
        db.session.commit();self.c=app.test_client();self.c.get('/workspace/general/notices')
        with self.c.session_transaction() as s:self.csrf=s['record_csrf']
        self.n=0
    def tearDown(self):
        db.session.remove();db.drop_all();self.ctx.pop()
    def payload(self,**changes):
        self.n+=1
        data=dict(_csrf=self.csrf,submission=str(self.n).zfill(43),campus='North',title='Fictional notice',description='<script>unsafe</script> Homework',starts='2026-11-07',ends='2026-11-08',classes=['One'],action='save')
        data.update(changes)
        return MultiDict((k,v) for k,values in data.items() for v in (values if isinstance(values,list) else [values]))
    def test_pages_and_general_heading(self):
        for url in ['/workspace/general/notices','/workspace/general/notices?new=1','/workspace/general/diary','/workspace/general/diary?new=1']:
            r=self.c.get(url);self.assertEqual(r.status_code,200);self.assertIn(b'Student Extras',r.data)
    def test_notice_is_durable_escaped_targeted_and_duplicate_safe(self):
        data=self.payload();self.assertEqual(self.c.post('/workspace/general/notices',data=data).status_code,302)
        self.assertEqual(self.c.post('/workspace/general/notices',data=data).status_code,302)
        self.assertEqual(self.models['entry'].query.count(),1)
        r=app.test_client().get('/workspace/general/notices');self.assertIn(b'&lt;script&gt;',r.data);self.assertNotIn(b'<script>unsafe',r.data)
        row=self.models['entry'].query.one();self.assertEqual(row.data['classes'],['One']);self.assertEqual(row.campus,'North')
        self.assertNotIn(b'Fictional notice',self.c.get('/workspace/general/notices?campus=South').data)
    def test_notice_validation_and_csrf_do_not_save(self):
        self.assertEqual(self.c.post('/workspace/general/notices',data={}).status_code,400)
        for changes in [dict(classes=[]),dict(classes=['Missing']),dict(ends='2026-11-06'),dict(campus='Missing'),dict(title=''),dict(starts='2026-02-30')]:
            self.assertEqual(self.c.post('/workspace/general/notices',data=self.payload(**changes)).status_code,422,changes)
        self.assertEqual(self.models['entry'].query.count(),0)
    def test_attachment_is_downloaded_and_bad_upload_rolls_back(self):
        data=self.payload();data.add('attachments',(io.BytesIO(b'%PDF-1.4\nfictional'),'notice.pdf'))
        self.assertEqual(self.c.post('/workspace/general/notices',data=data).status_code,302)
        item=self.models['attachment'].query.one();r=self.c.get('/workspace/general/attachments/'+str(item.id))
        self.assertEqual(r.status_code,200);self.assertIn('attachment',r.headers['Content-Disposition']);self.assertTrue(r.data.startswith(b'%PDF'))
        data=self.payload();data.add('attachments',(io.BytesIO(b'<script>bad</script>'),'fake.jpg'))
        self.assertEqual(self.c.post('/workspace/general/notices',data=data).status_code,422)
        self.assertEqual(self.models['entry'].query.count(),1)
    def test_diary_save_and_request_status_filters(self):
        changes=dict(class_name='One',section='A',subject='Math',channel='app',father='1',parent_notification='1',action='save-send')
        self.assertEqual(self.c.post('/workspace/general/diary',data=self.payload(**changes)).status_code,302)
        row=self.models['entry'].query.one();self.assertEqual(row.data['message_status'],'Provider not configured')
        self.assertEqual(row.starts,row.ends)
        for args,visible in [('subject=Math',True),('subject=English',False),('from=2026-11-08',False),('to=2026-11-06',False)]:
            page=self.c.get('/workspace/general/diary?'+args);self.assertEqual(page.status_code,200);self.assertEqual(b'Homework' in page.data,visible)
        self.assertEqual(self.c.post('/workspace/general/diary',data=self.payload(**{**changes,'father':'','mother':'','student':''})).status_code,422)
    def test_section_and_subject_assignment_are_enforced(self):
        row=self.Settings.query.filter_by(category='section').one();row.class_name='Two';db.session.commit()
        data=dict(class_name='One',section='A',subject='Math',channel='app',action='save')
        self.assertEqual(self.c.post('/workspace/general/diary',data=self.payload(**data)).status_code,422)
        row.class_name='';Item=app.extensions['school_settings_models']['item']
        db.session.add(Item(kind='class-subjects',scope='North',name='One',data={'subjects':['English']}));db.session.commit()
        self.assertEqual(self.c.post('/workspace/general/diary',data=self.payload(**data)).status_code,422)
    def test_private_institutes_cannot_read_each_others_notice_or_file(self):
        import tempfile
        from flask import g
        with tempfile.TemporaryDirectory() as root:
            app.config.update(IDENTITY_ENFORCE_IN_TESTS=True,INSTITUTE_DATABASE_DIR=root)
            try:
                H=app.extensions['identity_helpers']
                ids=[H['provision'](code,'Fictional '+code,'owner@example.invalid','Fictional-password-2026').id for code in ('EXTRAS-A','EXTRAS-B')]
                for sid in ids:
                    with app.test_request_context('/'):
                        g.institute_engine=H['engine'](sid);db.session.remove()
                        db.session.add(self.Settings(category='campus',value='Shared label',class_name=''));db.session.commit();db.session.remove()
                    g.pop('institute_engine',None)
                def login(code):
                    c=app.test_client();c.get('/auth/institute')
                    with c.session_transaction() as sess:token=sess['record_csrf']
                    c.post('/auth/institute',data={'_csrf':token,'code':code})
                    with c.session_transaction() as sess:token=sess['record_csrf']
                    c.post('/auth/login',data={'_csrf':token,'email':'owner@example.invalid','password':'Fictional-password-2026'})
                    return c
                a=login('EXTRAS-A')
                with a.session_transaction() as sess:token=sess['record_csrf']
                data=self.payload(_csrf=token,campus='Shared label',all_students='1',classes=[],title='Only institute A')
                data.add('attachments',(io.BytesIO(b'%PDF-1.4\nfictional'),'private.pdf'))
                self.assertEqual(a.post('/workspace/general/notices',data=data).status_code,302)
                self.assertIn(b'Only institute A',a.get('/workspace/general/notices').data)
                b=login('EXTRAS-B')
                self.assertNotIn(b'Only institute A',b.get('/workspace/general/notices').data)
                self.assertEqual(b.get('/workspace/general/attachments/1').status_code,404)
                self.assertEqual(a.get('/workspace/general/attachments/1').status_code,200)
            finally:
                db.session.remove();g.pop('institute_engine',None)
                app.config.update(IDENTITY_ENFORCE_IN_TESTS=False,INSTITUTE_DATABASE_DIR=None)

    def test_pagination_keeps_filters(self):
        for i in range(26):self.c.post('/workspace/general/notices',data=self.payload())
        page=self.c.get('/workspace/general/notices?campus=North');self.assertEqual(page.status_code,200);self.assertIn(b'page=2',page.data)
        page=self.c.get('/workspace/general/notices?campus=North&page=2');self.assertEqual(page.status_code,200);self.assertIn(b'Previous',page.data)

if __name__=='__main__':unittest.main()
