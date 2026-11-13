"""Central software-owner provisioning; school logins never grant vendor access."""
import hmac
import secrets
import time
from functools import wraps

from flask import Blueprint, abort, flash, redirect, render_template, request, session, url_for
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from werkzeug.security import check_password_hash, generate_password_hash


def configure_vendor_admin(app, db):
    bp=Blueprint('vendor',__name__,url_prefix='/vendor')
    bind_key=app.extensions.get('identity_bind_key')
    control={'info':{'identity_control':True}}
    helpers=app.extensions['identity_helpers']
    School=app.extensions['identity_models']['institute']
    Owner=app.extensions['identity_models']['owner']

    class Vendor(db.Model):
        __bind_key__=bind_key
        __tablename__='vendor_owner';__table_args__=control
        id=db.Column(db.Integer,primary_key=True)
        email=db.Column(db.String(254),nullable=False)
        password_hash=db.Column(db.String(300),nullable=False)
        version=db.Column(db.Integer,nullable=False,default=1)

    class Gate(db.Model):
        __bind_key__=bind_key
        __tablename__='vendor_provision_gate';__table_args__=control
        id=db.Column(db.Integer,primary_key=True)
        revision=db.Column(db.Integer,nullable=False)

    class Audit(db.Model):
        __bind_key__=bind_key
        __tablename__='vendor_audit';__table_args__=control
        id=db.Column(db.Integer,primary_key=True)
        actor=db.Column(db.String(254),nullable=False)
        action=db.Column(db.String(40),nullable=False)
        school_code=db.Column(db.String(40),nullable=False,default='')
        created=db.Column(db.Float,nullable=False,default=time.time)

    app.extensions['vendor_models']=dict(owner=Vendor,gate=Gate,audit=Audit)
    dummy=generate_password_hash(secrets.token_urlsafe(32))

    def lock():
        engine=db.session.get_bind(mapper=Gate.__mapper__)
        insert=pg_insert if engine.dialect.name=='postgresql' else sqlite_insert
        db.session.execute(insert(Gate).values(id=1,revision=1).on_conflict_do_update(index_elements=['id'],set_={'revision':Gate.revision+1}))

    def matches(a,b):return hmac.compare_digest(a.encode(),b.encode())

    @bp.before_request
    def bounded_form():
        if request.content_length and request.content_length>16384:abort(413)

    def password_valid(value):return isinstance(value,str) and 12<=len(value)<=128

    def sign_in(user):
        session.clear()
        session.update(vendor_id=user.id,vendor_version=user.version,vendor_signed_at=time.time(),record_csrf=secrets.token_urlsafe(32))

    def current():
        if session.get('vendor_id')!=1 or time.time()-session.get('vendor_signed_at',0)>3600:return None
        user=db.session.get(Vendor,1)
        return user if user and user.version==session.get('vendor_version') else None

    def required(fn):
        @wraps(fn)
        def wrapped(*args,**kwargs):
            if not current():return redirect(url_for('vendor.login'))
            return fn(*args,**kwargs)
        return wrapped

    @bp.after_request
    def private_response(response):
        response.headers['Cache-Control']='no-store'
        response.headers['Referrer-Policy']='no-referrer'
        return response

    @bp.route('/setup',methods=['GET','POST'])
    def setup():
        if db.session.get(Vendor,1):return redirect(url_for('vendor.login'))
        enabled=bool(app.config.get('VENDOR_SETUP_HASH'))
        error=None
        if request.method=='POST':
            helpers['csrf']()
            if not enabled:abort(404)
            if helpers['limited']('vendor-setup','bootstrap'):abort(429,'Too many attempts. Try again in 15 minutes.')
            token=request.form.get('setup_code','')
            if len(token)>200 or not check_password_hash(app.config['VENDOR_SETUP_HASH'],token):
                error='The private setup code is incorrect.'
            else:
                email=request.form.get('email','').strip().casefold()
                password=request.form.get('password','')
                if not helpers['valid_email'](email) or not password_valid(password):error='Enter a valid email and a password of 12–128 characters.'
                elif not matches(password,request.form.get('confirm','')):error='The passwords do not match.'
                else:
                    try:
                        lock()
                        if db.session.get(Vendor,1):
                            db.session.rollback();return redirect(url_for('vendor.login'))
                        user=Vendor(id=1,email=email,password_hash=generate_password_hash(password))
                        db.session.add(user);db.session.add(Audit(actor=email,action='owner-setup'));db.session.commit()
                        sign_in(user)
                        return redirect(url_for('vendor.schools'))
                    except IntegrityError:
                        db.session.rollback();return redirect(url_for('vendor.login'))
        return render_template('vendor_login.html',title='Software owner setup',mode='setup',enabled=enabled,error=error),422 if error else 200

    @bp.route('/login',methods=['GET','POST'])
    def login():
        if current():return redirect(url_for('vendor.schools'))
        error=None
        configured=db.session.get(Vendor,1) is not None
        if request.method=='POST':
            helpers['csrf']()
            email=request.form.get('email','').strip().casefold()[:254]
            if helpers['limited']('vendor-login',email):abort(429,'Too many attempts. Try again in 15 minutes.')
            user=db.session.get(Vendor,1)
            password=request.form.get('password','')
            valid=check_password_hash(user.password_hash if user else dummy,password[:128])
            if not user or not valid or len(password)>128 or email!=user.email:error='Email or password is incorrect.'
            else:
                sign_in(user);return redirect(url_for('vendor.schools'))
        return render_template('vendor_login.html',title='Software owner sign in',mode='login',configured=configured,error=error),401 if error else 200

    @bp.post('/logout')
    @required
    def logout():
        helpers['csrf']();session.clear();return redirect(url_for('vendor.login'))

    @bp.route('/schools',methods=['GET','POST'])
    @required
    def schools():
        error=None
        if request.method=='POST':
            helpers['csrf']()
            if helpers['limited']('vendor-create',current().email):abort(429,'Try again in 15 minutes.')
            password=request.form.get('password','')
            if not matches(password,request.form.get('confirm','')):error='The passwords do not match.'
            else:
                try:
                    lock()
                    db.session.add(Audit(actor=current().email,action='school-created',school_code=request.form.get('code','').strip().upper()[:40]))
                    school=helpers['provision'](request.form.get('code',''),request.form.get('name',''),request.form.get('email',''),password)
                    flash('Private school '+school.code+' created. Use its Institute Code and owner login to sign in.','success')
                    return redirect(url_for('vendor.schools',q=school.code))
                except ValueError as exc:db.session.rollback();error=str(exc)
                except IntegrityError:db.session.rollback();error='This institute code or owner is already registered.'
                except SQLAlchemyError:
                    db.session.rollback();app.logger.error('Private school provisioning failed; transaction rolled back.')
                    error='The school could not be created. Please retry; no completed account was published.'
        q=request.args.get('q','').strip()[:160]
        try:page=max(1,int(request.args.get('page','1')))
        except ValueError:page=1
        query=School.query
        if q:query=query.filter(db.or_(School.code.contains(q,autoescape=True),School.name.contains(q,autoescape=True)))
        pagination=query.order_by(School.id.desc()).paginate(page=page,per_page=20,error_out=False)
        ids=[school.id for school in pagination.items]
        owners=Owner.query.filter(Owner.institute_id.in_(ids)).all() if ids else []
        return render_template('vendor_schools.html',title='Private school accounts',pagination=pagination,owners={o.institute_id:o for o in owners},q=q,error=error,vendor=current(),durable=helpers['control_engine']().dialect.name=='postgresql'),422 if error else 200

    @bp.post('/schools/<int:school_id>/reset-password')
    @required
    def reset_password(school_id):
        helpers['csrf']()
        if helpers['limited']('vendor-reset',current().email):abort(429)
        lock()
        school=db.session.get(School,school_id)
        owner=Owner.query.filter_by(institute_id=school_id).first() if school else None
        if not owner:abort(404)
        if request.form.get('code','')!=school.code:abort(400,'Confirm the school Institute Code.')
        password=request.form.get('password','')
        if not password_valid(password) or not matches(password,request.form.get('confirm','')):abort(422,'Use matching passwords of 12–128 characters.')
        owner.password_hash=generate_password_hash(password);owner.version+=1
        db.session.add(Audit(actor=current().email,action='owner-password-reset',school_code=school.code));db.session.commit()
        flash('Owner password reset for '+school.code+'. Previous owner sessions are signed out.','success')
        return redirect(url_for('vendor.schools',q=school.code))

    @bp.route('/password',methods=['GET','POST'])
    @required
    def password():
        error=None
        if request.method=='POST':
            helpers['csrf']()
            if helpers['limited']('vendor-password',current().email):abort(429)
            new=request.form.get('password','');old=request.form.get('current_password','')
            if len(old)>128 or not check_password_hash(current().password_hash,old):error='Your current password is incorrect.'
            elif not password_valid(new) or not matches(new,request.form.get('confirm','')):error='Use matching passwords of 12–128 characters.'
            else:
                lock();user=current();user.password_hash=generate_password_hash(new);user.version+=1
                db.session.add(Audit(actor=user.email,action='owner-password-changed'));db.session.commit();sign_in(user)
                flash('Your software owner password was changed.','success');return redirect(url_for('vendor.schools'))
        return render_template('vendor_login.html',title='Change software owner password',mode='password',error=error),422 if error else 200

    app.register_blueprint(bp)
