"""Accept short-lived GitHub OIDC identities only from the owner's exact workflow."""
import time
import jwt
from jwt import PyJWKClient
from flask import abort,request

REPOSITORY='irfanmehmood5703-web/SchoolFlow'
REPOSITORY_ID='1439152590'
IMMUTABLE_SUBJECT='repo:irfanmehmood5703-web@349908224/SchoolFlow@1439152590:ref:refs/heads/main'
WORKFLOW=REPOSITORY+'/.github/workflows/school-app-builder.yml@refs/heads/main'
AUDIENCE='https://schoolflow-phase1.onrender.com/api/app-builder'
ISSUER='https://token.actions.githubusercontent.com'
jwks=PyJWKClient(ISSUER+'/.well-known/jwks',timeout=5,lifespan=300)

def authenticate_builder():
    authorization=request.headers.get('Authorization','')
    if not authorization.startswith('Bearer ') or len(authorization)>16000:abort(401)
    token=authorization[7:]
    try:
        header=jwt.get_unverified_header(token)
        if header.get('alg')!='RS256' or header.get('typ')!='JWT':abort(401)
        public=jwks.get_signing_key_from_jwt(token).key
        claims=jwt.decode(token,public,algorithms=['RS256'],audience=AUDIENCE,issuer=ISSUER,
            options={'require':['exp','iat','nbf','jti','sub','repository','repository_id','workflow_ref','ref','event_name','run_id','run_attempt','sha'],'strict_aud':True},leeway=20)
        if claims['repository']!=REPOSITORY or str(claims['repository_id'])!=REPOSITORY_ID:abort(403)
        if claims['workflow_ref']!=WORKFLOW or claims['ref']!='refs/heads/main':abort(403)
        if claims['sub'] not in ('repo:'+REPOSITORY+':ref:refs/heads/main',IMMUTABLE_SUBJECT):abort(403)
        if claims['event_name'] not in ('push','schedule','workflow_dispatch'):abort(403)
        if time.time()-claims['iat']>600 or claims['exp']-claims['iat']>600:abort(401)
        if not str(claims['run_id']).isdigit() or not str(claims['run_attempt']).isdigit():abort(403)
        return claims
    except (jwt.PyJWTError,ValueError,TypeError,OSError):abort(401)
