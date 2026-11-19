"""Android entry points. School binding narrows routing; normal auth authorises data."""
import hmac,re,secrets
from flask import Blueprint,abort,g,redirect,render_template,request,session,url_for
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

    @app.before_request
    def keep_school_binding():
        bound=binding()
        if not bound:return
        # A signed routing cookie survives normal session rotation/logout. It grants no access.
        if request.blueprint in ('identity','parent_portal','parent_messages'):
            code=(request.view_args or {}).get('code')
            if code and code.upper()!=bound['code']:abort(403,'Open the app supplied by this school.')
            if request.endpoint=='identity.institute' and request.method=='POST' and request.form.get('code','').strip().upper()!=bound['code']:abort(403,'This app belongs to '+bound['code']+'.')
            if request.endpoint=='identity.demo':abort(403)
            if request.endpoint=='identity.login':
                School=app.extensions['identity_models']['institute']
                school=School.query.filter_by(storage_key=bound['scope'],code=bound['code'],active=True).first()
                if not school or session.get('pending_institute')!=school.id:abort(403,'Reopen the school app home screen.')
        school=getattr(g,'school_identity',None)
        if school and (school.get('scope')!=bound['scope'] or bound['kind']=='parents'):abort(403,'Sign in with the account for this school app.')

    @bp.route('/mobile/<kind>',methods=['GET','POST'])
    def entry(kind):
        if kind not in ('parents','teacher','owner'):abort(404)
        token=session.setdefault('record_csrf',secrets.token_urlsafe(32));error=''
        preset=request.args.get('school','').strip().upper()
        scope=request.args.get('scope','')
        bound=binding()
        if preset and re.fullmatch(r'[A-Z0-9][A-Z0-9-]{2,39}',preset):
            School=app.extensions['identity_models']['institute']
            school=School.query.filter_by(code=preset,active=True).first_or_404()
            if scope and scope!=school.storage_key:abort(403,'The installed school app identity does not match.')
            # Old generic clients only prefill a code; new branded clients pin the immutable scope.
            if scope:
                value=dict(code=school.code,scope=school.storage_key,kind=kind)
                if bound!=value:
                    session.clear();session['record_csrf']=secrets.token_urlsafe(32)
                response=redirect(url_for('parent_portal.home',code=preset) if kind=='parents' else url_for('ops.dashboard') if session.get('institute_id')==school.id and (session.get('owner_id') if kind=='owner' else session.get('staff_id')) else url_for('identity.login'))
                if kind!='parents' and not (session.get('owner_id') or session.get('staff_id')):
                    import time
                    session.update(pending_institute=school.id,pending_at=time.time())
                response.set_cookie(COOKIE,signer().dumps(value),secure=True,httponly=True,samesite='Lax',max_age=31536000)
                return response
            if kind=='parents':return redirect(url_for('parent_portal.login',code=preset))
            return redirect(url_for('identity.institute',school=preset))
        if scope:abort(400)
        if bound:
            return redirect(url_for('mobile_clients.entry',kind=bound['kind'],school=bound['code'],scope=bound['scope']))
        if request.method=='POST':
            if not hmac.compare_digest(request.form.get('_csrf',''),token):abort(400)
            if kind!='parents':return redirect(url_for('identity.institute'))
            code=request.form.get('code','').strip().upper()
            if re.fullmatch(r'[A-Z0-9][A-Z0-9-]{2,39}',code) and code!='DEMO':return redirect(url_for('parent_portal.login',code=code))
            error='Enter the Institute Code provided by your school.'
        return render_template('mobile_entry.html',kind=kind,error=error,title='SchoolFlow '+kind.title())
    app.register_blueprint(bp)
