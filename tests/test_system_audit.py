"""Whole-menu traversal and real setup failures found in the pre-UAT audit."""
import json,re,unittest
from html.parser import HTMLParser
from flask import g,session
from tests import test_messaging as fixture
from app import app,db

class Links(HTMLParser):
    def __init__(self):super().__init__();self.urls=set();self.selects=set();self.inputs=set()
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if tag=='a' and a.get('href','').startswith(('/workspace/','/records/')):self.urls.add(a['href'].split('#')[0])
        if tag=='select':self.selects.add(a.get('name'))
        if tag=='input':self.inputs.add(a.get('name'))

class SystemAuditTests(unittest.TestCase):
    password=fixture.MessagingTests.password
    setUp=fixture.MessagingTests.setUp;tearDown=fixture.MessagingTests.tearDown;tenant=fixture.MessagingTests.tenant;csrf=fixture.MessagingTests.csrf;login=fixture.MessagingTests.login;post=fixture.MessagingTests.post
    def test_all_private_owner_menu_and_inner_links_are_real_pages(self):
        with app.test_request_context('/workspace/how-to'):
            g.school_identity=dict(scope='fictional-audit',demo=False);session['owner_id']=1
            guides=app.extensions['how_to_catalogue']()
            self.assertEqual(len(guides),106)
            for a in guides:
                endpoint,_=app.url_map.bind('localhost').match(a['target'].split('?')[0]);self.assertNotEqual(endpoint,'ops.entry',a['slug'])
        urls={a['target'] for a in guides}|{'/workspace/readiness','/records/student/new','/records/employee/new'};seen=set()
        for depth in range(2):
            more=set()
            for url in sorted(urls-seen):
                seen.add(url)
                if any(x in url for x in ('/logo','/photo','/files/','/exports/','/identity-card','/qr-image','/download')):continue
                with self.subTest(url=url):
                    r=self.c.get(url,follow_redirects=True)
                    if url.split('?')[0]=='/workspace/attendance/geo-self':self.assertEqual(r.status_code,403);continue
                    self.assertEqual(r.status_code,200,r.data[:200]);self.assertNotIn(b'Reference screen pending',r.data)
                    if r.mimetype=='text/html':
                        links=Links();links.feed(r.text);more|=links.urls
            urls=more
        self.assertGreater(len(seen),250)
    def test_empty_catalogs_remain_selects_and_new_unknown_choices_do_not_save(self):
        page=self.c.get('/workspace/register/teacher-classes');p=Links();p.feed(page.text)
        for name in ('employee_id','campus','class_name','section','subject'):self.assertIn(name,p.selects);self.assertNotIn(name,p.inputs)
        self.assertIn(b'No Subject configured',page.data)
        values=dict(employee_id='1',campus='North',class_name='One',section='A',subject='Unknown subject')
        self.assertEqual(self.post('/workspace/register/teacher-classes',values).status_code,422)
        def seed():db.session.add(self.rm['settings'](category='subject',value='Math',class_name=''))
        self.tenant(seed)
        for key in ('campus','class_name','section'):
            self.assertEqual(self.post('/workspace/register/teacher-classes',{**values,'subject':'Math',key:'Unknown choice'}).status_code,422)
        self.assertEqual(self.post('/workspace/register/teacher-classes',{**values,'subject':'Math'}).status_code,302)
    def test_free_text_register_fields_are_not_accidentally_dropdowns(self):
        page=self.c.get('/workspace/register/increments');p=Links();p.feed(page.text)
        self.assertIn('employee_id',p.selects)
        for name in ('amount','effective'):self.assertIn(name,p.inputs);self.assertNotIn(name,p.selects)
    def test_roll_review_not_offered_until_automatic_numbering_enabled(self):
        path='/workspace/core/roll-number-series';page=self.c.get(path);p=Links();p.feed(page.text)
        self.assertFalse(any('?fill=' in u for u in p.urls));self.assertIn(b'Enable automatic rolls first',page.data)
        self.assertEqual(self.post(path,dict(action='settings',version='0',enabled='1',skip='1')).status_code,302)
        p=Links();p.feed(self.c.get(path).text);review=next(u for u in p.urls if '?fill=' in u);self.assertEqual(self.c.get(review).status_code,200)
    def test_reminder_day_requires_actual_calendar_day(self):
        for day in ('0','32','999'):
            self.assertEqual(self.post('/workspace/register/auto-reminders',dict(name='Fictional reminder',day=day,message='Fictional reminder text')).status_code,422)
        self.assertEqual(self.post('/workspace/register/auto-reminders',dict(name='Fictional reminder',day='31',message='Fictional reminder text')).status_code,302)
    def test_private_and_demo_storage_guidance_do_not_confuse_real_data_testing(self):
        page=self.c.get('/workspace/readiness');self.assertIn(b'School-data testing order',page.data);self.assertIn(b'Private school account storage',page.data)
        dashboard=self.c.get('/workspace/dashboard');self.assertIn(b'Private school workspace',dashboard.data);self.assertNotIn(b'DEMO',dashboard.data)
        before=app.config.get('PUBLIC_DEMO_ENABLED');app.config['PUBLIC_DEMO_ENABLED']=True
        try:
            demo=app.test_client();demo.get('/auth/institute');self.assertEqual(self.post('/auth/demo',{},demo).status_code,302)
            page=demo.get('/workspace/readiness');self.assertIn(b'Public DEMO: temporary testing only',page.data);self.assertIn(b'Do not enter real school records here',page.data)
        finally:app.config['PUBLIC_DEMO_ENABLED']=before
