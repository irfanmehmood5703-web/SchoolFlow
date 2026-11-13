"""Compile and return actual APKs for two isolated fictional school accounts."""
import io,os,secrets,sys,tempfile,time,threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from cryptography.hazmat.primitives.asymmetric import rsa
from PIL import Image
import jwt

def verify():
    with tempfile.TemporaryDirectory(prefix='school-app-check-') as tmp:
        os.environ['DATABASE_URL']='sqlite:///'+str(Path(tmp)/'control.db');os.environ['INSTITUTE_DATABASE_DIR']=str(Path(tmp)/'schools');os.environ['SCHOOLFLOW_FINE_WORKER']='0'
        from app import app,db
        import app_builder_auth
        from scripts.school_app_worker import run
        from werkzeug.serving import make_server
        app.config.update(TESTING=True,IDENTITY_ENFORCE_IN_TESTS=True,SECRET_KEY='fictional-build-test-only')
        ids=[];clients=[];password=secrets.token_urlsafe(24)
        with app.app_context():
            for code,name,color in [('ISF-BUILD-QA','ISF School System','#176b4a'),('SADIA-BUILD-QA','Sadia School','#365f9c')]:
                school=app.extensions['identity_helpers']['provision'](code,name,'build@example.invalid',password);ids.append(school.id)
                from flask import g
                with app.test_request_context('/'):
                    g.institute_engine=app.extensions['identity_helpers']['engine'](school.id);profile=db.session.get(app.extensions['institute_setup_models']['profile'],1)
                    image=Image.new('RGB',(200,200),color);stream=io.BytesIO();image.save(stream,format='PNG');profile.logo=stream.getvalue();profile.logo_mime='image/png';db.session.commit();db.session.remove()
                client=app.test_client();client.get('/auth/institute')
                with client.session_transaction() as session:token=session['record_csrf']
                client.post('/auth/institute',data={'_csrf':token,'code':code})
                with client.session_transaction() as session:token=session['record_csrf']
                assert client.post('/auth/login',data={'_csrf':token,'email':'build@example.invalid','password':password}).status_code==302
                client.get('/workspace/general/app-links')
                with client.session_transaction() as session:token=session['record_csrf']
                response=client.post('/workspace/general/school-apps/prepare',data={'_csrf':token,'version':'0','display_name':name});assert response.status_code==302,response.status_code
                clients.append(client)
        signing_key=rsa.generate_private_key(public_exponent=65537,key_size=2048);now=int(time.time());sha=os.environ.get('GITHUB_SHA','a'*40)
        claims=dict(iss=app_builder_auth.ISSUER,aud=app_builder_auth.AUDIENCE,sub='repo:'+app_builder_auth.REPOSITORY+':ref:refs/heads/main',exp=now+600,iat=now,nbf=now-1,jti=secrets.token_urlsafe(20),repository=app_builder_auth.REPOSITORY,repository_id=app_builder_auth.REPOSITORY_ID,workflow_ref=app_builder_auth.WORKFLOW,ref='refs/heads/main',event_name='workflow_dispatch',run_id='1234',run_attempt='1',sha=sha)
        token=jwt.encode(claims,signing_key,algorithm='RS256',headers={'kid':'fictional-rsa-key'})
        server=make_server('127.0.0.1',0,app);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start();base='http://127.0.0.1:'+str(server.server_port)
        try:
            with patch.object(app_builder_auth.jwks,'get_signing_key_from_jwt',return_value=SimpleNamespace(key=signing_key.public_key())):
                os.environ['GITHUB_SHA']=sha
                assert run(base,fixture_token=token);assert run(base,fixture_token=token)
                with app.app_context():
                    models=app.extensions['school_app_models'];schools=app.extensions['identity_models']['institute']
                    first=db.session.get(schools,ids[0]);second=db.session.get(schools,ids[1]);scope=first.storage_key
                    one=models['build'].query.filter_by(school_key=scope).one();two=models['build'].query.filter_by(school_key=second.storage_key).one()
                    assert one.state==two.state=='ready';assert one.spec['name']=='ISF School System';assert two.spec['name']=='Sadia School'
                    first_key=db.session.get(models['signing'],scope).fingerprint;second_key=db.session.get(models['signing'],second.storage_key).fingerprint;assert first_key!=second_key
                    for client,other in [(clients[0],'Sadia School'),(clients[1],'ISF School System')]:
                        html=client.get('/workspace/general/app-links').data.decode();assert '<h2>'+other+' Parents</h2>' not in html
                        assert html.count('/apps/school/')>=4
                    artifact=models['artifact'].query.filter_by(build_id=one.id,role='parents').one();assert artifact.size>10000
                    public_token=db.session.get(models['signing'],scope).download_token
                    anonymous=app.test_client();assert anonymous.get('/apps/school/'+public_token+'/parents.apk').status_code==200
                # Rebuild with a new label: package/key stay stable, version rises.
                client=clients[0]
                with client.session_transaction() as session:csrf=session['record_csrf']
                assert client.post('/workspace/general/school-apps/prepare',data={'_csrf':csrf,'version':'1','display_name':'ISF & "Academy"'}).status_code==302
                assert run(base,fixture_token=token)
                with app.app_context():
                    latest=models['build'].query.filter_by(school_key=scope).order_by(models['build'].sequence.desc()).first()
                    assert latest.state=='ready' and latest.sequence==2 and latest.spec['name']=='ISF & "Academy"'
                    assert db.session.get(models['signing'],scope).fingerprint==first_key
            print('Verified 12 compiled school APKs: two distinct schools, labels, icons, packages, school isolation, private signing, anonymous APK-only sharing and stable-key/versioned updates.')
        finally:server.shutdown();thread.join(timeout=5)

if __name__=='__main__':verify()
