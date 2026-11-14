"""Private schools, real human support, authorised notices and bounded assistant."""
import io,json,re,secrets,time,unittest
from datetime import datetime
from zoneinfo import ZoneInfo
from unittest.mock import patch
from flask import g
from werkzeug.security import generate_password_hash
import test_messaging as messaging_tests
from app import app,db,Student
from assistant_service import ProviderUnavailable

class WorkspaceToolsTests(unittest.TestCase):
    password=messaging_tests.MessagingTests.password
    def setUp(self):
        messaging_tests.MessagingTests.setUp(self)
        def move():
            d=self.rm['student'].query.filter_by(student_id=2).one();d.data={**d.data,'campus':'South'}
        self.tenant(move)
    tearDown=messaging_tests.MessagingTests.tearDown;tenant=messaging_tests.MessagingTests.tenant;csrf=messaging_tests.MessagingTests.csrf;login=messaging_tests.MessagingTests.login;post=messaging_tests.MessagingTests.post;policy=messaging_tests.MessagingTests.policy
    def vendor(self):
        V=app.extensions['vendor_models']['owner'];db.session.add(V(id=1,email='vendor@example.invalid',password_hash=generate_password_hash(self.password)));db.session.commit()
        c=app.test_client();c.get('/vendor/login');r=self.post('/vendor/login',dict(email='vendor@example.invalid',password=self.password),c);self.assertEqual(r.status_code,302);return c
    def ticket(self,c=None,**changes):
        data=dict(token=secrets.token_urlsafe(32),subject='Fictional issue',body='Cannot open an attendance form.',category='Technical',priority='Normal',campus='North');data.update(changes)
        r=self.post('/workspace/support/new',data,c);self.assertEqual(r.status_code,302,r.data[:300]);return r.location
    def ask(self,c=None,**changes):
        data=dict(token=secrets.token_urlsafe(32),question='Fee plan kaise banate hain?',action='guide');data.update(changes);return self.post('/workspace/assistant/ask',data,c)
    def grant(self):
        def f():
            staff=db.session.get(self.Staff,1);staff.data={**staff.data,'permissions':{**staff.data['permissions'],'assistant.view':['North'],'support.view':['North'],'support.create':['North'],'admissions.view':['North'],'admissions.approve':['North']}}
        self.tenant(f)
    def test_header_routes_and_guide_mode_history_idempotency(self):
        self.assertIn(b'data-assistant-open',self.c.get('/workspace/dashboard').data)
        for path in ('/workspace/assistant','/workspace/support','/workspace/notifications','/workspace/notifications/page'):
            self.assertEqual(self.c.get(path).status_code,200,path)
        token=secrets.token_urlsafe(32);r=self.ask(token=token);self.assertEqual(r.status_code,200,r.data);self.assertEqual(r.json['answer']['mode'],'Guide');self.assertTrue(r.json['answer']['links'])
        self.assertEqual(self.ask(token=token).json,r.json);self.assertEqual(self.ask(token=token,question='Changed').status_code,422)
        cid=r.json['chat_id'];self.assertEqual(len(self.c.get('/workspace/assistant/chats/'+cid).json['turns']),2)
        self.assertEqual(len(self.c.get('/workspace/assistant/history').json['chats']),1)
        self.assertEqual(app.test_client().get('/workspace/assistant/history').status_code,302)
        self.assertEqual(self.c.post('/workspace/assistant/ask',data={'question':'fee'}).status_code,400)
    def test_chat_tenant_and_actor_isolation(self):
        cid=self.ask().json['chat_id'];self.grant();teacher=self.login('teacher1');self.assertEqual(teacher.get('/workspace/assistant/chats/'+cid).status_code,404)
        self.H['provision']('MSG-TWO','Second fictional','owner@example.invalid',self.password);other=self.login(code='MSG-TWO');self.assertEqual(other.get('/workspace/assistant/chats/'+cid).status_code,404);self.assertEqual(other.get('/workspace/assistant/history').json['chats'],[])
    def test_staff_live_counts_campus_scope_and_access_revocation(self):
        self.grant();teacher=self.login('teacher1')
        r=self.ask(teacher,action='students',question='Student counts');self.assertEqual(r.status_code,200,r.data);self.assertIn('Active: 1',r.json['answer']['body']);self.assertNotIn('Fictional child',r.json['answer']['body'])
        self.assertEqual(self.ask(teacher,action='fees',question='Fees').status_code,403)
        self.assertEqual(self.ask(teacher,action='delete',question='Delete').status_code,422)
        cid=r.json['chat_id']
        self.tenant(lambda:setattr(db.session.get(self.Staff,1),'data',dict(role='Teacher',campuses=['North'],permissions={'assistant.view':['North']})))
        self.assertEqual(teacher.get('/workspace/assistant/chats/'+cid).status_code,302)
    def test_no_staff_permission_does_not_expose_help_or_stats(self):
        teacher=self.login('teacher1');self.assertEqual(teacher.get('/workspace/assistant/history').status_code,403);self.assertEqual(teacher.get('/workspace/support').status_code,403)
        self.assertNotIn(b'data-assistant-open',teacher.get('/workspace/dashboard').data)
    def test_live_fee_and_attendance_correct_units(self):
        today=datetime.now(ZoneInfo('Asia/Karachi')).date()
        def seed():
            db.session.add(self.ops['bill'](student_id=1,month=today.strftime('%Y-%m'),due=today,lines=[{'amount':12345}],paid=2000,discount=345));db.session.add(self.ops['daily'](kind='student',person_id=1,day=today,status='Present'))
        self.tenant(seed)
        r=self.ask(action='fees',question='Fee balance');self.assertIn('123.45',r.json['answer']['body']);self.assertIn('100.00',r.json['answer']['body']);self.assertIn('Net payable PKR: 120.00',r.json['answer']['body']);self.assertIn('Paid PKR: 20.00',r.json['answer']['body'])
        self.assertIn('Present: 1',self.ask(action='attendance',question='Today attendance').json['answer']['body'])
    def test_ai_model_activation_is_central_and_checks_availability(self):
        self.assertEqual(self.c.get('/vendor/assistant').status_code,302);v=self.vendor()
        with patch('assistant_service.provider_models',return_value=[]):
            r=self.post('/vendor/assistant',dict(version='0',model='gpt-5-mini',enabled='1'),v);self.assertEqual(r.status_code,422);self.assertIn(b'credits',r.data)
        P=app.extensions['assistant_models']['policy'];self.assertIsNone(db.session.get(P,1))
        with patch('assistant_service.provider_models',return_value=['gpt-5-mini']):
            self.assertEqual(self.post('/vendor/assistant',dict(version='0',model='gpt-5-mini',enabled='1'),v).status_code,200)
        self.assertTrue(db.session.get(P,1).enabled)
    def enable(self):
        app.config.update(AI_GATEWAY_TOKEN='fictional-not-a-real-key',AI_GATEWAY_BASE_URL='https://fictional.neon.tech');P=app.extensions['assistant_models']['policy'];db.session.add(P(id=1,enabled=True,model='gpt-5-mini'));db.session.commit();self.addCleanup(lambda:app.config.update(AI_GATEWAY_TOKEN='',AI_GATEWAY_BASE_URL=''))
    def test_ai_input_has_only_guides_retry_single_call_and_fallback(self):
        self.enable();token=secrets.token_urlsafe(32)
        with patch('assistant_service.model_answer',return_value='Open the saved Fee Plans form.') as model:
            r=self.ask(token=token);self.assertEqual(r.json['answer']['mode'],'AI');self.assertEqual(self.ask(token=token).json,r.json);self.assertEqual(model.call_count,1);self.assertNotIn('Fictional child',repr(model.call_args))
        with patch('assistant_service.model_answer',side_effect=ProviderUnavailable):
            r=self.ask();self.assertEqual(r.json['answer']['mode'],'Guide');self.assertIn('unavailable',r.json['answer']['body'])
    def test_ai_budget_and_live_summary_never_call_model(self):
        self.enable();B=app.extensions['assistant_models']['budget'];day=datetime.now(ZoneInfo('Asia/Karachi')).date().isoformat();db.session.add(B(key='all:'+day,count=100));db.session.commit()
        with patch('assistant_service.model_answer') as model:
            self.assertEqual(self.ask().json['answer']['mode'],'Guide');self.assertEqual(self.ask(action='students',question='counts').json['answer']['mode'],'Live summary');model.assert_not_called()
    def test_support_real_owner_reply_files_read_and_no_stale_reply(self):
        path=self.ticket(attachments=(io.BytesIO(b'%PDF-1.4\nfictional'),'issue.pdf'));v=self.vendor();self.assertIn(b'Fictional issue',v.get('/vendor/support').data)
        tid=path.rsplit('/',1)[-1];S=app.extensions['support_models'];ticket=db.session.get(S['ticket'],tid);version=ticket.version;fid=S['file'].query.one().id
        self.assertEqual(self.c.get(path+'/files/'+str(fid)).status_code,200)
        self.assertEqual(self.post('/vendor/support/'+tid+'/reply',dict(token=secrets.token_urlsafe(32),version=str(version),body='Human answer',status='Waiting for School'),v).status_code,302)
        page=self.c.get(path);self.assertIn(b'Human Support',page.data);version=db.session.get(S['ticket'],tid).version;last=S['reply'].query.order_by(S['reply'].id.desc()).first().id
        self.assertEqual(self.post(path+'/read',dict(last=last)).status_code,204);self.assertEqual(db.session.get(S['ticket'],tid).version,version)
        self.assertEqual(self.post(path+'/reply',dict(token=secrets.token_urlsafe(32),version=str(version),body='Thanks',status='Resolved')).status_code,302)
    def test_support_school_actor_isolation_and_vendor_expiry(self):
        path=self.ticket();self.grant();teacher=self.login('teacher1');self.assertEqual(teacher.get(path).status_code,404)
        self.H['provision']('MSG-TWO','Second fictional','owner@example.invalid',self.password);other=self.login(code='MSG-TWO');self.assertEqual(other.get(path).status_code,404)
        self.assertEqual(self.c.get('/vendor/support').status_code,302);v=self.vendor()
        with v.session_transaction() as s:s['vendor_signed_at']=time.time()-4000
        self.assertEqual(v.get('/vendor/support').status_code,302)
    def test_support_exact_create_retry_and_validation(self):
        data=dict(token=secrets.token_urlsafe(32),subject='Retry',body='Details',category='Technical',priority='Normal',campus='North');r=self.post('/workspace/support/new',data);self.assertEqual(r.status_code,302);self.assertEqual(self.post('/workspace/support/new',data).location,r.location)
        self.assertEqual(self.post('/workspace/support/new',{**data,'body':'Different'}).status_code,422)
        self.assertEqual(self.c.post('/workspace/support/new',data=data).status_code,400)
        self.assertEqual(self.post('/workspace/support/new',{**data,'token':secrets.token_urlsafe(32),'attachments':(io.BytesIO(b'executable'),'bad.pdf')}).status_code,422)
    def test_demo_support_preview_cannot_send(self):
        app.config['PUBLIC_DEMO_ENABLED']=True;c=app.test_client();c.get('/auth/institute');r=self.post('/auth/demo',{},c);self.assertEqual(r.status_code,302)
        self.assertIn(b'Demo preview only',c.get('/workspace/support').data)
        self.assertEqual(self.post('/workspace/support/new',dict(token=secrets.token_urlsafe(32)),c).status_code,403)
    def test_notice_support_reply_revision_ack_and_read_all_race(self):
        path=self.ticket();tid=path.rsplit('/',1)[-1];S=app.extensions['support_models'];v=self.vendor()
        def reply(text):
            ver=db.session.get(S['ticket'],tid).version
            return self.post('/vendor/support/'+tid+'/reply',dict(token=secrets.token_urlsafe(32),version=str(ver),body=text,status='In Progress'),v)
        self.assertEqual(reply('First reply').status_code,302);data=self.c.get('/workspace/notifications').json;self.assertEqual(data['count'],1);old=data['events'][0]
        self.assertEqual(self.post('/workspace/notifications/read',dict(key=old['key'],revision=old['revision'])).status_code,204);self.assertEqual(self.c.get('/workspace/notifications').json['count'],0)
        self.assertEqual(reply('New reply').status_code,302)
        self.assertEqual(self.post('/workspace/notifications/read',dict(items=json.dumps([old]))).status_code,204);self.assertEqual(self.c.get('/workspace/notifications').json['count'],1)
        self.assertEqual(self.post('/workspace/notifications/read',dict(key=old['key'],revision=old['revision'])).status_code,409)
    def test_notice_waiting_approvals_scopes_and_no_names(self):
        self.grant();self.tenant(lambda:setattr(db.session.get(Student,1),'status','Waiting'));self.tenant(lambda:setattr(db.session.get(Student,2),'status','Waiting'))
        teacher=self.login('teacher1');r=teacher.get('/workspace/notifications');self.assertEqual(r.status_code,200,r.data);self.assertEqual(len(r.json['events']),1);self.assertNotIn('Fictional child',r.text);self.assertNotIn('South',r.text)
        second=self.login('teacher2');self.assertEqual(second.get('/workspace/notifications').json['events'],[])
    def test_notice_unread_message_disabled_account_and_inactive_child(self):
        def seed():
            C=self.M['conversation'];M=self.M['message'];db.session.add(C(id='fictional-conversation',campus='North',subject='Private subject',people={},first_actor='owner:1',second_actor='staff:1',student_id=1));db.session.flush();db.session.add(M(conversation_id='fictional-conversation',actor='staff:1',label='Teacher',role='Teacher',body='hello'))
        self.tenant(seed);r=self.c.get('/workspace/notifications');self.assertEqual(r.status_code,200,r.data);self.assertEqual(r.json['count'],1)
        self.policy(disabled=['owner:1']);self.assertEqual(self.c.get('/workspace/notifications').json['count'],0)
        self.policy(disabled=[]);self.tenant(lambda:setattr(db.session.get(Student,1),'status','Inactive'));self.assertEqual(self.c.get('/workspace/notifications').json['count'],0)
