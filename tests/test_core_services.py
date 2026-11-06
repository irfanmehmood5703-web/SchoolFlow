"""Credential secrecy, provider command replay, billing and tenant isolation."""
import unittest,secrets
from unittest.mock import patch
from datetime import date,datetime,timedelta,timezone
from cryptography.fernet import Fernet
from flask import g
import tests.test_attendance_devices as fixture
from app import app,db
from whatsapp_settings import ENDPOINT

class CoreServiceTests(unittest.TestCase):
    password=fixture.AttendanceDeviceTests.password
    key=fixture.AttendanceDeviceTests.key
    setUpFixture=fixture.AttendanceDeviceTests.setUp
    tenant=fixture.AttendanceDeviceTests.tenant
    login=fixture.AttendanceDeviceTests.login
    token=fixture.AttendanceDeviceTests.token
    def setUp(self):
        self.setUpFixture();self.old={k:app.config.get(k) for k in ('INTEGRATION_KEY','WHATSAPP_ENABLED','WHATSAPP_SEND_ENABLED')};app.config.update(INTEGRATION_KEY=Fernet.generate_key().decode(),WHATSAPP_ENABLED=False,WHATSAPP_SEND_ENABLED=False);self.api_key='fictional-provider-secret-for-tests-only'
    def tearDown(self):app.config.update(self.old);fixture.AttendanceDeviceTests.tearDown(self)
    def post(self,path,**data):return self.c.post(path,data={'_csrf':self.token(),**data})
    def add_provider(self):return self.post('/workspace/core/whatsapp',action='save-provider',name='Fictional provider',api_key=self.api_key,endpoint=ENDPOINT)
    def test_services_render_empty_without_fabricated_balance_or_billing(self):
        self.login()
        for path in ('/workspace/core/whatsapp/service','/workspace/core/whatsapp','/workspace/core/subscription'):
            response=self.c.get(path);self.assertEqual(response.status_code,200,response.data)
        self.assertIn(b'No invoices',self.c.get('/workspace/core/subscription').data);self.assertIn(b'not configured',self.c.get('/workspace/core/whatsapp/service').data)
    def test_missing_encryption_key_refuses_saving_credentials(self):
        self.login();app.config['INTEGRATION_KEY']=None
        with patch.dict('os.environ',{},clear=True):self.assertEqual(self.add_provider().status_code,422)
        self.assertEqual(self.tenant(lambda:app.extensions['whatsapp_models']['provider'].query.count()),0)
    def test_provider_key_is_encrypted_hidden_and_bad_host_refused(self):
        self.login();self.assertEqual(self.add_provider().status_code,302)
        raw=self.tenant(lambda:db.session.get(app.extensions['whatsapp_models']['provider'],1).secret);self.assertNotIn(self.api_key,raw)
        self.assertNotIn(self.api_key.encode(),self.c.get('/workspace/core/whatsapp').data)
        response=self.post('/workspace/core/whatsapp',action='save-provider',name='SSRF',api_key=self.api_key,endpoint='https://127.0.0.1/private')
        self.assertEqual(response.status_code,422)
    def test_provider_not_contacted_without_explicit_enable_and_csrf(self):
        self.login();self.add_provider()
        with patch('whatsapp_settings.provider_request') as provider:
            r=self.post('/workspace/core/whatsapp/command',operation='account_new',version='1',token='a'*48);self.assertEqual(r.status_code,422);provider.assert_not_called()
            r=self.c.post('/workspace/core/whatsapp/command',data={'operation':'account_new'});self.assertEqual(r.status_code,400)
    def test_command_replay_never_generates_a_second_external_qr(self):
        self.login();self.add_provider();app.config['WHATSAPP_ENABLED']=True
        data=dict(operation='account_new',version='1',token='b'*48)
        with patch('whatsapp_settings.provider_request',return_value={'qr':'fictional-qr-text','key':self.api_key}) as provider:
            self.assertEqual(self.post('/workspace/core/whatsapp/command',**data).status_code,302)
            self.assertEqual(self.post('/workspace/core/whatsapp/command',**data).status_code,302);self.assertEqual(provider.call_count,1)
        page=self.c.get('/workspace/core/whatsapp');self.assertEqual(page.status_code,200,page.data);self.assertNotIn(self.api_key.encode(),page.data);self.assertIn(b'data:image/png;base64,',page.data)
    def test_unknown_external_result_is_not_retried_or_claimed_sent(self):
        self.login();self.add_provider();app.config['WHATSAPP_ENABLED']=True
        with patch('whatsapp_settings.provider_request',side_effect=ValueError('Fictional timeout')) as provider:
            data=dict(operation='account_new',version='1',token='c'*48)
            self.post('/workspace/core/whatsapp/command',**data);self.post('/workspace/core/whatsapp/command',**data);self.assertEqual(provider.call_count,1)
        self.assertEqual(self.tenant(lambda:app.extensions['whatsapp_models']['command'].query.one().status),'Unknown')
    def test_send_requires_enable_linked_account_and_unique_command(self):
        self.login();self.add_provider();app.config.update(WHATSAPP_ENABLED=True,WHATSAPP_SEND_ENABLED=True)
        with patch('whatsapp_settings.provider_request',return_value={'data':[{'id':'fictional-device-1','name':'Fictional linked phone'}]}):self.assertEqual(self.post('/workspace/core/whatsapp/command',operation='account_view',version='1',token='d'*48).status_code,302)
        data=dict(operation='send',version='2',token='e'*48,device='fictional-device-1',mobile='923000000000',message='Fictional test message only',media_url='')
        with patch('whatsapp_settings.provider_request',return_value={'success':True,'id':'fictional-provider-message'}) as provider:
            self.assertEqual(self.post('/workspace/core/whatsapp/command',**data).status_code,302)
            self.assertEqual(self.post('/workspace/core/whatsapp/command',**data).status_code,302);self.assertEqual(provider.call_count,1)
        page=self.c.get('/workspace/core/whatsapp');self.assertIn(b'Submitted',page.data);self.assertNotIn(self.api_key.encode(),page.data)
    def test_removed_provider_clears_secret_and_retains_command_history(self):
        self.login();self.add_provider();app.config['WHATSAPP_ENABLED']=True
        with patch('whatsapp_settings.provider_request',return_value={'balance':100}):self.post('/workspace/core/whatsapp/command',operation='check_balance',version='1',token='f'*48)
        self.assertEqual(self.post('/workspace/core/whatsapp',action='delete-provider',provider_id='1',version='2').status_code,302)
        self.assertEqual(self.tenant(lambda:db.session.get(app.extensions['whatsapp_models']['provider'],1).secret),'');self.assertEqual(self.tenant(lambda:app.extensions['whatsapp_models']['command'].query.count()),1)
    def cli(self,command,*args):return app.test_cli_runner().invoke(args=[command,*args])
    def test_subscription_invoice_payment_and_replayed_reference(self):
        r=self.cli('subscription-service','--code','DEVICE-TEST','--name','SchoolFlow test subscription','--cycle','Monthly','--price','1250');self.assertEqual(r.exit_code,0,r.output)
        r=self.cli('subscription-invoice','--code','DEVICE-TEST','--month','2026-11','--due','2026-11-10','--amount','1250','--discount','50');self.assertEqual(r.exit_code,0,r.output)
        args=('--invoice-id','1','--amount','1200','--reference','fictional-bank-ref-001')
        for _ in range(2):
            r=self.cli('subscription-receive',*args);self.assertEqual(r.exit_code,0,r.output)
        self.assertEqual(self.cli('subscription-receive','--invoice-id','1','--amount','1','--reference','fictional-bank-ref-002').exit_code,1)
        self.login();page=self.c.get('/workspace/core/subscription?from=2026-11-01&to=2026-11-30');self.assertEqual(page.status_code,200,page.data);self.assertIn(b'Paid',page.data)
        receipt=self.c.get('/workspace/core/subscription/receipts/1');self.assertIn(b'fictional-bank-ref-001',receipt.data)
        M=app.extensions['client_subscription_models'];self.assertEqual(M['receipt'].query.count(),1);self.assertEqual(db.session.get(M['invoice'],1).remaining,0)
    def test_subscription_cannot_be_edited_or_read_across_institutes(self):
        self.login();M=app.extensions['client_subscription_models'];other=app.extensions['identity_helpers']['provision']('OTHER-BILLING','Fictional other school','other@example.invalid',self.password)
        db.session.add(M['invoice'](institute_id=other.id,month='2026-11',due=date(2026,11,10),amount=99900,paid=0,discount=0,snapshot={}));db.session.commit()
        self.assertEqual(self.c.get('/workspace/core/subscription/receipts/1').status_code,404)
        self.assertIn(self.c.post('/workspace/core/subscription',data={'_csrf':self.token(),'paid':'999'}).status_code,(404,405))
        self.assertEqual(db.session.get(M['invoice'],1).paid,0)
        self.assertNotIn(b'999.00',self.c.get('/workspace/core/subscription?from=2026-11-01&to=2026-11-30').data)
    def test_retention_purges_message_content_but_retains_replay_claim(self):
        self.login();self.add_provider();M=app.extensions['whatsapp_models']
        def seed():
            db.session.add(M['command'](provider_id=1,token='1'*48,action='send',fingerprint='a'*64,status='Submitted',payload='fictional-encrypted-payload',created=datetime.now(timezone.utc)-timedelta(days=8)))
        self.tenant(seed);r=self.cli('whatsapp-history-prune','--code','DEVICE-TEST');self.assertEqual(r.exit_code,0,r.output)
        self.assertIsNone(self.tenant(lambda:M['command'].query.one().payload));self.assertEqual(self.tenant(lambda:M['command'].query.count()),1)
