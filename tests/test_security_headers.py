"""Boundary policies without blocking print frames, capture or file sandboxing."""
import os,unittest
os.environ['DATABASE_URL']='sqlite:///:memory:'
from app import app

class SecurityHeadersTests(unittest.TestCase):
    def setUp(self):
        self.old=app.config['TESTING'];app.config['TESTING']=True
        self.client=app.test_client()
    def tearDown(self):app.config['TESTING']=self.old
    def test_https_hsts_and_no_insecure_hsts(self):
        secure=self.client.get('/healthz',base_url='https://school.example')
        self.assertEqual(secure.headers['Strict-Transport-Security'],'max-age=31536000')
        self.assertNotIn('Strict-Transport-Security',self.client.get('/healthz').headers)
    def test_native_readiness_contract(self):
        health=self.client.get('/healthz')
        self.assertEqual(health.status_code,200)
        self.assertEqual(health.mimetype,'application/json')
        self.assertEqual(health.headers['X-SchoolFlow-Response'],'1')
        self.assertEqual(health.json['status'],'ok')
        self.assertTrue(health.json['build'].startswith('schoolflow-'))
        self.assertIn('no-store',health.headers['Cache-Control'])
    def test_baseline_policy_preserves_capture_and_same_origin_print(self):
        response=self.client.get('/healthz');h=response.headers
        self.assertEqual(h['X-Content-Type-Options'],'nosniff')
        self.assertEqual(h['X-Frame-Options'],'SAMEORIGIN')
        self.assertIn("frame-ancestors 'self'",h['Content-Security-Policy'])
        self.assertIn("object-src 'none'",h['Content-Security-Policy'])
        self.assertIn('microphone=(self)',h['Permissions-Policy'])
        self.assertIn('camera=(self)',h['Permissions-Policy'])
    def test_strict_file_sandbox_and_no_referrer_are_preserved(self):
        from flask import make_response
        with app.test_request_context('/workspace/private-file',base_url='https://school.example'):
            response=make_response('private')
            response.headers['Content-Security-Policy']="default-src 'none'; sandbox"
            response.headers['Referrer-Policy']='no-referrer'
            response=app.process_response(response)
            self.assertEqual(response.headers['Content-Security-Policy'],"default-src 'none'; sandbox")
            self.assertEqual(response.headers['Referrer-Policy'],'no-referrer')
            self.assertIn('no-store',response.headers['Cache-Control'])
