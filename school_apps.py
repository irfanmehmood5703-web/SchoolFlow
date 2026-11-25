"""Tenant-specific APK queue and private delivery. Central builder keeps signing control."""
import base64,hashlib,hmac,io,json,os,re,secrets,time,zipfile
from datetime import datetime,timedelta,timezone
from flask import Blueprint,abort,flash,g,jsonify,redirect,render_template,request,send_file,session,url_for
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey,generate_private_key
from cryptography.hazmat.primitives import hashes,serialization
from cryptography import x509
from cryptography.x509.oid import NameOID
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from app_builder_auth import authenticate_builder,QR_WORKFLOW,REPOSITORY
from itsdangerous import BadData, URLSafeTimedSerializer

SOURCE_VERSION=25
ROLES={'parents':'Parents','teacher':'Teacher','owner':'Owner','sms':'SMS','qr':'QR Attendance','face':'Face Attendance'}
API_ENDPOINTS={'school_apps.claim','school_apps.signing','school_apps.complete','school_apps.fail'}
MAX_APK=2*1024*1024
MAX_FACE_APK=170*1024*1024
APK_MIME='application/vnd.android.package-archive'
UPDATE_TICKET_MAX_AGE=30*60
BUILD_FAILED='The app build did not finish. The school owner can retry from App Links.'

