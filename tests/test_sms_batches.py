"""Paced finite school-SIM runs; all jobs/numbers are fictional, no SMS sent."""
import hashlib,secrets,unittest
from unittest.mock import patch
from flask import g
from tests import test_sms_gateway as fixture
from app import app,db

class SmsBatchTests(unittest.TestCase):
    setUp=fixture.SmsGatewayTests.setUp
    tearDown=fixture.SmsGatewayTests.tearDown
    call=fixture.SmsGatewayTests.call
    heartbeat=fixture.SmsGatewayTests.heartbeat
    ref=fixture.SmsGatewayTests.ref
    login=fixture.SmsGatewayTests.login
    def tenant(self,fn,school=None):
        with app.test_request_context('/'):
            g.institute_engine=app.extensions['identity_helpers']['engine'](school or self.school_id);db.session.remove();result=fn();db.session.commit();db.session.remove();return result
    def extra(self,n=2):
        def seed():
            for i in range(n):db.session.add(self.M['job'](id=str(i)*43,source='extra:'+str(i),device_id=1,generation=1,phone='+12025550123',text='Fictional queued '+str(i),created=100+i))
        self.tenant(seed)
    def batch(self,interval=20,token=None):
        response=self.call('batch',dict(id=token or secrets.token_urlsafe(32),interval=interval));self.assertEqual(response.status_code,200,response.data);return response.json['batch']
    def claim(self,batch):return self.call('claim',dict(batch=batch['id']))
    def start(self,batch,job):return self.call('start',dict(self.ref(job),batch=batch['id']))
    def report(self,job,state='sent'):return self.call('result',dict(self.ref(job),state=state,detail='Fictional callback'))
    def test_background_notification_feed_does_not_claim_or_send_sms(self):
        self.heartbeat();self.extra()
        before=self.tenant(lambda:self.M['job'].query.filter_by(state='queued').count())
        r=self.call('notification-feed',{})
        self.assertEqual(r.status_code,200);self.assertTrue(any(e['title']=='Pending school SMS' for e in r.json['events']))
        self.assertNotIn('+12025550123',str(r.json));self.assertNotIn('Fictional queued',str(r.json))
        self.assertEqual(self.tenant(lambda:self.M['job'].query.filter_by(state='queued').count()),before)
        self.assertEqual(self.call('notification-feed',{}).json,r.json)
    def test_pending_list_selected_send_and_cancel_are_device_scoped(self):
        self.heartbeat();self.extra()
        pending=self.call('pending').json
        self.assertEqual(pending['total'],3)
        self.assertEqual({j['id'] for j in pending['jobs']},{'j'*43,'0'*43,'1'*43})
        self.assertTrue(all('token' not in j for j in pending['jobs']))
        for _ in range(2):
            self.assertEqual(self.call('cancel-pending',{'ids':['0'*43]}).status_code,200)
        self.assertEqual(self.tenant(lambda:db.session.get(self.M['job'],'0'*43).state),'cancelled')
        self.assertEqual(self.call('cancel-pending',{'ids':['z'*43,'j'*43]}).status_code,409)
        token=secrets.token_urlsafe(32)
        b=self.call('batch',{'id':token,'interval':20,'ids':['1'*43]}).json['batch']
        self.assertEqual(b['total'],1)
        self.assertEqual(self.call('cancel-pending',{'ids':['j'*43]}).status_code,409)
        job=self.claim(b).json['job'];self.assertEqual(job['id'],'1'*43)
        self.assertEqual(self.start(b,job).status_code,200)
        self.assertEqual(self.report(job).status_code,200)
        self.assertTrue(self.claim(b).json['complete'])
        self.assertEqual(self.call('cancel-pending',{'ids':['1'*43]}).status_code,409)
        self.assertEqual([j['id'] for j in self.call('pending').json['jobs']],['j'*43])
        self.assertEqual(self.call('batch',{'id':token,'interval':20,'ids':['j'*43]}).status_code,409)
    def test_cancel_reviewed_only_before_dispatch(self):
        self.heartbeat();self.extra()
        job=self.call('claim').json['job']
        for _ in range(2):self.assertEqual(self.call('cancel-reviewed',self.ref(job)).status_code,200)
        self.assertEqual(self.call('start',self.ref(job)).status_code,409)
        next_job=self.call('claim').json['job']
        self.assertEqual(self.call('start',self.ref(next_job)).status_code,200)
        self.assertEqual(self.call('cancel-reviewed',self.ref(next_job)).status_code,409)
    def test_default_and_all_supported_delays_enforced_on_server(self):
        for interval in (15,20,25):
            with self.subTest(interval=interval):
                self.heartbeat();self.extra(1) if interval==15 else None
                # Replenish a unique queued job for each subsequent run.
                if interval!=15:self.tenant(lambda:db.session.add(self.M['job'](id=secrets.token_urlsafe(32),source='interval:'+str(interval),device_id=1,generation=1,phone='+12025550123',text='Fictional spacing')))
                with patch('sms_batches.time.time',return_value=10000+interval*100):
                    batch=self.batch(interval);job=self.claim(batch).json['job'];self.assertEqual(self.start(batch,job).status_code,200);self.assertEqual(self.report(job).status_code,200)
                    wait=self.claim(batch).json
                    if wait.get('batch',{}).get('pending'):self.assertEqual(wait['wait_seconds'],interval)
                    self.assertEqual(self.call('batch-stop',dict(batch=batch['id'])).status_code,200)
    def test_omitting_interval_uses_twenty_seconds(self):
        self.heartbeat();r=self.call('batch',dict(id=secrets.token_urlsafe(32)));self.assertEqual(r.status_code,200);self.assertEqual(r.json['batch']['interval'],20)
    def test_queue_snapshot_does_not_absorb_new_requests(self):
        self.heartbeat();batch=self.batch();self.extra(1)
        with patch('sms_batches.time.time',return_value=10000):
            job=self.claim(batch).json['job'];self.assertEqual(job['id'],'j'*43);self.assertEqual(self.start(batch,job).status_code,200);self.assertEqual(self.report(job).status_code,200)
            done=self.claim(batch).json;self.assertTrue(done['complete']);self.assertFalse(done['batch']['active']);self.assertEqual(done['batch']['sent'],1)
        self.assertEqual(self.call('heartbeat').json['queued'],1)
    def test_early_manual_or_batch_start_cannot_bypass_pacing(self):
        self.heartbeat();self.extra();batch=self.batch(25)
        with patch('sms_batches.time.time',return_value=20000):
            job=self.claim(batch).json['job'];self.assertEqual(self.start(batch,job).status_code,200);self.report(job)
            self.assertEqual(self.claim(batch).json['wait_seconds'],25)
        with patch('sms_batches.time.time',return_value=20025):
            job=self.claim(batch).json['job']
            self.assertEqual(self.call('start',self.ref(job)).status_code,409)
            self.assertEqual(self.start(batch,job).status_code,200);self.report(job)
        self.call('batch-stop',dict(batch=batch['id']))
        manual=self.call('claim').json['job']
        with patch('sms_batches.time.time',return_value=20030):self.assertEqual(self.call('start',self.ref(manual)).status_code,429)
        with patch('sms_batches.time.time',return_value=20050):self.assertEqual(self.call('start',self.ref(manual)).status_code,200)
    def test_slow_sim_result_extends_gap_once_and_report_replay_does_not_extend_it(self):
        self.heartbeat();self.extra();batch=self.batch(20)
        with patch('sms_batches.time.time',return_value=10000):job=self.claim(batch).json['job'];self.start(batch,job)
        with patch('sms_batches.time.time',return_value=10005):self.assertEqual(self.report(job).status_code,200)
        with patch('sms_batches.time.time',return_value=10015):self.assertTrue(self.report(job).json['replayed'])
        with patch('sms_batches.time.time',return_value=10024):self.assertEqual(self.claim(batch).json['wait_seconds'],1)
        with patch('sms_batches.time.time',return_value=10025):self.assertIsNotNone(self.claim(batch).json['job'])
    def test_pause_releases_only_unsent_claim_and_invalidates_old_token(self):
        self.heartbeat();self.extra();batch=self.batch();job=self.claim(batch).json['job']
        self.assertEqual(self.call('batch-stop',dict(batch=batch['id'])).status_code,200)
        self.assertEqual(self.start(batch,job).status_code,403)
        self.assertTrue(self.claim(batch).json['paused'])
        new=self.batch();claimed=self.claim(new).json['job'];self.assertNotEqual(job['token'],claimed['token'])
        self.assertEqual(self.start(new,claimed).status_code,200)
        self.call('batch-stop',dict(batch=new['id']))
        self.assertEqual(self.tenant(lambda:db.session.get(self.M['job'],claimed['id']).state),'started')
    def test_unknown_result_stops_run_and_started_is_not_automatically_requeued(self):
        self.heartbeat();self.extra();batch=self.batch();job=self.claim(batch).json['job'];self.start(batch,job);self.report(job,'unknown')
        paused=self.claim(batch).json;self.assertTrue(paused['paused']);self.assertEqual(paused['batch']['unknown'],1)
        newer=self.batch();self.assertEqual(newer['total'],2);self.assertNotEqual((self.claim(newer).json.get('job') or {}).get('id'),job['id'])
    def test_missing_callback_stops_next_dispatch_even_after_interval(self):
        self.heartbeat();self.extra();batch=self.batch()
        with patch('sms_batches.time.time',return_value=10000):job=self.claim(batch).json['job'];self.start(batch,job)
        with patch('sms_batches.time.time',return_value=11000):
            response=self.claim(batch).json;self.assertTrue(response['paused']);self.assertEqual(response['batch']['started'],1)
            self.assertEqual(self.tenant(lambda:db.session.get(self.M['job'],job['id']).state),'started')
    def test_batch_request_replay_recovers_same_snapshot_and_requires_explicit_stop(self):
        self.heartbeat();token=secrets.token_urlsafe(32);a=self.batch(token=token);b=self.batch(token=token);self.assertEqual(a['id'],b['id']);self.assertEqual(a['total'],b['total'])
        self.assertEqual(self.call('batch',dict(id=secrets.token_urlsafe(32),interval=20)).status_code,409)
        self.assertEqual(self.call('heartbeat').json['active_batch']['id'],a['id'])
        self.assertEqual(self.call('batch',dict(id=token,interval=15)).status_code,409)
    def test_invalid_intervals_wrong_scope_and_foreign_phone_rejected(self):
        self.heartbeat()
        for interval in (0,1,14,30,'20',True,None):self.assertEqual(self.call('batch',dict(id=secrets.token_urlsafe(32),interval=interval)).status_code,422)
        batch=self.batch();self.assertEqual(self.call('batch-status',dict(batch=batch['id']),headers={**self.headers,'X-Device-Scope':'wrong'}).status_code,409)
        def seed():db.session.add(self.M['device'](id=2,name='Other campus phone',campus='South',active=True,digest=hashlib.sha256(self.key.encode()).hexdigest()))
        self.tenant(seed);h={k:v for k,v in self.headers.items() if k!='X-Device-Scope'};h['X-Device-Scope']=self.call('heartbeat',headers=h,did=2).json['scope']
        for action in ('batch-status','batch-stop','claim'):self.assertEqual(self.call(action,dict(batch=batch['id']),headers=h,did=2).status_code,403)
    def test_suspension_rotation_and_same_ids_in_other_school_remain_isolated(self):
        self.heartbeat();batch=self.batch();token=self.login();self.c.post('/workspace/general/sms',data=dict(_csrf=token,action='suspend',device_id=1));self.assertEqual(self.claim(batch).status_code,403)
        self.c.post('/workspace/general/sms',data=dict(_csrf=token,action='activate',device_id=1));self.c.post('/workspace/general/sms',data=dict(_csrf=token,action='rotate',device_id=1));self.assertEqual(self.claim(batch).status_code,401)
        other=app.extensions['identity_helpers']['provision']('SMS-OTHER','Fictional second school','other@example.invalid','Fictional-SMS-password-2026').id
        self.tenant(lambda:db.session.add(self.M['device'](id=1,name='Other phone',campus='North',active=True,digest=hashlib.sha256(('z'*43).encode()).hexdigest())),other)
        h={'X-Institute-Code':'SMS-OTHER','Authorization':'Bearer '+'z'*43};h['X-Device-Scope']=self.call('heartbeat',headers=h).json['scope']
        self.assertEqual(self.call('batch-status',dict(batch=batch['id']),headers=h).status_code,404)

if __name__=='__main__':unittest.main()
