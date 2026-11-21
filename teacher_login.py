"""Owner-issued, ten-minute, single-use teacher QR sign-in handover."""
import base64,hashlib,hmac,io,re,secrets,time
from flask import Blueprint,abort,g,render_template,request,session,redirect,url_for
import qrcode

def configure_teacher_login(app,db,Employee):
    bp=Blueprint('teacher_login',__name__,url_prefix='/teacher-sign-in');Staff=app.extensions['staff_account_model'];School=app.extensions['identity_models']['institute']
    class Link(db.Model):
        __tablename__='teacher_sign_in_link'
        digest=db.Column(db.String(64),primary_key=True)
        staff_id=db.Column(db.Integer,nullable=False)
        version=db.Column(db.Integer,nullable=False)
        expires=db.Column(db.Float,nullable=False)
        used=db.Column(db.Boolean,nullable=False,default=False)
    app.extensions['teacher_login_model']=Link
    def issue(row):
        if row.data.get('role')!='Teacher' or not row.active or db.session.get(Employee,row.employee_id).status!='Active':abort(403)
        for link in Link.query.filter_by(staff_id=row.id,used=False):link.used=True
        token=secrets.token_urlsafe(32);db.session.add(Link(digest=hashlib.sha256(token.encode()).hexdigest(),staff_id=row.id,version=row.version,expires=time.time()+600));db.session.commit()
        url=url_for('teacher_login.enter',code=g.school_identity['code'],_external=True)+'#'+token;stream=io.BytesIO();qrcode.make(url).save(stream,format='PNG')
        response=app.make_response(render_template('teacher_qr.html',title='Teacher sign-in QR',row=row,credential_url=url,qr=base64.b64encode(stream.getvalue()).decode()));response.headers['Cache-Control']='no-store';return response
    @bp.route('/<code>',methods=['GET','POST'])
    def enter(code):
        school=School.query.filter_by(code=code.upper(),active=True).first_or_404();bound=app.extensions['mobile_client_helpers']['binding']()
        if bound and (bound['kind']!='teacher' or bound['scope']!=school.storage_key or bound['code']!=school.code):abort(403)
        school_id,key,name=school.id,school.storage_key,school.name
        g.institute_engine=app.extensions['identity_helpers']['engine'](school_id);db.session.remove();g.school_identity=dict(code=code.upper(),scope=key,name=name,demo=False)
        if request.method=='POST':
            if not session.get('record_csrf') or not hmac.compare_digest(session['record_csrf'],request.form.get('_csrf','')):abort(400)
            token=request.form.get('credential','')
            if not re.fullmatch(r'[A-Za-z0-9_-]{43}',token):abort(403,'This school sign-in link is invalid or expired.')
            app.extensions['admission_capacity']['lock']();link=db.session.get(Link,hashlib.sha256(token.encode()).hexdigest())
            staff=app.extensions['staff_access_helpers']['resolve'](link.staff_id,link.version) if link else None
            if not link or link.used or link.expires<time.time() or not staff or staff.data.get('role')!='Teacher':abort(403,'This sign-in link expired, was used or was revoked. Ask the school for a new QR.')
            sid,version=staff.id,staff.version;link.used=True;db.session.commit();session.clear();session.update(staff_id=sid,staff_version=version,institute_id=school_id,signed_in_at=time.time(),record_csrf=secrets.token_urlsafe(32));return redirect(url_for('teacher_app.home'))
        response=app.make_response(render_template('teacher_signin.html',title='Teacher QR sign-in',school_name=name,school_code=code.upper()));response.headers['Cache-Control']='no-store';return response
    app.extensions['teacher_login_helpers']=dict(issue=issue)
    app.register_blueprint(bp)
