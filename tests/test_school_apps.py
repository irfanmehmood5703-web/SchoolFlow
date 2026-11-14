"""School-branded APK orchestration: real tenant login, signed OIDC and isolation."""
import os,tempfile,time,unittest,base64,io,zipfile,hashlib,secrets
from types import SimpleNamespace
from unittest.mock import patch
os.environ['DATABASE_URL']='sqlite:///:memory:'
import jwt
from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import hashes,serialization
from cryptography.hazmat.primitives.serialization import pkcs12
from datetime import datetime,timedelta,timezone
from flask import g
from app import app,db
import app_builder_auth as auth

class SchoolAppTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.rsa=rsa.generate_private_key(public_exponent=65537,key_size=2048)
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.previous={k:app.config.get(k) for k in ('TESTING','SECRET_KEY','IDENTITY_ENFORCE_IN_TESTS','INSTITUTE_DATABASE_DIR')}
        app.config.update(TESTING=True,SECRET_KEY='fictional-school-app-key',IDENTITY_ENFORCE_IN_TESTS=True,INSTITUTE_DATABASE_DIR=self.tmp.name)
        self.ctx=app.app_context();self.ctx.push();db.drop_all();db.create_all();self.M=app.extensions['school_app_models'];self.password='Fictional-brand-password-2026'
        self.schools=[];self.clients=[]
        for code,name in [('ISF-APP-QA','ISF School System'),('SADIA-APP-QA','Sadia School')]:
            row=app.extensions['identity_helpers']['provision'](code,name,'owner@example.invalid',self.password);self.schools.append((row.id,row.storage_key,code,name))
            self.clients.append(self.login(code))
        self.mock=patch.object(auth.jwks,'get_signing_key_from_jwt',return_value=SimpleNamespace(key=self.rsa.public_key()));self.mock.start()
        self.worker=app.test_client();self.headers=self.token()
    def tearDown(self):
        self.mock.stop();db.session.remove();db.drop_all();self.ctx.pop();app.config.update(self.previous);self.tmp.cleanup()
    def token(self,**overrides):
        now=int(time.time());claims=dict(iss=auth.ISSUER,aud=auth.AUDIENCE,sub='repo:'+auth.REPOSITORY+':ref:refs/heads/main',exp=now+300,iat=now,nbf=now-1,jti='fictional-jti',repository=auth.REPOSITORY,repository_id=auth.REPOSITORY_ID,workflow_ref=auth.WORKFLOW,ref='refs/heads/main',event_name='workflow_dispatch',run_id='55',run_attempt='1',sha='a'*40)
        claims.update(overrides);value=jwt.encode(claims,self.rsa,algorithm='RS256',headers={'kid':'fictional-key'});return {'Authorization':'Bearer '+value}
    def login(self,code):
        c=app.test_client();c.get('/auth/institute')
        with c.session_transaction() as s:token=s['record_csrf']
        c.post('/auth/institute',data={'_csrf':token,'code':code})
        with c.session_transaction() as s:token=s['record_csrf']
        self.assertEqual(c.post('/auth/login',data={'_csrf':token,'email':'owner@example.invalid','password':self.password}).status_code,302);return c
    def prepare(self,index=0,name=None,version='0'):
        c=self.clients[index];c.get('/workspace/general/app-links')
        with c.session_transaction() as s:csrf=s['record_csrf']
        return c.post('/workspace/general/school-apps/prepare',data={'_csrf':csrf,'display_name':name or self.schools[index][3],'version':version})
    def claim(self,headers=None):return self.worker.post('/api/app-builder/claim',json={},headers=headers or self.headers)
    def key(self,job,other=False):
        password=job['signing']['password'];key=rsa.generate_private_key(public_exponent=65537,key_size=2048) if other else self.rsa
        subject=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'Fictional school signing')]);now=datetime.now(timezone.utc)
        certificate=x509.CertificateBuilder().subject_name(subject).issuer_name(subject).public_key(key.public_key()).serial_number(x509.random_serial_number()).not_valid_before(now-timedelta(days=1)).not_valid_after(now+timedelta(days=100)).sign(key,hashes.SHA256())
        content=pkcs12.serialize_key_and_certificates(b'schoolflow',key,certificate,None,serialization.BestAvailableEncryption(password.encode()))
        response=self.worker.put('/api/app-builder/'+job['id']+'/signing',json={'keystore':base64.b64encode(content).decode()},headers=self.headers)
        return response
    def complete(self,job):
        response=self.key(job);self.assertEqual(response.status_code,200);fingerprint=response.json['fingerprint'];blob=io.BytesIO()
        with zipfile.ZipFile(blob,'w') as archive:archive.writestr('AndroidManifest.xml','Synthetic unit-test fixture, not an installable Android build');archive.writestr('classes.dex','fictional-dex')
        content=blob.getvalue();files=[]
        for role,title in {'parents':'Parents','teacher':'Teacher','owner':'Owner','sms':'SMS'}.items():files.append(dict(role=role,label=job['branding']['name']+' '+title,package='com.schoolflow.schools.s'+job['branding']['school_key']+'.'+role+'.test',version_code=job['sequence'],signing_sha256=fingerprint,sha256=hashlib.sha256(content).hexdigest(),content=base64.b64encode(content).decode()))
        body=dict(source_sha='a'*40,artifacts=files)
        self.assertEqual(self.worker.post('/api/app-builder/'+job['id']+'/complete',json=body,headers=self.headers).status_code,200)
        return body
    def test_school_name_no_generic_substitution_and_repeated_request_idempotent(self):
        html=self.clients[0].get('/workspace/general/app-links').data
        self.assertIn(b'ISF School System Parents',html);self.assertNotIn(b'/SchoolFlow-parents-test.apk',html);self.assertNotIn(b'<h2>Sadia School Parents</h2>',html)
        self.assertEqual(self.prepare().status_code,302);self.assertEqual(self.prepare(version='1').status_code,302)
        self.assertEqual(self.M['build'].query.count(),1)
        self.assertEqual(self.prepare(1).status_code,302);self.assertEqual(self.M['build'].query.count(),2)
        response=self.claim();self.assertEqual(response.status_code,200);self.assertEqual(response.json['job']['branding']['name'],'ISF School System')
        self.assertEqual(self.claim().json['job']['id'],response.json['job']['id'])
        self.assertNotIn(b'signing',self.clients[0].get('/workspace/general/school-apps/status').data)
    def test_oidc_rejects_foreign_repo_branch_workflow_expiry_and_missing_auth(self):
        self.assertEqual(self.worker.post('/api/app-builder/claim',json={}).status_code,401)
        for changes in [dict(repository_id='wrong'),dict(repository='someone/SchoolFlow'),dict(ref='refs/heads/feature'),dict(workflow_ref='different'),dict(event_name='pull_request')]:self.assertEqual(self.claim(self.token(**changes)).status_code,403)
        self.assertEqual(self.claim(self.token(exp=int(time.time())-100)).status_code,401)
        self.assertEqual(self.claim(self.token(aud='different')).status_code,401)
        self.assertIsNone(self.claim().json['job'])
        self.assertEqual(self.claim(self.token(sub=auth.IMMUTABLE_SUBJECT)).status_code,200)
        self.assertEqual(self.claim(self.token(sub=auth.IMMUTABLE_SUBJECT.replace('@349908224/','@999999/'))).status_code,403)
    def test_artifacts_are_school_bound_and_public_links_share_no_account_access(self):
        self.prepare();job=self.claim().json['job'];self.complete(job)
        self.assertEqual(self.clients[0].get('/workspace/general/school-apps/parents/download').status_code,200)
        self.assertEqual(self.clients[1].get('/workspace/general/school-apps/parents/download').status_code,409)
        signing=db.session.get(self.M['signing'],self.schools[0][1]);self.assertNotIn(job['signing']['password'].encode(),signing.encrypted)
        anonymous=app.test_client();public='/apps/school/'+signing.download_token+'/parents.apk'
        self.assertEqual(anonymous.get(public).status_code,200)
        self.assertEqual(anonymous.get('/workspace/dashboard').status_code,302)
        self.assertEqual(anonymous.get('/api/app-builder/claim').status_code,405)
        self.assertEqual(anonymous.get('/apps/school/'+'x'*43+'/parents.apk').status_code,404)
        self.assertEqual(anonymous.get(public).headers['Cache-Control'],'private, no-store')
        model=app.extensions['identity_models']['institute'];school=db.session.get(model,self.schools[0][0]);school.active=False;db.session.commit()
        self.assertEqual(anonymous.get(public).status_code,404)
    def test_rename_and_rename_back_use_increasing_versions_and_stable_signing(self):
        self.prepare();one=self.claim().json['job'];self.complete(one);stored=db.session.get(self.M['signing'],self.schools[0][1]).fingerprint
        self.assertEqual(self.prepare(name='ISF Academy',version='1').status_code,302)
        two=self.claim().json['job'];self.assertEqual(two['sequence'],2);self.assertTrue(two['signing']['keystore'])
        # Reuse the actual stored key, never rotate it for a rename.
        blob=base64.b64decode(two['signing']['keystore']);result=self.worker.put('/api/app-builder/'+two['id']+'/signing',json={'keystore':base64.b64encode(blob).decode()},headers=self.headers);self.assertEqual(result.json['fingerprint'],stored)
        bad=self.key(two,other=True);self.assertEqual(bad.status_code,409)
        self.worker.post('/api/app-builder/'+two['id']+'/fail',json={},headers=self.headers)
        self.assertEqual(self.prepare(name='ISF School System',version='2').status_code,302)
        three=self.claim().json['job'];self.assertEqual(three['sequence'],3);self.assertEqual(three['branding']['name'],'ISF School System')
    def test_logo_change_invalidates_old_download_until_new_school_build(self):
        self.prepare();job=self.claim().json['job'];self.complete(job)
        with app.test_request_context('/'):
            g.institute_engine=app.extensions['identity_helpers']['engine'](self.schools[0][0]);profile=db.session.get(app.extensions['institute_setup_models']['profile'],1);profile.logo=b'fictional changed logo';profile.logo_mime='image/png';db.session.commit();db.session.remove()
        html=self.clients[0].get('/workspace/general/app-links').data;self.assertNotIn(b'/apps/school/',html)
        self.assertEqual(self.prepare(version='1').status_code,302);self.assertEqual(self.claim().json['job']['sequence'],2)
    def test_csrf_job_lease_and_wrong_branding_refused(self):
        self.assertEqual(self.clients[0].post('/workspace/general/school-apps/prepare',data={'display_name':'Wrong'}).status_code,400)
        self.prepare();job=self.claim().json['job'];self.key(job)
        self.assertEqual(self.worker.post('/api/app-builder/'+job['id']+'/complete',json={'artifacts':[]},headers=self.headers).status_code,422)
        self.assertEqual(self.worker.post('/api/app-builder/'+job['id']+'/fail',json={},headers=self.token(run_id='99')).status_code,409)
        self.assertEqual(self.worker.post('/api/app-builder/'+job['id']+'/fail',json={},headers=self.headers).status_code,200)
        self.assertEqual(self.prepare(version='1').status_code,302)
        self.assertEqual(self.claim().json['job']['id'],job['id'])
    def test_generic_release_url_cannot_override_school_app(self):
        c=self.clients[0];c.get('/workspace/general/app-links')
        with c.session_transaction() as s:csrf=s['record_csrf']
        self.assertEqual(c.post('/workspace/general/app-links',data={'_csrf':csrf,'app':'parents','version_token':'0','url':'https://example.invalid/generic.apk','version':'1'}).status_code,422)

if __name__=='__main__':unittest.main()
