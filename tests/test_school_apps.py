"""School-branded APK orchestration: real tenant login, signed OIDC and isolation."""
import os,tempfile,time,unittest,base64,io,zipfile,hashlib,secrets
from urllib.parse import urlsplit
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
    def claim(self,headers=None):return self.worker.post('/api/app-builder/claim',json={'source_version':13},headers=headers or self.headers)
    def key(self,job,other=False):
        if job['signing'].get('keystore') and not other:return self.worker.put('/api/app-builder/'+job['id']+'/signing',json={'keystore':job['signing']['keystore']},headers=self.headers)
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
        for role,title in {'parents':'Parents','teacher':'Teacher','owner':'Owner','sms':'SMS','qr':'QR Attendance'}.items():files.append(dict(role=role,label=job['branding']['name']+' '+title,package='com.schoolflow.schools.s'+job['branding']['school_key']+'.'+role+'.test',version_code=job['sequence'],signing_sha256=fingerprint,sha256=hashlib.sha256(content).hexdigest(),content=base64.b64encode(content).decode()))
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

    def test_qr_release_uses_a_separate_workflow_and_persistent_key(self):
        manifest='/api/mobile-app/update/qr-attendance'
        signing='/api/app-builder/qr-attendance/signing'
        publish='/api/app-builder/qr-attendance/publish'
        self.assertEqual(self.worker.get(manifest).json,{'available':False})
        self.assertEqual(self.worker.post(signing).status_code,401)
        self.assertEqual(self.worker.post(signing,headers=self.headers).status_code,403)
        qr=self.token(workflow_ref=auth.QR_WORKFLOW)
        self.assertEqual(self.claim(qr).status_code,403)
        first=self.worker.post(signing,headers=qr)
        self.assertEqual(first.status_code,200)
        credentials=first.json
        self.assertEqual(self.worker.post(signing,headers=self.token(workflow_ref=auth.QR_WORKFLOW,run_id='56')).json,credentials)
        key,cert,_=pkcs12.load_key_and_certificates(base64.b64decode(credentials['keystore']),credentials['password'].encode())
        self.assertEqual(cert.fingerprint(hashes.SHA256()).hex(),credentials['fingerprint'])
        self.assertEqual(key.key_size,3072)
        release=dict(package='com.schoolflow.gate',version_code=7,version_name='0.7',
                     size=120000000,sha256='c'*64,fingerprint=credentials['fingerprint'],source_commit='a'*40)
        self.assertEqual(self.worker.post(publish,json={**release,'fingerprint':'f'*64},headers=qr).status_code,422)
        self.assertEqual(self.worker.post(publish,json=release,headers=qr).status_code,200)
        self.assertEqual(self.worker.post(publish,json=release,headers=qr).status_code,200)
        self.assertEqual(self.worker.post(publish,json={**release,'version_code':6},headers=qr).status_code,409)
        public=self.worker.get(manifest)
        self.assertTrue(public.json['available'])
        self.assertEqual(public.json['version_code'],7)
        self.assertNotIn('keystore',public.json)
        self.assertIn('/qr-attendance-7-55-1/SchoolFlow-QR-Attendance.apk',public.json['url'])
        self.assertIn(public.json['url'].encode(),self.clients[0].get('/workspace/general/app-links').data)
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
    def test_installed_apps_check_and_download_updates_without_a_web_session(self):
        self.prepare();job=self.claim().json['job'];self.complete(job)
        scope=self.schools[0][1]
        signing=db.session.get(self.M['signing'],scope)
        phone=app.test_client()
        for role in ('parents','teacher','owner','sms','qr'):
            info=phone.get('/api/mobile-app/update/'+scope+'/'+role)
            self.assertEqual(info.status_code,200)
            self.assertIn('no-store',info.headers['Cache-Control'])
            self.assertEqual(info.json['version_code'],job['sequence'])
            self.assertNotIn(signing.download_token,info.json['url'])
            link=urlsplit(info.json['url'])
            self.assertEqual(link.netloc,'schoolflow-phase1.onrender.com')
            self.assertTrue(link.path.startswith('/apps/school/update/'))
            binary=phone.get(link.path)
            self.assertEqual(binary.status_code,200)
            self.assertEqual(hashlib.sha256(binary.data).hexdigest(),info.json['sha256'])
            wrong_role='sms' if role!='sms' else 'owner'
            self.assertEqual(phone.get(link.path.rsplit('/',1)[0]+'/'+wrong_role+'.apk').status_code,404)
            now=time.time()
            with patch('itsdangerous.timed.time.time',return_value=now+3600):
                self.assertEqual(phone.get(link.path).status_code,404)
        self.assertFalse(phone.get('/api/mobile-app/update/'+self.schools[1][1]+'/sms').json['available'])
        self.assertEqual(phone.get('/workspace/dashboard').status_code,302)

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
    def test_ready_app_can_request_new_code_build_with_stable_school_identity(self):
        self.prepare();job=self.claim().json['job'];self.complete(job)
        c=self.clients[0]
        with c.session_transaction() as session:csrf=session['record_csrf']
        data=dict(_csrf=csrf,version='1',display_name=self.schools[0][3],rebuild='1',build_sequence='0')
        self.assertEqual(c.post('/workspace/general/school-apps/prepare',data=data).status_code,422)
        data['build_sequence']='1'
        self.assertEqual(c.post('/workspace/general/school-apps/prepare',data=data).status_code,302)
        update=self.claim().json['job'];self.assertEqual(update['sequence'],2)
        self.assertEqual(update['branding']['school_key'],job['branding']['school_key'])
        self.assertTrue(update['signing']['keystore'])
        # Repeated clicks while queued do not allocate extra builds.
        data['version']=str(c.get('/workspace/general/school-apps/status').json['version'])
        self.assertEqual(c.post('/workspace/general/school-apps/prepare',data=data).status_code,302)
        self.assertEqual(self.M['build'].query.count(),2)

    def test_central_update_queues_existing_school_once_and_refuses_old_worker(self):
        self.prepare();job=self.claim().json['job'];self.complete(job)
        old=self.M['build'].query.one();old.spec={**old.spec,'source_version':1};db.session.commit()
        self.assertEqual(self.worker.post('/api/app-builder/claim',json={},headers=self.headers).status_code,409)
        update=self.claim().json['job'];self.assertEqual(update['sequence'],2)
        self.assertEqual(update['branding']['source_version'],13)
        self.assertEqual(self.claim().json['job']['id'],update['id'])
        self.assertEqual(self.M['build'].query.count(),2)

    def test_client_upgrade_reloads_each_tenants_saved_logo_after_old_bytes_are_discarded(self):
        from PIL import Image
        logos=[]
        for index,color in enumerate(['#176b4a','#8b2454']):
            stream=io.BytesIO();Image.new('RGB',(120,120),color).save(stream,format='PNG');logos.append(stream.getvalue())
            with app.test_request_context('/'):
                g.institute_engine=app.extensions['identity_helpers']['engine'](self.schools[index][0]);profile=db.session.get(app.extensions['institute_setup_models']['profile'],1);profile.logo=logos[index];profile.logo_mime='image/png';db.session.commit();db.session.remove()
            self.assertEqual(self.prepare(index).status_code,302);job=self.claim().json['job'];self.complete(job)
        for row in self.M['build'].query.all():
            self.assertEqual(row.logo,b'');row.spec={**row.spec,'source_version':3}
        db.session.commit()
        seen=set()
        for _ in range(2):
            job=self.claim().json['job'];scope=job['branding']['school_key'];index=next(i for i,school in enumerate(self.schools) if school[1]==scope)
            self.assertNotIn(scope,seen);seen.add(scope)
            self.assertEqual(base64.b64decode(job['logo']),logos[index]);self.assertEqual(job['branding']['logo_sha256'],hashlib.sha256(logos[index]).hexdigest());self.assertEqual(job['sequence'],2);self.complete(job)
        self.assertEqual(seen,{school[1] for school in self.schools})

    def test_failed_central_update_retries_once_with_the_same_build_and_key(self):
        self.prepare();original=self.claim().json['job'];self.complete(original)
        old=self.M['build'].query.one();old.spec={**old.spec,'source_version':10};db.session.commit()
        update=self.claim().json['job']
        self.assertEqual(update['sequence'],original['sequence']+1)
        fail='/api/app-builder/'+update['id']+'/fail'
        self.assertEqual(self.worker.post(fail,json={},headers=self.headers).status_code,200)
        retry=self.claim().json['job']
        self.assertEqual(retry['id'],update['id'])
        self.assertEqual(retry['signing'],update['signing'])
        self.assertEqual(self.worker.post(fail,json={},headers=self.headers).status_code,200)
        self.assertIsNone(self.claim().json['job'])

    def test_signin_branding_and_logo_are_bound_to_installed_school(self):
        from PIL import Image
        logos=[]
        for index,color in enumerate(['#176b4a','#3a4070']):
            stream=io.BytesIO();Image.new('RGB',(90,90),color).save(stream,format='PNG');logos.append(stream.getvalue())
            with app.test_request_context('/'):
                g.institute_engine=app.extensions['identity_helpers']['engine'](self.schools[index][0]);profile=db.session.get(app.extensions['institute_setup_models']['profile'],1);profile.logo=logos[index];profile.logo_mime='image/png';db.session.commit();db.session.remove()
        for index in range(2):
            c=app.test_client();iid,scope,code,name=self.schools[index];c.get('/mobile/owner?school='+code+'&scope='+scope)
            page=c.get('/auth/login');self.assertEqual(page.status_code,200);self.assertIn(name.encode(),page.data);self.assertIn(('/mobile/school-logo/'+scope).encode(),page.data);self.assertNotIn(b'Software owner',page.data)
            logo=c.get('/mobile/school-logo/'+scope);self.assertEqual(logo.data,logos[index]);self.assertEqual(logo.headers['Cache-Control'],'private, no-store');self.assertEqual(c.get('/mobile/school-logo/'+self.schools[1-index][1]).status_code,404)
            with c.session_transaction() as session:self.assertNotIn('owner_id',session)
        self.assertIn(b'SchoolFlow',app.test_client().get('/auth/institute').data)

    def test_branded_portal_pins_school_preserves_home_session_and_role(self):
        c=app.test_client();school_id,scope,code,_=self.schools[0]
        entry='/mobile/owner?school='+code+'&scope='+scope
        response=c.get(entry);self.assertEqual(response.status_code,302)
        self.assertIn('/auth/login',response.location)
        self.assertIn('Secure',response.headers['Set-Cookie'])
        with c.session_transaction() as session:csrf=session['record_csrf']
        self.assertEqual(c.post('/auth/institute',data={'_csrf':csrf,'code':self.schools[1][2]}).status_code,403)
        self.assertEqual(c.post('/auth/login',data={'_csrf':csrf,'email':'owner@example.invalid','password':self.password}).status_code,302)
        self.assertEqual(c.get('/workspace/dashboard').status_code,200)
        self.assertIn('/owner-app',c.get(entry).location)
        with c.session_transaction() as session:csrf=session['record_csrf']
        self.assertIn('/mobile/owner',c.post('/auth/logout',data={'_csrf':csrf}).location)
        self.assertIn('/auth/login',c.get('/auth/institute').location)
        with c.session_transaction() as session:csrf=session['record_csrf']
        self.assertEqual(c.post('/auth/login',data={'_csrf':csrf,'email':'owner@example.invalid','password':self.password}).status_code,302)
        self.assertEqual(c.get('/parents/'+self.schools[1][2]+'/login').status_code,403)
        self.assertEqual(c.get('/mobile/owner?school='+code+'&scope='+'a'*32).status_code,403)
        # A teacher-branded portal does not accept an owner password as a staff login.
        response=c.get('/mobile/teacher?school='+code+'&scope='+scope)
        with c.session_transaction() as session:csrf=session['record_csrf']
        self.assertEqual(c.post('/auth/login',data={'_csrf':csrf,'email':'owner@example.invalid','password':self.password}).status_code,200)
        with c.session_transaction() as session:self.assertNotIn('owner_id',session)
        # Parent app cannot reuse owner or staff credentials to open the workspace.
        self.assertEqual(c.get('/mobile/parents?school='+code+'&scope='+scope).status_code,302)
        self.assertEqual(c.get('/parents/'+code+'/login').status_code,200)
        self.assertEqual(c.get('/parents/'+self.schools[1][2]+'/login').status_code,403)

    def test_generic_release_url_cannot_override_school_app(self):
        c=self.clients[0];c.get('/workspace/general/app-links')
        with c.session_transaction() as s:csrf=s['record_csrf']
        self.assertEqual(c.post('/workspace/general/app-links',data={'_csrf':csrf,'app':'parents','version_token':'0','url':'https://example.invalid/generic.apk','version':'1'}).status_code,422)

