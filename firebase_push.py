"""Optional private FCM wake-ups for authorised mobile notification feeds.

Only opaque actor/event digests go to Google. An authenticated app fetches the
actual content from its existing scoped feed. A lease cannot outlive the
original portal sign-in; SMS leases are rechecked against device generation.
No Firebase topics, passwords, bearer keys or session cookies are stored.
"""
import base64,hashlib,hmac,json,os,re,time,threading
import urllib.request,urllib.parse,urllib.error
from cryptography.fernet import Fernet,InvalidToken
import jwt
from flask import abort,g,request,session

ROLES=('parents','owner','teacher','sms')
SCOPE='https://www.googleapis.com/auth/firebase.messaging'
PORTAL_KEYS={'parents':('parent_scope','parent_family','parent_version','parent_expiry','parent_login_phone'),
             'owner':('owner_id','owner_version','institute_id','signed_in_at'),
             'teacher':('staff_id','staff_version','institute_id','signed_in_at')}
TOKEN=re.compile(r'[A-Za-z0-9_:.\-]{20,4096}')
DIGEST=re.compile(r'[a-f0-9]{64}')

def credentials():
    if os.getenv('SCHOOLFLOW_FCM_ENABLED')!='1':return None
    try:
        cfg=json.loads(os.environ['SCHOOLFLOW_FCM_SERVICE_ACCOUNT_JSON'])
        if not re.fullmatch('[a-z][a-z0-9-]{4,62}',cfg['project_id']):return None
        if cfg['type']!='service_account' or not cfg['client_email'].endswith('.gserviceaccount.com') or 'BEGIN PRIVATE KEY' not in cfg['private_key']:return None
        return cfg
    except (KeyError,ValueError,TypeError,AttributeError):return None

def message(token,actor,ids,package):
    # Never include names, fees, phone numbers or other school data in FCM.
    return {'message':{'token':token,'data':{'kind':'schoolflow-update','actor':actor,'ids':','.join(ids[:20])},
            'android':{'priority':'HIGH','ttl':'86400s','collapse_key':'schoolflow-update','restricted_package_name':package}}}

class Transport:
    def __init__(self):
        self.lock=threading.Lock();self.cached=None
    def access(self,cfg):
        with self.lock:
            now=int(time.time());key=hashlib.sha256(cfg['private_key'].encode()).hexdigest()
            if self.cached and self.cached[0]==key and self.cached[1]>now+60:return self.cached[2]
            assertion=jwt.encode(dict(iss=cfg['client_email'],scope=SCOPE,aud='https://oauth2.googleapis.com/token',iat=now,exp=now+3600),cfg['private_key'],algorithm='RS256')
            body=urllib.parse.urlencode(dict(grant_type='urn:ietf:params:oauth:grant-type:jwt-bearer',assertion=assertion)).encode()
            req=urllib.request.Request('https://oauth2.googleapis.com/token',data=body,headers={'Content-Type':'application/x-www-form-urlencoded'})
            with urllib.request.urlopen(req,timeout=10) as res:reply=json.loads(res.read(65536))
            token=reply['access_token'];self.cached=(key,now+min(3600,int(reply['expires_in'])),token);return token
    def send(self,cfg,token,actor,ids,package):
        req=urllib.request.Request('https://fcm.googleapis.com/v1/projects/'+cfg['project_id']+'/messages:send',data=json.dumps(message(token,actor,ids,package)).encode(),headers={'Content-Type':'application/json','Authorization':'Bearer '+self.access(cfg)})
        try:
            with urllib.request.urlopen(req,timeout=10) as res:reply=json.loads(res.read(65536))
            return 'submitted' if reply.get('name') else 'unknown'
        except urllib.error.HTTPError as exc:
            try:
                details=json.loads(exc.read(65536)).get('error',{}).get('details',[])
                if any(d.get('errorCode')=='UNREGISTERED' for d in details if isinstance(d,dict)):return 'unregistered'
            except (ValueError,TypeError,AttributeError):pass
            return 'failed'
        except OSError:return 'unknown'

