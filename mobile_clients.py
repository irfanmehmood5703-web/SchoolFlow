"""Entry points for the Android portal clients; existing web auth remains authoritative."""
import hmac,re,secrets
from flask import Blueprint,abort,redirect,render_template,request,session,url_for

def configure_mobile_clients(app):
    bp=Blueprint('mobile_clients',__name__)
    @bp.route('/mobile/<kind>',methods=['GET','POST'])
    def entry(kind):
        if kind not in ('parents','teacher','owner'):abort(404)
        token=session.setdefault('record_csrf',secrets.token_urlsafe(32))
        error=''
        preset=request.args.get('school','').strip().upper()
        if preset and re.fullmatch(r'[A-Z0-9][A-Z0-9-]{2,39}',preset):
            if kind=='parents':return redirect(url_for('parent_portal.login',code=preset))
            return redirect(url_for('identity.institute',school=preset))
        if request.method=='POST':
            if not hmac.compare_digest(request.form.get('_csrf',''),token):abort(400)
            if kind!='parents':return redirect(url_for('identity.institute'))
            code=request.form.get('code','').strip().upper()
            if re.fullmatch(r'[A-Z0-9][A-Z0-9-]{2,39}',code) and code!='DEMO':return redirect(url_for('parent_portal.login',code=code))
            error='Enter the Institute Code provided by your school.'
        return render_template('mobile_entry.html',kind=kind,error=error,title='SchoolFlow '+kind.title())
    app.register_blueprint(bp)