def configure_school_apps(app,db):
    bp=Blueprint('school_apps',__name__)
    School=app.extensions['identity_models']['institute'];Profile=app.extensions['institute_setup_models']['profile'];Item=app.extensions['school_settings_models']['item']
    control={'info':{'identity_control':True}}
    class Gate(db.Model):
        __bind_key__=app.extensions.get('identity_bind_key')
        __tablename__='school_app_build_gate';__table_args__=control
        id=db.Column(db.Integer,primary_key=True);revision=db.Column(db.Integer,nullable=False)
    class Signing(db.Model):
        __bind_key__=app.extensions.get('identity_bind_key')
        __tablename__='school_app_signing';__table_args__=control
        school_key=db.Column(db.String(32),primary_key=True)
        encrypted=db.deferred(db.Column(db.LargeBinary,nullable=False))
        fingerprint=db.Column(db.String(64),nullable=False,default='')
        download_token=db.Column(db.String(43),nullable=False,unique=True,default=lambda:secrets.token_urlsafe(32))
    class QRRelease(db.Model):
        __bind_key__=app.extensions.get('identity_bind_key')
        __tablename__='qr_attendance_release';__table_args__=control
        id=db.Column(db.Integer,primary_key=True)
        encrypted=db.deferred(db.Column(db.LargeBinary,nullable=False))
        fingerprint=db.Column(db.String(64),nullable=False)
        published=db.Column(db.JSON,nullable=False,default=dict)
    class Build(db.Model):
        __bind_key__=app.extensions.get('identity_bind_key')
        __tablename__='school_app_build';__table_args__=(db.UniqueConstraint('school_key','sequence'),control)
        id=db.Column(db.String(43),primary_key=True,default=lambda:secrets.token_urlsafe(32))
        school_key=db.Column(db.String(32),nullable=False,index=True)
        fingerprint=db.Column(db.String(64),nullable=False)
        sequence=db.Column(db.Integer,nullable=False)
        spec=db.Column(db.JSON,nullable=False)
        logo=db.deferred(db.Column(db.LargeBinary))
        state=db.Column(db.String(20),nullable=False,default='queued')
        created=db.Column(db.Float,nullable=False,default=time.time)
        finished=db.Column(db.Float)
        worker=db.Column(db.String(80),nullable=False,default='')
        lease_until=db.Column(db.Float,nullable=False,default=0)
        attempts=db.Column(db.Integer,nullable=False,default=0)
        source_sha=db.Column(db.String(40),nullable=False,default='')
        error=db.Column(db.String(200),nullable=False,default='')
    class Artifact(db.Model):
        __bind_key__=app.extensions.get('identity_bind_key')
        __tablename__='school_app_artifact';__table_args__=(db.UniqueConstraint('build_id','role'),control)
        id=db.Column(db.Integer,primary_key=True)
        build_id=db.Column(db.String(43),db.ForeignKey('school_app_build.id'),nullable=False)
        role=db.Column(db.String(10),nullable=False)
        sha256=db.Column(db.String(64),nullable=False)
        size=db.Column(db.Integer,nullable=False)
        content=db.deferred(db.Column(db.LargeBinary,nullable=False))
    app.extensions['school_app_models']=dict(build=Build,artifact=Artifact,signing=Signing,gate=Gate)
    def lock():
        engine=db.session.get_bind(mapper=Gate.__mapper__);insert=postgres_insert if engine.dialect.name=='postgresql' else sqlite_insert
        db.session.execute(insert(Gate).values(id=1,revision=1).on_conflict_do_update(index_elements=['id'],set_={'revision':Gate.revision+1}))
    def cipher():return Fernet(base64.urlsafe_b64encode(hashlib.sha256(str(app.config.get('SCHOOL_APP_SIGNING_KEY') or app.config['SECRET_KEY']).encode()+b'school-app-signing-v1').digest()))
    def face_storage():
        from school_face_storage import configured_storage
        return configured_storage()
    def face_key(build_id,digest):
        return 'face/'+build_id+'/'+digest+'.apk'
    def required_roles(spec):
        return set(ROLES) if spec.get('face_storage') else set(ROLES)-{'face'}
    def artifact_response(school, file):
        filename='School-'+school.code+'-'+file.role+'.apk'
        if file.role=='face':
            storage=face_storage()
            if not storage:abort(503,'Face Attendance download storage is unavailable.')
            client,bucket=storage
            url=client.generate_presigned_url('get_object',Params={
                'Bucket':bucket,'Key':face_key(file.build_id,file.sha256),'ResponseContentDisposition':f'attachment; filename="{filename}"',
                'ResponseContentType':APK_MIME},ExpiresIn=600)
            response=redirect(url)
            response.headers['Referrer-Policy']='no-referrer'
        else:
            response=send_file(io.BytesIO(file.content),mimetype=APK_MIME,as_attachment=True,download_name=filename)
        response.headers['X-APK-SHA256']=file.sha256
        response.headers['Cache-Control']='private, no-store'
        return response
    def qr_release():
        row=db.session.get(QRRelease,1)
        return row.published if row else {}
    @bp.get('/api/mobile-app/update/qr-attendance')
    def qr_update():
        release=qr_release()
        return jsonify(available=bool(release),**release),200,{'Cache-Control':'no-store'}
    @bp.post('/api/app-builder/qr-attendance/signing')
    def qr_signing():
        authenticate_builder(QR_WORKFLOW);lock()
        row=db.session.get(QRRelease,1)
        if not row:
            password=secrets.token_urlsafe(32)
            key=generate_private_key(public_exponent=65537,key_size=3072)
            name=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'SchoolFlow QR Attendance')])
            now=datetime.now(timezone.utc)
            certificate=(x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
                         .serial_number(x509.random_serial_number()).not_valid_before(now-timedelta(days=1))
                         .not_valid_after(now+timedelta(days=10000)).sign(key,hashes.SHA256()))
            keystore=pkcs12.serialize_key_and_certificates(b'schoolflow',key,certificate,None,serialization.BestAvailableEncryption(password.encode()))
            private=dict(keystore=base64.b64encode(keystore).decode(),password=password)
            row=QRRelease(id=1,encrypted=cipher().encrypt(json.dumps(private).encode()),fingerprint=certificate.fingerprint(hashes.SHA256()).hex(),published={})
            db.session.add(row)
        signing=json.loads(cipher().decrypt(row.encrypted))
        fingerprint=row.fingerprint
        db.session.commit()
        return jsonify(**signing,fingerprint=fingerprint),200,{'Cache-Control':'no-store'}
    @bp.post('/api/app-builder/qr-attendance/publish')
    def qr_publish():
        claims=authenticate_builder(QR_WORKFLOW);data=payload();lock()
        row=db.get_or_404(QRRelease,1)
        version=data.get('version_code');label=data.get('version_name');digest=data.get('sha256');size=data.get('size')
        if (type(version) is not int or not 1<=version<=2100000000 or not re.fullmatch(r'[0-9]+(?:\.[0-9]+){1,3}',str(label))
            or not re.fullmatch(r'[a-f0-9]{64}',str(digest)) or type(size) is not int or not 100000<=size<=250000000
            or data.get('fingerprint')!=row.fingerprint or data.get('package')!='com.schoolflow.gate'
            or data.get('source_commit')!=claims['sha']):
            raise ValueError('Provide verified metadata for the signed QR Attendance APK.')
        tag='qr-attendance-'+str(version)+'-'+str(claims['run_id'])+'-'+str(claims['run_attempt'])
        url='https://github.com/'+REPOSITORY+'/releases/download/'+tag+'/SchoolFlow-QR-Attendance.apk'
        release=dict(version_code=version,version_name=label,url=url,sha256=digest,size=size,source_commit=claims['sha'])
        if row.published==release:return jsonify(published=True)
        if version<=row.published.get('version_code',0):abort(409,'QR Attendance release versions must increase.')
        row.published=release
        db.session.commit()
        return jsonify(published=True)
    def private_school():
        identity=getattr(g,'school_identity',None) or {}
        if identity.get('demo') or not identity.get('scope'):return None
        return School.query.filter_by(storage_key=identity['scope'],active=True).first()
    def display_name(value):
        if not isinstance(value,str) or len(value)>256:raise ValueError('Use a school app name of 1–80 characters.')
        value=' '.join(value.split())
        if not 1<=len(value)<=80 or any(ord(c)<32 or ord(c) in (*range(0x202a,0x202f),*range(0x2066,0x206a)) for c in value):raise ValueError('Use a school app name of 1–80 characters without control characters.')
        return value
    def snapshot(school):
        profile=db.session.get(Profile,1);row=Item.query.filter_by(kind='school-app-branding',scope='',name='launcher').first()
        name=display_name((row.data.get('display_name') if row else '') or ' '.join(str((profile.data.get('name') if profile else '') or school.name).split())[:80])
        logo=bytes(profile.logo) if profile and profile.logo_mime and profile.logo else b''
        spec=dict(name=name,code=school.code,school_key=school.storage_key,logo_sha256=hashlib.sha256(logo).hexdigest(),source_version=SOURCE_VERSION)
        if face_storage():spec['face_storage']=True
        fingerprint=hashlib.sha256(json.dumps(spec,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        return spec,logo,fingerprint,row
    def current(school):
        spec,logo,fingerprint,row=snapshot(school)
        build=Build.query.filter_by(school_key=school.storage_key).order_by(Build.sequence.desc()).first()
        return spec,build if build and build.fingerprint==fingerprint else None,row
    def view_model():
        school=private_school()
        if not school:return None
        spec,build,row=current(school)
        return dict(name=spec['name'],has_logo=bool(spec['logo_sha256']!=hashlib.sha256(b'').hexdigest()),state=build.state if build else 'not-requested',error=build.error if build else '',version=row.version if row else 0,can_prepare=bool(session.get('owner_id')) and not session.get('staff_id'),ready=bool(build and build.state=='ready'),sequence=build.sequence if build else 0)
    def releases(rows):
        qr=qr_release()
        for row in rows:
            if row['key'] in ('qr','face') and qr:
                row.update(official_qr=True,platform='apk',url=qr['url'],version=qr['version_name'],size=str(qr['size'])+' bytes',
                           sha256=qr['sha256'],source_commit=qr['source_commit'],
                           notes=('Shared app for Face Attendance gates. For a school-branded QR scanner, use the QR Attendance card above.' if row['key']=='face'
                                  else 'Official SchoolFlow QR Attendance APK. Register this installation using your school’s attendance device settings.'))
        school=private_school()
        if not school:return rows
        spec,build,_=current(school)
        files={f.role:f for f in Artifact.query.filter_by(build_id=build.id).all()} if build and build.state=='ready' else {}
        signer=db.session.get(Signing,school.storage_key) if files else None
        for row in rows:
            if row['key'] not in required_roles(spec):continue
            role=row['key'];file=files.get(role)
            row.pop('official_qr',None)
            row.update(label=spec['name']+' '+ROLES[role],school_managed=True,platform='apk',url='https://schoolflow-phase1.onrender.com'+url_for('school_apps.public_download',token=signer.download_token,role=role) if file and signer else '',version=('0.3' if build.spec.get('source_version',1)>=3 else '0.2')+'-school-test.'+str(build.sequence) if file else '',size=str(file.size)+' bytes' if file else '',sha256=file.sha256 if file else '',source_commit=build.source_sha if file else '',notes='School-specific Android test app. '+('Ready to install with your school name and icon.' if file else 'Prepare this school’s apps below. No generic SchoolFlow APK is substituted.'))
        return rows
    def owner():
        school=private_school()
        if not school or not session.get('owner_id') or session.get('staff_id'):abort(403)
        return school
    def csrf():
        if not session.get('record_csrf') or not hmac.compare_digest(request.form.get('_csrf',''),session['record_csrf']):abort(400)
        app.extensions['admission_capacity']['lock']()
    @bp.errorhandler(ValueError)
    def invalid(error):
        db.session.rollback()
        if request.path.startswith('/api/'):return jsonify(error=str(error)),422
        return render_template('operation_error.html',title='Check school app branding',error=str(error)),422
    @bp.post('/workspace/general/school-apps/prepare')
    def prepare():
        school=owner();csrf();lock()
        _,_,_,row=snapshot(school)
        if request.form.get('version')!=str(row.version if row else 0):raise ValueError('Branding changed. Reload before preparing apps.')
        name=request.form.get('display_name','').strip()
        if name:display_name(name)
        profile=db.session.get(Profile,1)
        base_name=display_name(' '.join(str((profile.data.get('name') if profile else '') or school.name).split())[:80])
        if name==base_name:name=''
        if row:row.data={'display_name':name}
        else:row=Item(kind='school-app-branding',scope='',name='launcher',data={'display_name':name});db.session.add(row)
        db.session.flush();spec,logo,fingerprint,_=snapshot(school)
        latest_build=Build.query.filter_by(school_key=school.storage_key).order_by(Build.sequence.desc()).first()
        existing=latest_build if latest_build and latest_build.fingerprint==fingerprint else None
        if existing and existing.state=='ready' and request.form.get('rebuild')=='1':
            if request.form.get('build_sequence')!=str(existing.sequence):raise ValueError('The app build changed. Reload before requesting an update.')
            existing=None
        if existing:
            if existing.state=='failed' and existing.attempts>=3:raise ValueError('This school build failed three times. The central software owner must review it before another attempt.')
            if existing.state=='failed':existing.state='queued';existing.error='';existing.worker='';existing.lease_until=0
        else:
            recent=Build.query.filter(Build.school_key==school.storage_key,Build.created>time.time()-86400).count()
            if recent>=3:raise ValueError('Three school app builds were already requested today. Use the existing build or try tomorrow.')
            latest=db.session.query(db.func.max(Build.sequence)).filter(Build.school_key==school.storage_key).scalar() or 0
            db.session.add(Build(school_key=school.storage_key,fingerprint=fingerprint,sequence=latest+1,spec=spec,logo=logo))
        db.session.commit()
        notice='School apps are already ready. Use the download buttons below.' if existing and existing.state=='ready' else 'School apps queued or building. The central builder checks about every 15 minutes; a first build takes additional time. Refresh this page to check progress.'
        flash(notice,'success')
        return redirect(url_for('general_tools.app_links'))
    @bp.get('/workspace/general/school-apps/status')
    def status():
        if not private_school():abort(403)
        return jsonify(**view_model())
    @bp.get('/workspace/general/school-apps/<role>/download')
    def download(role):
        if role not in ROLES:abort(404)
        school=private_school()
        if not school:abort(403)
        spec,build,_=current(school)
        if not build or build.state!='ready':abort(409,'Your school app is not ready yet. Prepare it in App Links.')
        file=Artifact.query.filter_by(build_id=build.id,role=role).first_or_404()
        return artifact_response(school,file)
    @bp.get('/apps/school/<token>/<role>.apk')
    def public_download(token,role):
        if role not in ROLES or not re.fullmatch(r'[A-Za-z0-9_-]{43}',token):abort(404)
        signing=Signing.query.filter_by(download_token=token).first_or_404()
        school=School.query.filter_by(storage_key=signing.school_key,active=True).first_or_404()
        # This opaque URL shares only the APK. It grants no account/data access.
        g.institute_engine=app.extensions['identity_helpers']['engine'](school.id);db.session.remove()
        spec,build,_=current(school)
        if not build or build.state!='ready':abort(409,'The school app is being prepared. Ask the school for its current download link.')
        file=Artifact.query.filter_by(build_id=build.id,role=role).first_or_404()
        return artifact_response(school,file)
    def update_ticket():
        return URLSafeTimedSerializer(app.config['SECRET_KEY'],salt='schoolflow-apk-update-v1')

    @bp.get('/apps/school/update/<ticket>/<role>.apk')
    def mobile_update_download(ticket,role):
        if role not in ROLES or len(ticket)>512:abort(404)
        try:
            scope,expected_role,sequence=update_ticket().loads(ticket,max_age=UPDATE_TICKET_MAX_AGE)
        except (BadData,TypeError,ValueError):
            abort(404)
        if role!=expected_role:abort(404)
        school=School.query.filter_by(storage_key=scope,active=True).first_or_404()
        g.institute_engine=app.extensions['identity_helpers']['engine'](school.id);db.session.remove()
        _,build,_=current(school)
        if not build or build.state!='ready' or build.sequence!=sequence:abort(404)
        file=Artifact.query.filter_by(build_id=build.id,role=role).first_or_404()
        return artifact_response(school,file)

    @bp.get('/api/mobile-app/update/<scope>/<role>')
    def mobile_update(scope,role):
        # An installed school-specific client checks for a newer signed APK.
        if role not in ROLES or not re.fullmatch(r'[0-9a-f]{32}',scope):abort(404)
        school=School.query.filter_by(storage_key=scope,active=True).first_or_404()
        g.institute_engine=app.extensions['identity_helpers']['engine'](school.id);db.session.remove()
        spec,build,_=current(school)
        if not build or build.state!='ready':
            return jsonify(available=False),200,{'Cache-Control':'private, no-store'}
        file=Artifact.query.filter_by(build_id=build.id,role=role).first()
        key=Signing.query.filter_by(school_key=scope).first()
        if not file or not key or not key.fingerprint:
            return jsonify(available=False),200,{'Cache-Control':'private, no-store'}
        ticket=update_ticket().dumps([scope,role,build.sequence])
        link='https://schoolflow-phase1.onrender.com'+url_for('school_apps.mobile_update_download',ticket=ticket,role=role)
        response=jsonify(available=True,version_code=build.sequence,version_name="0.3-school-test."+str(build.sequence),
                         whats_new="SchoolFlow app improvements and fixes.",minimum_supported_version_code=max(0,int(os.environ.get("SCHOOLFLOW_MIN_ANDROID_VERSION_CODE","0"))),
                         sha256=file.sha256,url=link)
        response.headers['Cache-Control']='private, no-store'
        return response
    def payload():
        if len(request.get_data(cache=True))>14*1024*1024:abort(413)
        data=request.get_json(silent=True)
        if not isinstance(data,dict):raise ValueError('Use a JSON object.')
        return data
    def worker(claims):return str(claims['run_id'])+':'+str(claims['run_attempt'])
    def leased(bid,claims):
        row=db.get_or_404(Build,bid)
        if row.state!='building' or row.worker!=worker(claims) or row.lease_until<=time.time():abort(409)
        return row
    @bp.post('/api/app-builder/claim')
    def claim():
        claims=authenticate_builder();data=payload()
        if data.get('source_version')!=SOURCE_VERSION:abort(409,'Update the central app builder before claiming school builds.')
        lock();stamp=time.time()
        # Existing school installs receive this client update with the same
        # package/signing key. New schools are still explicitly provisioned.
        latest=db.session.query(Build.school_key,db.func.max(Build.sequence)).group_by(Build.school_key).all()
        for school_key,sequence in latest:
            previous=Build.query.filter_by(school_key=school_key,sequence=sequence).one()
            upgrade=previous.state=='ready' and (previous.spec.get('source_version',1)<SOURCE_VERSION or bool(previous.spec.get('face_storage'))!=bool(face_storage()))
            recover=(previous.state=='failed' and previous.attempts==1
                     and previous.error==BUILD_FAILED and previous.spec.get('source_version')==SOURCE_VERSION)
            if not upgrade and not recover:continue
            school=School.query.filter_by(storage_key=school_key,active=True).first()
            if not school:continue
            if recover:
                # A published school can recover its first failed automatic update.
                # Preserve the same version and signing identity on retry.
                older=Build.query.filter_by(school_key=school_key,state='ready').order_by(Build.sequence.desc()).first()
                if older and older.spec.get('source_version',1)<SOURCE_VERSION:
                    previous.state='queued';previous.error='';previous.worker=''
                continue
            # Ready jobs discard their temporary logo bytes. Reload the current
            # tenant's canonical profile in an isolated session, never the
            # registry/default DB or a different school's cached Profile(1).
            school_engine=app.extensions['identity_helpers']['engine'](school.id)
            with app.app_context(),app.test_request_context('/internal/school-app-branding'):
                g.institute_engine=school_engine
                spec,logo,fingerprint,_=snapshot(school)
                db.session.remove()
            db.session.add(Build(school_key=school_key,fingerprint=fingerprint,sequence=sequence+1,spec=spec,logo=logo))
        db.session.flush()
        row=Build.query.filter_by(state='building',worker=worker(claims)).filter(Build.lease_until>stamp).first()
        if not row:
            expired=Build.query.filter(Build.state=='building',Build.lease_until<=stamp).all()
            for old in expired:
                old.state='queued' if old.attempts<3 else 'failed';old.error='The previous build did not finish.'
            db.session.flush();row=Build.query.filter_by(state='queued').order_by(Build.created).first()
            if row:row.state='building';row.worker=worker(claims);row.lease_until=stamp+1800;row.attempts+=1;row.error=''
        if not row:db.session.commit();return jsonify(job=None)
        key=db.session.get(Signing,row.school_key)
        if not key:
            key=Signing(school_key=row.school_key,encrypted=cipher().encrypt(json.dumps(dict(password=secrets.token_urlsafe(32),keystore='')).encode()));db.session.add(key)
        private=json.loads(cipher().decrypt(key.encrypted))
        job=dict(id=row.id,sequence=row.sequence,branding=row.spec,logo=base64.b64encode(row.logo or b'').decode(),signing=private)
        db.session.commit();return jsonify(job=job)
    @bp.put('/api/app-builder/<bid>/signing')
    def signing(bid):
        claims=authenticate_builder();data=payload();lock();row=leased(bid,claims);key=db.session.get(Signing,row.school_key)
        try:
            blob=base64.b64decode(data.get('keystore',''),validate=True)
            if not 100<=len(blob)<=65536:raise ValueError()
            private=json.loads(cipher().decrypt(key.encrypted));secret,cert,_=pkcs12.load_key_and_certificates(blob,private['password'].encode())
            if not isinstance(secret,RSAPrivateKey) or secret.key_size<2048 or cert is None or secret.public_key().public_numbers()!=cert.public_key().public_numbers():raise ValueError()
            fingerprint=cert.fingerprint(hashes.SHA256()).hex()
        except (ValueError,TypeError):raise ValueError('Use the issued school signing key and password.')
        if key.fingerprint and key.fingerprint!=fingerprint:abort(409,'A school update must retain its existing signing identity.')
        if not key.fingerprint:
            key.fingerprint=fingerprint;private['keystore']=base64.b64encode(blob).decode();key.encrypted=cipher().encrypt(json.dumps(private).encode())
        db.session.commit();return jsonify(saved=True,fingerprint=fingerprint)
    @bp.post('/api/app-builder/<bid>/face-upload')
    def face_upload(bid):
        claims=authenticate_builder();data=payload();row=leased(bid,claims)
        storage=face_storage()
        if not row.spec.get('face_storage') or not storage:abort(404)
        digest=data.get('sha256');size=data.get('size')
        if type(size) is not int or not 100<size<=MAX_FACE_APK or not re.fullmatch(r'[a-f0-9]{64}',str(digest)):
            raise ValueError('Provide the Face APK size and checksum.')
        client,bucket=storage
        fields={'Bucket':bucket,'Key':face_key(row.id,digest),'ContentType':APK_MIME,'ContentLength':size,'Metadata':{'sha256':digest}}
        response=jsonify(url=client.generate_presigned_url('put_object',Params=fields,ExpiresIn=900))
        response.headers['Cache-Control']='no-store'
        return response

    @bp.post('/api/app-builder/<bid>/complete')
    def complete(bid):
        claims=authenticate_builder();data=payload();lock();row=leased(bid,claims);key=db.session.get(Signing,row.school_key)
        if not key or not key.fingerprint:raise ValueError('Store the school signing identity before publishing apps.')
        files=data.get('artifacts')
        roles=required_roles(row.spec)
        if not isinstance(files,list) or len(files)!=len(roles) or {f.get('role') for f in files if isinstance(f,dict)}!=roles:raise ValueError('Provide exactly one APK for each school app.')
        if data.get('source_sha')!=claims['sha']:raise ValueError('Build provenance does not match this workflow.')
        for f in files:
            role=f['role'];expected='com.schoolflow.schools.s'+row.school_key+'.'+role+'.test'
            if f.get('package')!=expected or f.get('label')!=row.spec['name']+' '+ROLES[role] or f.get('version_code')!=row.sequence or f.get('signing_sha256')!=key.fingerprint:raise ValueError('APK branding, package, version or signing identity does not match its school.')
            if role=='face':
                storage=face_storage()
                if not storage:abort(503,'Face Attendance build storage is unavailable.')
                client,bucket=storage
                digest=f.get('sha256');size=f.get('size')
                if type(size) is not int or not 100<size<=MAX_FACE_APK or not re.fullmatch(r'[a-f0-9]{64}',str(digest)):
                    raise ValueError('Provide verified Face APK metadata.')
                header=client.head_object(Bucket=bucket,Key=face_key(row.id,digest))
                if header['ContentLength']!=size or header.get('Metadata',{}).get('sha256')!=digest:
                    raise ValueError('Uploaded Face APK metadata does not match.')
                db.session.add(Artifact(build_id=row.id,role=role,sha256=digest,size=size,content=b''))
                continue
            try:
                blob=base64.b64decode(f.get('content',''),validate=True)
                if not 100<len(blob)<=MAX_APK:raise ValueError()
                with zipfile.ZipFile(io.BytesIO(blob)) as archive:
                    if not {'AndroidManifest.xml','classes.dex'}<=set(archive.namelist()):raise ValueError()
            except (ValueError,TypeError,zipfile.BadZipFile):raise ValueError('Provide a valid compiled APK within the size limit.')
            digest=hashlib.sha256(blob).hexdigest()
            if f.get('sha256')!=digest:raise ValueError('APK checksum failed.')
            db.session.add(Artifact(build_id=row.id,role=role,sha256=digest,size=len(blob),content=blob))
        row.state='ready';row.finished=time.time();row.source_sha=claims['sha'];row.lease_until=0;row.logo=b''
        # Keep two completed APK revisions; never discard a signing identity.
        old_ids=[r.id for r in Build.query.filter_by(school_key=row.school_key,state='ready').order_by(Build.sequence.desc()).offset(2).all()]
        old_face_keys=[face_key(f.build_id,f.sha256) for f in Artifact.query.filter(Artifact.build_id.in_(old_ids),Artifact.role=='face').all()] if old_ids else []
        if old_ids:Artifact.query.filter(Artifact.build_id.in_(old_ids)).delete(synchronize_session=False)
        db.session.commit()
        if old_face_keys and (storage:=face_storage()):
            client,bucket=storage
            try:
                client.delete_objects(Bucket=bucket,Delete={'Objects':[{'Key':key} for key in old_face_keys]})
            except Exception:
                app.logger.warning('Could not clean up older Face Attendance APKs.')
        return jsonify(ready=True)
    @bp.post('/api/app-builder/<bid>/fail')
    def fail(bid):
        claims=authenticate_builder();payload();lock();row=leased(bid,claims)
        row.state='failed';row.error=BUILD_FAILED;row.lease_until=0;db.session.commit();return jsonify(saved=True)
    app.extensions['school_app_helpers']=dict(view_model=view_model,releases=releases,current=current,snapshot=snapshot,qr_release=qr_release)
    app.register_blueprint(bp)
