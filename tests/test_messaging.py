"""Real two-school login, family-scoped chat, policy, media and report regressions."""
import os,io,re,html,tempfile,time,secrets,unittest,wave
from datetime import date
from flask import g
from werkzeug.security import generate_password_hash
from openpyxl import load_workbook
os.environ['DATABASE_URL']='sqlite:///:memory:'
from app import app,db,Student,Employee
from messaging import DEFAULTS,contact_spans

class MessagingTests(unittest.TestCase):
    password='Fictional-messages-password-2026'
    def setUp(self):
        self.root=tempfile.TemporaryDirectory();app.config.update(TESTING=True,SECRET_KEY='fictional-message-qa',IDENTITY_ENFORCE_IN_TESTS=True,INSTITUTE_DATABASE_DIR=self.root.name)
        self.ctx=app.app_context();self.ctx.push();db.drop_all();db.create_all()
        self.H=app.extensions['identity_helpers'];self.M=app.extensions['message_models'];self.rm=app.extensions['record_models'];self.ops=app.extensions['ops_models'];self.Staff=app.extensions['staff_account_model']
        self.school=self.H['provision']('MSG-ONE','Fictional school one','owner@example.invalid',self.password).id
        def seed():
            for cat,values in {'campus':['North','South'],'class_name':['One','Two'],'section':['A']}.items():
                for value in values:db.session.add(self.rm['settings'](category=cat,value=value,class_name=''))
            for n in (1,2):
                f=self.rm['family'](number='F'+str(n),data={'father':'Guardian '+str(n)});db.session.add(f);db.session.flush()
                s=Student(admission_no='M'+str(n),name='Fictional child '+str(n),class_name='One' if n==1 else 'Two',status='Active');db.session.add(s);db.session.flush();db.session.add(self.rm['student'](student_id=s.id,family_id=f.id,data={'campus':'North','section':'A'}))
            for n,role,campus in [(1,'Teacher','North'),(2,'Admin','South')]:
                e=Employee(employee_no='T'+str(n),name='Fictional teacher '+str(n),role='Teacher',status='Active');db.session.add(e);db.session.flush();db.session.add(self.rm['employee'](employee_id=e.id,data={'campus':campus}))
                permissions={p:[campus] for p in ['dashboard.view','messages.view','messages.create','messages.update','messages.report']}
                staff=self.Staff(employee_id=e.id,username='teacher'+str(n),password_hash=generate_password_hash(self.password),data=dict(role=role,campuses=[campus],permissions=permissions));db.session.add(staff)
                if n==1:db.session.add(self.ops['workflow'](kind='teacher-classes',status='Active',data={'employee_id':str(e.id),'campus':'North','class_name':'One','section':'A','subject':'Math'}))
        self.tenant(seed);self.c=self.login()
    def tearDown(self):
        db.session.remove();g.pop('institute_engine',None);db.drop_all();self.ctx.pop();app.config.update(IDENTITY_ENFORCE_IN_TESTS=False,INSTITUTE_DATABASE_DIR=None);self.root.cleanup()
    def tenant(self,fn,school=None):
        with app.test_request_context('/'):
            g.institute_engine=self.H['engine'](school or self.school);db.session.remove();result=fn();db.session.commit();db.session.remove()
        g.pop('institute_engine',None);return result
    def csrf(self,c=None):
        with (c or self.c).session_transaction() as s:return s['record_csrf']
    def login(self,username='owner@example.invalid',code='MSG-ONE'):
        c=app.test_client();c.get('/auth/institute');c.post('/auth/institute',data={'_csrf':self.csrf(c),'code':code});r=c.post('/auth/login',data={'_csrf':self.csrf(c),'email':username,'password':self.password});self.assertEqual(r.status_code,302);return c
    def post(self,path,data=None,c=None):
        c=c or self.c;return c.post(path,data={'_csrf':self.csrf(c),**(data or {})})
    def parent(self,fid=1):
        r=self.post('/workspace/general/parents/links/'+str(fid),{'action':'issue'});self.assertEqual(r.status_code,200)
        full=html.unescape(re.search(rb'<strong>(.*?)</strong>',r.data)[1].decode());p=app.test_client();p.get('/parents/MSG-ONE/enter');r=self.post('/parents/MSG-ONE/enter',{'credential':full.split('#')[1]},p);self.assertEqual(r.status_code,302);return p
    def new(self,**changes):
        data=dict(campus='North',category='Parent',recipient='parent:1|1',subject='Fictional progress',body='Please review classwork.',token=secrets.token_urlsafe(32));data.update(changes);return data
    def create(self,**changes):
        r=self.post('/workspace/conversations/new',self.new(**changes));self.assertEqual(r.status_code,302,r.data[:500]);return r.location.rsplit('/',1)[1]
    def policy(self,**changes):
        def save():
            row=db.session.get(self.M['policy'],1)
            if not row:row=self.M['policy'](id=1,data={**DEFAULTS,**changes});db.session.add(row)
            else:row.data={**row.data,**changes}
        self.tenant(save)
    def test_real_parent_reply_read_state_and_fresh_login_persistence(self):
        cid=self.create();p=self.parent();path='/parents/MSG-ONE/messages/'+cid
        page=p.get(path);self.assertEqual(page.status_code,200);self.assertIn(b'Please review classwork.',page.data)
        r=self.post(path+'/reply',dict(body='Family reply',token=secrets.token_urlsafe(32)),p);self.assertEqual(r.status_code,302)
        self.assertIn(b'Family reply',self.c.get('/workspace/conversations/'+cid).data)
        mid=self.tenant(lambda:self.M['message'].query.order_by(self.M['message'].id).first().id)
        self.assertEqual(self.post(path+'/read',{'last':str(mid)},p).status_code,204)
        self.assertIn(b'Read in SchoolFlow',self.c.get('/workspace/conversations/'+cid).data)
        self.c=self.login();self.assertIn(b'Family reply',self.c.get('/workspace/conversations/'+cid).data)
    def test_foreign_family_school_anonymous_and_private_file_boundaries(self):
        cid=self.create(attachments=(io.BytesIO(b'%PDF-1.4\nfictional'),'school.pdf'));p=self.parent(2)
        self.assertEqual(p.get('/parents/MSG-ONE/messages/'+cid).status_code,404)
        fid=self.tenant(lambda:self.M['file'].query.one().id)
        self.assertEqual(p.get('/parents/MSG-ONE/messages/'+cid+'/files/'+str(fid)).status_code,404)
        second=self.H['provision']('MSG-TWO','Second fictional','owner@example.invalid',self.password).id
        other=self.login(code='MSG-TWO');self.assertEqual(other.get('/workspace/conversations/'+cid).status_code,404)
        self.assertNotIn(b'Fictional progress',other.get('/workspace/conversations').data)
        self.assertEqual(app.test_client().get('/workspace/conversations/'+cid).status_code,302)
    def test_directory_class_campus_pair_and_disabled_staff_revalidate(self):
        teacher=self.login('teacher1')
        people=teacher.get('/workspace/conversations/recipients?category=Parent&campus=North').json['people'];self.assertEqual(len(people),1);self.assertEqual(people[0]['value'],'parent:1|1')
        self.assertEqual(teacher.get('/workspace/conversations/recipients?category=Parent&campus=South').status_code,403)
        self.assertEqual(self.post('/workspace/conversations/new',self.new(recipient='parent:2|2'),teacher).status_code,422)
        self.policy(disabled=['staff:1']);self.assertEqual(teacher.get('/workspace/conversations').status_code,403)
        self.assertEqual(self.post('/workspace/conversations/new',self.new(category='Teacher',recipient='staff:1')).status_code,422)
    def test_parent_start_pair_toggle_and_off_preserve_reading(self):
        cid=self.create();p=self.parent();path='/parents/MSG-ONE/messages'
        self.policy(parents_start=False)
        owner=self.c.get('/workspace/conversations/recipients?category=Owner&campus=North').json['people']
        # Owner is self and correctly excluded from its own recipient picker.
        self.assertEqual(owner,[])
        self.assertEqual(self.post(path+'/new',self.new(category='Owner',recipient='owner:1',student_id='1'),p).status_code,422)
        self.assertEqual(self.post(path+'/'+cid+'/reply',dict(body='Reply allowed',token=secrets.token_urlsafe(32)),p).status_code,302)
        self.policy(enabled=False)
        self.assertEqual(p.get(path+'/'+cid).status_code,200)
        self.assertEqual(self.post(path+'/'+cid+'/reply',dict(body='Must not send',token=secrets.token_urlsafe(32)),p).status_code,422)
    def test_contact_warn_hide_and_block_do_not_leak_blocked_files(self):
        self.assertTrue(contact_spans('Call ۰۳۰۶۷۱۵۷۹۶۶ or teacher@example.invalid'))
        self.policy(contact_mode='hide');cid=self.create(body='Call 0306-7157966 or staff@example.invalid')
        p=self.parent();page=p.get('/parents/MSG-ONE/messages/'+cid);self.assertNotIn(b'0306-7157966',page.data);self.assertIn(b'contact details hidden',page.data)
        self.policy(contact_mode='block');blocked=self.create(body='Call 0306-7157966',attachments=(io.BytesIO(b'%PDF-1.4\nblocked'),'blocked.pdf'))
        page=p.get('/parents/MSG-ONE/messages/'+blocked);self.assertEqual(page.status_code,404);self.assertNotIn(b'0306-7157966',page.data);self.assertNotIn(b'blocked.pdf',page.data)
        fid=self.tenant(lambda:self.M['file'].query.order_by(self.M['file'].id.desc()).first().id)
        self.assertEqual(p.get('/parents/MSG-ONE/messages/'+blocked+'/files/'+str(fid)).status_code,404)
        self.assertIn(b'Blocked',self.c.get('/workspace/conversations/'+blocked).data)
    def test_exact_retry_payload_binding_and_missing_csrf(self):
        data=self.new();r=self.post('/workspace/conversations/new',data);self.assertEqual(r.status_code,302)
        self.assertEqual(self.post('/workspace/conversations/new',data).location,r.location)
        self.assertEqual(self.post('/workspace/conversations/new',{**data,'body':'Different payload'}).status_code,422)
        self.assertEqual(self.tenant(lambda:self.M['message'].query.count()),1)
        self.assertEqual(self.c.post('/workspace/conversations/new',data=data).status_code,400)
    def test_files_reject_invalid_types_atomically_and_expire_with_permission_checks(self):
        r=self.post('/workspace/conversations/new',self.new(attachments=(io.BytesIO(b'<script>bad</script>'),'fake.png')));self.assertEqual(r.status_code,422)
        self.assertEqual(self.tenant(lambda:self.M['conversation'].query.count()),0)
        cid=self.create(attachments=(io.BytesIO(b'%PDF-1.4\nfixture'),'valid.pdf'));fid=self.tenant(lambda:self.M['file'].query.one().id);p=self.parent()
        self.assertEqual(p.get('/parents/MSG-ONE/messages/'+cid+'/files/'+str(fid)).status_code,200)
        self.policy(retention_days=30)
        self.tenant(lambda:setattr(self.M['message'].query.one(),'created',time.time()-31*86400))
        self.assertEqual(p.get('/parents/MSG-ONE/messages/'+cid+'/files/'+str(fid)).status_code,410)
    def test_voice_duration_is_decoded_not_trusted_from_client(self):
        def wav(seconds):
            b=io.BytesIO()
            with wave.open(b,'wb') as w:w.setnchannels(1);w.setsampwidth(2);w.setframerate(8000);w.writeframes(b'\x00\x00'*int(8000*seconds))
            b.seek(0);return b
        self.policy(voice_seconds=1)
        r=self.post('/workspace/conversations/new',self.new(body='',voice=(wav(2),'voice.wav'),voice_duration='0'));self.assertEqual(r.status_code,422)
        self.assertEqual(self.tenant(lambda:self.M['message'].query.count()),0)
        cid=self.create(body='',voice=(wav(.2),'voice.wav'))
        self.assertIn(b'Voice note',self.c.get('/workspace/conversations/'+cid).data)
    def test_report_filter_transcript_confirmation_audit_and_formula_safe_export(self):
        cid=self.create(body='=HYPERLINK("x")')
        self.assertEqual(self.post('/workspace/conversations/report',{'export':'transcripts'}).status_code,422)
        r=self.post('/workspace/conversations/report',{'export':'transcripts','confirm':'yes','campus':'North'});self.assertEqual(r.status_code,200)
        book=load_workbook(io.BytesIO(r.data));self.assertEqual(book.active.cell(2,8).data_type,'s')
        self.assertEqual(self.tenant(lambda:self.ops['audit'].query.filter_by(action='Export conversation transcripts').count()),1)
        r=self.post('/workspace/conversations/report',{'export':'summary','campus':'South'});self.assertEqual(len(list(load_workbook(io.BytesIO(r.data)).active.values)),1)
        teacher=self.login('teacher1');self.assertEqual(teacher.get('/workspace/conversations/report').status_code,200);self.assertEqual(self.post('/workspace/conversations/report',{'export':'summary'},teacher).status_code,403)
        self.assertEqual(teacher.get('/workspace/conversations/settings').status_code,403)
    def test_resolve_reopen_stale_update_flag_and_support_intent(self):
        cid=self.create();version=self.tenant(lambda:db.session.get(self.M['conversation'],cid).version)
        self.assertEqual(self.post('/workspace/conversations/'+cid+'/status',{'version':str(version),'status':'Resolved'}).status_code,302)
        self.assertEqual(self.post('/workspace/conversations/'+cid+'/status',{'version':str(version),'status':'Open'}).status_code,422)
        self.assertEqual(self.post('/workspace/conversations/'+cid+'/reply',dict(body='No',token=secrets.token_urlsafe(32))).status_code,422)
        mid=self.tenant(lambda:self.M['message'].query.one().id)
        self.assertEqual(self.post('/workspace/conversations/'+cid+'/flag/'+str(mid),{'severity':'5','reason':'Review fictional issue'}).status_code,302)
        self.assertEqual(self.tenant(lambda:self.ops['workflow'].query.filter_by(kind='message-support-escalation',status='Support not connected').count()),1)
        self.assertIn(b'Review fictional issue',self.c.get('/workspace/conversations/report?tab=flagged').data)
    def test_settings_versions_invalid_ranges_and_legacy_sms_blaster(self):
        cfg={k:('1' if v else '') for k,v in DEFAULTS.items() if isinstance(v,bool)}
        cfg.update(version='0',pairs=DEFAULTS['pairs'],contact_mode='warn',max_mb='10',voice_seconds='120',retention_days='0',unresolved_hours='24',escalate_severity='4')
        self.assertEqual(self.post('/workspace/conversations/settings',cfg).status_code,302)
        self.assertEqual(self.post('/workspace/conversations/settings',cfg).status_code,422)
        self.assertEqual(self.post('/workspace/conversations/settings',{**cfg,'version':'1','retention_days':'5'}).status_code,422)
        self.assertIn(b'SMS Blaster',self.c.get('/workspace/messages').data)
    def test_student_target_is_family_bound_and_has_no_independent_authentication(self):
        cid=self.create(category='Student');p=self.parent();page=p.get('/parents/MSG-ONE/messages/'+cid)
        self.assertIn(b'Family access uses the verified Parent account',page.data)
        self.policy(pairs=['Owner:Parent'])
        self.assertEqual(self.post('/parents/MSG-ONE/messages/'+cid+'/reply',dict(body='Cannot bypass Student policy',token=secrets.token_urlsafe(32)),p).status_code,422)
    def test_unresolved_uses_oldest_unanswered_message_not_latest_bump(self):
        cid=self.create();p=self.parent();path='/parents/MSG-ONE/messages/'+cid
        for text in ('Old question','New reminder'):self.assertEqual(self.post(path+'/reply',dict(body=text,token=secrets.token_urlsafe(32)),p).status_code,302)
        def age():
            messages=self.M['message'].query.filter_by(conversation_id=cid).order_by(self.M['message'].id).all()
            messages[0].created=time.time()-40*3600;messages[1].created=time.time()-30*3600;messages[2].created=time.time()-3600
        self.tenant(age)
        page=self.c.get('/workspace/conversations/report');self.assertIn(b'<strong>1</strong><span>Unresolved',page.data)

    def test_parent_privilege_and_revoked_family_session_block_chat_and_files(self):
        cid=self.create(attachments=(io.BytesIO(b'%PDF-1.4\nprivate'),'private.pdf'));p=self.parent();fid=self.tenant(lambda:self.M['file'].query.one().id)
        def restrict():
            P=app.extensions['parent_models']['policy'];db.session.add(P(id=1,data={'overrides':{'1':{'messages':{'mode':'block'}}}}))
        self.tenant(restrict)
        self.assertEqual(p.get('/parents/MSG-ONE/messages/'+cid).status_code,403)
        self.assertEqual(p.get('/parents/MSG-ONE/messages/'+cid+'/files/'+str(fid)).status_code,403)
        self.assertNotIn(b'Fictional progress',p.get('/parents/MSG-ONE/messages').data)
        self.tenant(lambda:setattr(db.session.get(app.extensions['parent_models']['account'],1),'version',2))
        self.assertEqual(p.get('/parents/MSG-ONE/messages/'+cid).status_code,302)
    def test_staff_report_and_inbox_do_not_disclose_other_campus_threads(self):
        north=self.create();south=self.create(campus='South',category='Admin',recipient='staff:2',subject='South confidential')
        teacher=self.login('teacher1')
        self.assertNotIn(b'South confidential',teacher.get('/workspace/conversations/report').data)
        self.assertNotIn(b'South confidential',teacher.get('/workspace/conversations').data)
        self.assertEqual(teacher.get('/workspace/conversations/'+north).status_code,404)
        self.assertEqual(teacher.get('/workspace/conversations/'+south).status_code,404)
    def test_simultaneous_exact_retry_creates_one_message(self):
        from concurrent.futures import ThreadPoolExecutor
        data=self.new();cookie=self.c.get_cookie('session').value
        def send():
            client=app.test_client();client.set_cookie('session',cookie)
            return client.post('/workspace/conversations/new',data={'_csrf':self.csrf(),**data}).status_code
        with ThreadPoolExecutor(max_workers=2) as pool:statuses=list(pool.map(lambda _:send(),range(2)))
        self.assertEqual(statuses,[302,302]);self.assertEqual(self.tenant(lambda:self.M['message'].query.count()),1)