class CompiledSchoolIconTests(unittest.TestCase):
    def test_optimized_icon_resource_path_is_verified_by_pixels(self):
        from pathlib import Path
        from PIL import Image
        from scripts.school_app_worker import verify_school_icon
        with tempfile.TemporaryDirectory() as folder:
            expected=Path(folder)/'school_icon_foreground.png'
            Image.new('RGBA',(20,20),'#176b4a').save(expected)
            stream=io.BytesIO()
            with zipfile.ZipFile(stream,'w') as archive:archive.writestr('res/aB.png',expected.read_bytes())
            with zipfile.ZipFile(stream) as archive:verify_school_icon(archive,expected)
            Image.new('RGBA',(20,20),'#999999').save(expected)
            with zipfile.ZipFile(stream) as archive:
                with self.assertRaisesRegex(RuntimeError,'school logo'):verify_school_icon(archive,expected)

class BrandFallbackTests(unittest.TestCase):
    def test_existing_acronyms_and_approved_logo_hash(self):
        import mobile.clients.prepare_branding as branding
        from pathlib import Path
        self.assertEqual(branding.school_initials('ISF SCHOOL SYSTEM'),'ISF')
        self.assertEqual(branding.school_initials('DPS Faisalabad'),'DPS')
        self.assertEqual(branding.school_initials('Sadia School'),'SS')
        self.assertEqual(branding.school_initials('Beaconhouse School System'),'BSS')
        data=dict(name='ISF SCHOOL SYSTEM',school_key='a'*32,code='ISF001',logo_sha256=hashlib.sha256(b'approved logo bytes').hexdigest())
        with tempfile.TemporaryDirectory() as folder,patch.object(branding,'ROOT',Path(folder)):
            with self.assertRaisesRegex(ValueError,'approved branding'):branding.prepare(data,b'')
            self.assertFalse((Path(folder)/'generated-school-res').exists())

if __name__=='__main__':unittest.main()