def configure_firebase_push(app,db):
    class Lease(db.Model):
        __bind_key__=app.extensions['identity_bind_key']
        __tablename__='identity_mobile_push'
        __table_args__={'info':{'identity_control':True}}
        id=db.Column(db.String(64),primary_key=True)
        role=db.Column(db.String(12),nullable=False)
        school_scope=db.Column(db.String(32),nullable=False,index=True)
        actor=db.Column(db.String(64),nullable=False,index=True)
        package=db.Column(db.String(160),nullable=False)
        encrypted=db.Column(db.LargeBinary,nullable=False)
        expires=db.Column(db.Float,nullable=False,index=True)
        checked=db.Column(db.Float,nullable=False,default=0,index=True)
        generation=db.Column(db.Integer,nullable=False,default=1)
        seen=db.Column(db.JSON,nullable=False,default=list)
    transport=Transport()
    def secret():return str(app.config['SECRET_KEY']).encode()
    def cipher():return Fernet(base64.urlsafe_b64encode(hashlib.sha256(secret()+b'firebase-lease-v1').digest()))
    def enabled():return credentials() is not None
    def token_id(token):return hmac.new(secret(),('fcm-token:'+token).encode(),hashlib.sha256).hexdigest()
    def package_for(scope,role):return 'com.schoolflow.schools.s'+scope+'.'+role+'.test'
    def register(role,scope,actor,principal,events):
        if not enabled():return False
        payload=request.get_json(silent=True) if role=='sms' else request.form
        if not payload or not payload.get('push_token'):return False
        token=payload.get('push_token');package=payload.get('package')
        if role not in ROLES or not isinstance(token,str) or not TOKEN.fullmatch(token) or package!=package_for(scope,role):abort(422)
        now=time.time()
        if role=='sms':
            did,generation=map(int,str(principal).split(':'));claims={'device':did,'generation':generation};expiry=now+7*86400
        else:
            claims={k:session[k] for k in PORTAL_KEYS[role] if k in session}
            expiry=float(session.get('parent_expiry',0)) if role=='parents' else float(session.get('signed_in_at',0))+28800
        if expiry<=now:abort(401)
        # A token is globally unique. A new signed-in account replaces its old
        # association. Bound registration count prevents unbounded tenant spam.
        key=token_id(token);row=db.session.get(Lease,key)
        if not row or row.actor!=actor:
            if Lease.query.filter_by(actor=actor).filter(Lease.expires>now).count()>=8:abort(429)
        if not row:
            row=Lease(id=key,seen=[],generation=1);db.session.add(row)
        if row.actor!=actor:
            row.seen=[x['id'] for x in events];row.checked=now
            row.generation=(row.generation or 0)+1
        row.role=role;row.school_scope=scope;row.actor=actor;row.package=package
        row.encrypted=cipher().encrypt(json.dumps(dict(token=token,claims=claims)).encode());row.expires=expiry
        db.session.commit();return True
    def read_feed(role,scope,actor,claims):
        # Use a fresh app/request context and the exact existing read-only
        # endpoint/permission checks. No arbitrary target or request method.
        with app.app_context(),app.test_request_context('/internal/push-school'):
            School=app.extensions['identity_models']['institute']
            school=School.query.filter_by(storage_key=scope,active=True).first()
            if not school:return None
            sid,code=school.id,school.code
            if role=='sms':
                g.institute_engine=app.extensions['identity_helpers']['engine'](sid);db.session.remove()
                D=app.extensions['sms_models']['device'];device=db.session.get(D,claims['device'])
                if not device or not device.active or device.generation!=claims['generation']:return None
                from mobile_notices import feed_data
                result=feed_data('sms',scope,str(device.id)+':'+str(device.generation),app.extensions['sms_notice_events'](device))
                return result if result['actor']==actor else None
        path='/parents/'+code+'/app/notification-feed' if role=='parents' else '/'+role+'-app/notification-feed'
        with app.app_context(),app.test_request_context(path,method='GET',base_url='https://schoolflow-phase1.onrender.com'):
            session.update(claims)
            # Existing guards revalidate account version, school, family phone,
            # staff grants and expiry. An internal request never writes cookies.
            try:
                early=app.preprocess_request()
                response=app.make_response(early if early is not None else app.dispatch_request())
                if response.status_code!=200:return None
                result=response.get_json(silent=True)
                if not isinstance(result,dict) or result.get('actor')!=actor:return None
                return result
            except Exception:
                db.session.rollback();return None
            finally:db.session.remove()
    def tick():
        cfg=credentials()
        if not cfg:return 0
        now=time.time();submitted=0
        with app.app_context():
            Lease.query.filter(Lease.expires<=now).delete(synchronize_session=False);db.session.commit()
            keys=[x[0] for x in db.session.query(Lease.id).filter(Lease.expires>now,Lease.checked<=now-55).order_by(Lease.checked).limit(100)]
            for key in keys:
                # Atomic claim across multiple gunicorn workers.
                changed=Lease.query.filter_by(id=key).filter(Lease.checked<=now-55,Lease.expires>now).update({Lease.checked:now},synchronize_session=False)
                db.session.commit()
                if changed!=1:continue
                row=db.session.get(Lease,key,populate_existing=True)
                if not row:continue
                try:
                    values=json.loads(cipher().decrypt(row.encrypted))
                    role,scope,actor,package,generation,seen=row.role,row.school_scope,row.actor,row.package,row.generation,set(row.seen)
                    db.session.remove()
                    result=read_feed(role,scope,actor,values['claims'])
                    row=db.session.get(Lease,key,populate_existing=True)
                    if not row or row.generation!=generation or row.actor!=actor or row.expires<=time.time():continue
                    if result is None:
                        # No private push on revoked or invalid account. Let a
                        # subsequent authenticated registration renew the lease.
                        db.session.delete(row);db.session.commit();continue
                    ids=[e['id'] for e in result['events'] if DIGEST.fullmatch(e['id'])]
                    fresh=[i for i in ids if i not in seen]
                    if not fresh:db.session.remove();continue
                    # At most once per revision even if network reply is lost.
                    row.seen=list(dict.fromkeys(list(seen)+ids))[-500:]
                    db.session.commit()
                    outcome=transport.send(cfg,values['token'],actor,fresh,package)
                    if outcome=='submitted':submitted+=1
                    elif outcome=='unregistered':
                        Lease.query.filter_by(id=key,generation=generation,actor=actor).delete(synchronize_session=False);db.session.commit()
                except (InvalidToken,ValueError,TypeError,KeyError,OSError):
                    db.session.rollback()
                except Exception:
                    db.session.rollback();app.logger.warning('FCM lease check failed; polling fallback remains available.')
                finally:db.session.remove()
        return submitted
    app.extensions['firebase_push_helpers']=dict(enabled=enabled,register=register,tick=tick,model=Lease,read_feed=read_feed)
    @app.cli.command('firebase-push-tick')
    def tick_cli():tick()
