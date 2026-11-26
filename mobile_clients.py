"""Android entry points. School binding narrows routing; normal auth authorises data."""
import hmac,io,re,secrets
from flask import Blueprint,abort,g,redirect,render_template,request,send_file,session,url_for
from itsdangerous import URLSafeSerializer,BadSignature

COOKIE='schoolflow_mobile'

def configure_mobile_clients(app):
    bp=Blueprint('mobile_clients',__name__)
    def signer():return URLSafeSerializer(app.config['SECRET_KEY'],salt='schoolflow-mobile-v1')
    def binding():
        try:
            value=signer().loads(request.cookies.get(COOKIE,''))
            if isinstance(value,dict) and value.get('kind') in ('parents','teacher','owner'):return value
        except BadSignature:pass
        return None
    def role_allowed(role):
        bound=binding()
        return not bound or bound['kind']==role
    app.extensions['mobile_client_helpers']=dict(binding=binding,role_allowed=role_allowed)

    def school_brand(with_logo=False):
        bound=binding()
        if not bound:return None
        School=app.extensions['identity_models']['institute']
        school=School.query.filter_by(storage_key=bound['scope'],code=bound['code'],active=True).first()
        if not school:return None
        result=dict(name=school.name,code=school.code,scope=school.storage_key,kind=bound['kind'],has_logo=False,logo=b'',mime='')
        engine=app.extensions['identity_helpers']['engine'](school.id)
        # Separate identity maps are essential: every tenant has Profile(1).
        with app.app_context(),app.test_request_context('/internal/mobile-school-brand'):
            g.institute_engine=engine
            Profile=app.extensions['institute_setup_models']['profile']
            profile=db.session.query(Profile.data,Profile.logo_mime,db.func.length(Profile.logo)).filter(Profile.id==1).first()
            if profile:
                result['name']=profile[0].get('name') or result['name']
                result['has_logo']=bool(profile[1] and profile[2])
                if with_logo and result['has_logo']:result.update(logo=bytes(db.session.get(Profile,1).logo),mime=profile[1])
            db.session.remove()
        return result
    # Flask-SQLAlchemy is already configured by the application factory.
    db=app.extensions['sqlalchemy']
    @app.context_processor
    def branding_context():
        if request.blueprint not in ('identity','mobile_clients','parent_portal'):return {}
        brand=school_brand()
        return dict(app_school_brand=brand) if brand else {}

    @bp.get('/mobile/school-logo/<scope>')
    def school_logo(scope):
        bound=binding()
        if not bound or bound['scope']!=scope:abort(404)
        brand=school_brand(True)
        if not brand or not brand['logo'] or brand['mime'] not in ('image/png','image/jpeg','image/webp'):abort(404)
        response=send_file(io.BytesIO(brand['logo']),mimetype=brand['mime'])
        response.headers['Cache-Control']='private, no-store';response.headers['X-Content-Type-Options']='nosniff'
        return response

    @app.before_request
    def keep_school_binding():
        bound=binding()
        if not bound:return
        # A signed routing cookie survives normal session rotation/logout. It grants no access.
        if request.blueprint in ('identity','parent_portal','parent_messages'):
            School=app.extensions['identity_models']['institute']
            school=School.query.filter_by(storage_key=bound['scope'],code=bound['code'],active=True).first()
            if not school:abort(403,'Reopen the current app supplied by your school.')
            if request.endpoint=='identity.institute' and request.method=='GET':
                if bound['kind']=='parents':return redirect(url_for('parent_portal.home',code=bound['code']))
                import time
                session.update(pending_institute=school.id,pending_at=time.time())
                return redirect(url_for('identity.login'))
            code=(request.view_args or {}).get('code')
            if code and code.upper()!=bound['code']:abort(403,'Open the app supplied by this school.')
            if request.endpoint=='identity.institute' and request.method=='POST' and request.form.get('code','').strip().upper()!=bound['code']:abort(403,'This app belongs to '+bound['code']+'.')
            if request.endpoint=='identity.demo':abort(403)
            if request.endpoint=='identity.login':
                if session.get('pending_institute')!=school.id:abort(403,'Reopen the school app home screen.')
        school=getattr(g,'school_identity',None)
        if school and (school.get('scope')!=bound['scope'] or bound['kind']=='parents'):abort(403,'Sign in with the account for this school app.')
        # Recover any old session issued to a non-teacher before the login role check.
        principal=getattr(g,'staff_principal',None)
        if school and bound['kind']=='teacher' and (not principal or principal.data.get('role')!='Teacher'):
            session.clear()
            return redirect(url_for('identity.institute'))

    @bp.route('/mobile/<kind>',methods=['GET','POST'])
    def entry(kind):
        if kind not in ('parents','teacher','owner'):abort(404)
        token=session.setdefault('record_csrf',secrets.token_urlsafe(32));error=''
        preset=request.args.get('school','').strip().upper()
        scope=request.args.get('scope','')
        bound=binding()
        if request.method=='POST' and kind=='teacher' and not preset and not scope:
            if not hmac.compare_digest(request.form.get('_csrf',''),token):abort(400)
            preset=request.form.get('code','').strip().upper()
            if bound and bound['kind']=='teacher' and preset!=bound['code']:abort(403,'This app belongs to '+bound['code']+'.')
            if not re.fullmatch(r'[A-Z0-9][A-Z0-9-]{2,39}',preset) or preset=='DEMO':
                return render_template('mobile_entry.html',kind=kind,error='Enter the Institute Code provided by your school.',title='SchoolFlow Teacher')
        if preset and re.fullmatch(r'[A-Z0-9][A-Z0-9-]{2,39}',preset):
            School=app.extensions['identity_models']['institute']
            school=School.query.filter_by(code=preset,active=True).first()
            if not school:
                if kind=='teacher' and not scope:
                    return render_template('mobile_entry.html',kind=kind,error='Institute code not recognised. Check the code supplied by your school.',title='SchoolFlow Teacher')
                abort(404)
            if scope and scope!=school.storage_key:abort(403,'The installed school app identity does not match.')
            # The generic Teacher App also needs a teacher binding to reach the
            # correct login and dashboard; the school-specific scope is still verified above.
            if scope or kind=='teacher':
                if kind=='teacher' and not scope and bound and bound['kind']=='teacher' and bound['code']!=preset:
                    abort(403,'This app belongs to '+bound['code']+'.')
                value=dict(code=school.code,scope=school.storage_key,kind=kind)
                if bound!=value:
                    session.clear();session['record_csrf']=secrets.token_urlsafe(32)
                response=redirect(url_for('parent_portal.home',code=preset) if kind=='parents' else url_for('owner_app.home') if kind=='owner' and session.get('institute_id')==school.id and session.get('owner_id') else url_for('teacher_app.home') if kind=='teacher' and session.get('institute_id')==school.id and session.get('staff_id') else url_for('ops.dashboard') if session.get('institute_id')==school.id and session.get('owner_id') else url_for('identity.login'))
                if kind!='parents' and not (session.get('owner_id') or session.get('staff_id')):
                    import time
                    session.update(pending_institute=school.id,pending_at=time.time())
                response.set_cookie(COOKIE,signer().dumps(value),secure=True,httponly=True,samesite='Lax',max_age=31536000)
                return response
            if kind=='parents':return redirect(url_for('parent_portal.login',code=preset))
            return redirect(url_for('identity.institute',school=preset))
        if scope:abort(400)
        if bound and (kind!='teacher' or bound['kind']=='teacher'):
            return redirect(url_for('mobile_clients.entry',kind=bound['kind'],school=bound['code'],scope=bound['scope']))
        if request.method=='POST':
            if not hmac.compare_digest(request.form.get('_csrf',''),token):abort(400)
            if kind!='parents':return redirect(url_for('identity.institute'))
            code=request.form.get('code','').strip().upper()
            if re.fullmatch(r'[A-Z0-9][A-Z0-9-]{2,39}',code) and code!='DEMO':return redirect(url_for('parent_portal.login',code=code))
            error='Enter the Institute Code provided by your school.'
        return render_template('mobile_entry.html',kind=kind,error=error,title='SchoolFlow '+kind.title())
    app.register_blueprint(bp)
