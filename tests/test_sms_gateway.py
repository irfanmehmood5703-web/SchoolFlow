"""Real institute/device state transitions; no SIM or real destination is contacted."""
import os,tempfile,time,unittest,hashlib
os.environ['DATABASE_URL']='sqlite:///:memory:'
from flask import g
from app import app,db,Student

class SmsGatewayTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.old={key:app.config.get(key) for key in ('TESTING','IDENTITY_ENFORCE_IN_TESTS','INSTITUTE_DATABASE_DIR','PUBLIC_DEMO_ENABLED')}
        app.config.update(TESTING=True,IDENTITY_ENFORCE_IN_TESTS=True,INSTITUTE_DATABASE_DIR=self.tmp.name,PUBLIC_DEMO_ENABLED=False)
        self.ctx=app.app_context();self.ctx.push();db.drop_all();db.create_all();self.key='k'*43;self.M=app.extensions['sms_models']
        self.school=app.extensions['identity_helpers']['provision']('SMS-QA','Fictional SMS School','qa@example.invalid','Fictional-SMS-password-2026');self.school_id=self.school.id
        with app.test_request_context('/'):
            g.institute_engine=app.extensions['identity_helpers']['engine'](self.school_id)
            rm=app.extensions['record_models'];db.session.add(rm['settings'](category='campus',value='North',class_name=''))
            db.session.add(self.M['device'](id=1,name='Fictional school phone',campus='North',active=True,digest=hashlib.sha256(self.key.encode()).hexdigest()))
            db.session.add(self.M['job'](id='j'*43,source='fictional:1',device_id=1,generation=1,phone='+12025550123',text='Fictional test only'))
            db.session.commit();db.session.remove()
        self.c=app.test_client();self.headers={'X-Institute-Code':'SMS-QA','Authorization':'Bearer '+self.key}
    def tearDown(self):
        db.session.remove();db.drop_all();self.ctx.pop();app.config.update(self.old);self.tmp.cleanup()
    def call(self,action,data=None,headers=None,did=1):return self.c.post(f'/api/sms/devices/{did}/{action}',json={} if data is None else data,headers=self.headers if headers is None else headers)
    def heartbeat(self):
        response=self.call('heartbeat');self.assertEqual(response.status_code,200);self.headers['X-Device-Scope']=response.json['scope']
    def claim(self):
        self.heartbeat();response=self.call('claim');self.assertEqual(response.status_code,200);return response.json['job']
    def ref(self,job):return {key:job[key] for key in ('id','token')}
    def login(self):
        self.c.get('/auth/institute')
        with self.c.session_transaction() as session:token=session['record_csrf']
        self.c.post('/auth/institute',data={'_csrf':token,'code':'SMS-QA'})
        with self.c.session_transaction() as session:token=session['record_csrf']
        self.assertEqual(self.c.post('/auth/login',data={'_csrf':token,'email':'qa@example.invalid','password':'Fictional-SMS-password-2026'}).status_code,302)
        with self.c.session_transaction() as session:return session['record_csrf']
    def test_authentication_scope_and_replay_do_not_implicitly_send(self):
        self.assertEqual(self.call('heartbeat',headers={}).status_code,401)
        self.heartbeat();wrong={**self.headers,'X-Device-Scope':'wrong'}
        self.assertEqual(self.call('claim',headers=wrong).status_code,409)
        job=self.call('claim').json['job'];self.assertEqual(job['state'],'claimed')
        self.assertEqual(self.call('claim').json['job']['token'],job['token'])
        self.assertEqual(self.call('result',{**self.ref(job),'state':'sent'}).status_code,409)
        self.assertEqual(self.call('start',self.ref(job)).status_code,200)
        self.assertEqual(self.call('start',self.ref(job)).status_code,409)
        self.assertIsNone(self.call('claim').json['job'])
        body={**self.ref(job),'state':'sent','detail':'Synthetic accepted callback'}
        self.assertFalse(self.call('result',body).json['replayed'])
        self.assertTrue(self.call('result',body).json['replayed'])
        self.assertEqual(self.call('result',{**body,'state':'failed'}).status_code,409)
        self.assertEqual(self.call('start',{'id':job['id'],'token':'غلط'}).status_code,403)
    def test_expired_pre_dispatch_claim_can_be_reclaimed_but_started_cannot(self):
        job=self.claim()
        with app.test_request_context('/'):
            g.institute_engine=app.extensions['identity_helpers']['engine'](self.school_id);stored=db.session.get(self.M['job'],job['id']);stored.expires=1;db.session.commit();db.session.remove()
        reclaimed=self.call('claim').json['job'];self.assertNotEqual(reclaimed['token'],job['token'])
        self.assertEqual(self.call('start',self.ref(job)).status_code,403)
        self.assertEqual(self.call('start',self.ref(reclaimed)).status_code,200)
        self.assertEqual(self.call('result',{**self.ref(reclaimed),'state':'unknown'}).status_code,200)
        self.assertIsNone(self.call('claim').json['job'])
    def test_rotation_suspension_and_wrong_school_cannot_dispatch(self):
        job=self.claim();token=self.login()
        self.assertEqual(self.c.post('/workspace/general/sms',data={'_csrf':token,'device_id':1,'action':'suspend'}).status_code,302)
        self.assertEqual(self.call('start',self.ref(job)).status_code,403)
        self.c.post('/workspace/general/sms',data={'_csrf':token,'device_id':1,'action':'activate'})
        response=self.c.post('/workspace/general/sms',data={'_csrf':token,'device_id':1,'action':'rotate'})
        self.assertEqual(response.status_code,200);self.assertNotIn(self.key.encode(),response.data)
        self.assertEqual(self.call('heartbeat').status_code,401)
        self.assertEqual(self.call('heartbeat',headers={**self.headers,'X-Institute-Code':'UNKNOWN-QA'}).status_code,401)
    def test_explicit_preview_release_deduplication_and_campus(self):
        with app.test_request_context('/'):
            g.institute_engine=app.extensions['identity_helpers']['engine'](self.school_id);rm=app.extensions['record_models'];ops=app.extensions['ops_models']
            f=rm['family'](number='QA',data={'phone':'+12025550123'});db.session.add(f);db.session.flush()
            s=Student(admission_no='SMS-1',name='Fictional SMS Pupil',class_name='One',status='Active');db.session.add(s);db.session.flush();db.session.add(rm['student'](student_id=s.id,family_id=f.id,data={'campus':'North'}))
            row=ops['workflow'](kind='message',status='Provider not configured',data={'audience':'parent','preferences':{'app_sms':True,'father_contact':True},'ids':[s.id],'messages':[{'person_id':s.id,'text':'Fictional preview','unresolved':[]}]});db.session.add(row);db.session.commit();wid=row.id;db.session.remove()
        token=self.login();path=f'/workspace/general/sms/release/{wid}'
        self.assertEqual(self.c.get(path+'?device_id=1').status_code,200)
        self.assertEqual(self.c.post(path,data={'_csrf':token,'device_id':1}).status_code,422)
        for i in range(2):self.assertEqual(self.c.post(path,data={'_csrf':token,'device_id':1,'confirm':'yes'}).status_code,302)
        with app.test_request_context('/'):
            g.institute_engine=app.extensions['identity_helpers']['engine'](self.school_id)
            self.assertEqual(self.M['job'].query.count(),2)
            row=db.session.get(ops['workflow'],wid);row.data={**row.data,'preferences':{'branded_sms':True,'father_contact':True}};db.session.commit();db.session.remove()
        self.assertEqual(self.c.post(path,data={'_csrf':token,'device_id':1,'confirm':'yes'}).status_code,422)
    def test_cross_institute_colliding_device_ids_are_isolated(self):
        other=app.extensions['identity_helpers']['provision']('SMS-OTHER','Other Fictional School','other@example.invalid','Fictional-SMS-password-2026');other_id=other.id
        with app.test_request_context('/'):
            g.institute_engine=app.extensions['identity_helpers']['engine'](other_id);db.session.add(self.M['device'](id=1,name='Other phone',campus='North',active=True,digest=hashlib.sha256(('z'*43).encode()).hexdigest()));db.session.commit();db.session.remove()
        self.assertEqual(self.call('heartbeat',headers={**self.headers,'X-Institute-Code':'SMS-OTHER'}).status_code,401)
        job=self.claim();headers={'X-Institute-Code':'SMS-OTHER','Authorization':'Bearer '+'z'*43}
        headers['X-Device-Scope']=self.call('heartbeat',headers=headers).json['scope']
        self.assertIsNone(self.call('claim',headers=headers).json['job'])
        self.assertEqual(self.call('start',self.ref(job),headers=headers).status_code,404)
    def test_public_mobile_entries_and_private_outbox(self):
        for kind in ('parents','teacher','owner'):self.assertEqual(self.c.get('/mobile/'+kind).status_code,200)
        self.assertEqual(self.c.get('/mobile/unknown').status_code,404)
        self.assertEqual(self.c.post('/mobile/parents',data={'code':'SMS-QA','_csrf':'wrong'}).status_code,400)
        self.assertEqual(self.c.get('/workspace/general/sms').status_code,302)
        token=self.login();self.assertEqual(self.c.get('/workspace/general/sms').status_code,200)
        self.assertEqual(self.c.post('/workspace/general/sms',data={'action':'add','name':'New','campus':'North'}).status_code,400)
        self.assertEqual(self.c.post('/workspace/general/sms',data={'action':'add','name':'New','campus':'North','_csrf':token}).status_code,200)

if __name__=='__main__':unittest.main()
