"""Institute authentication and per-institute SQLAlchemy database routing.

The control database holds identities only. Workspace queries use a separate
database namespace for each institute (SQLite locally; PostgreSQL schemas when configured). No public registration or shared demo credentials.
"""
import hashlib
import hmac
import json
import os
import re
import secrets
import time
from datetime import timedelta
from pathlib import Path

import click
from flask import (Blueprint, abort, g, has_request_context, jsonify, redirect,
                   render_template, request, session, url_for)
from flask_sqlalchemy.session import Session
from sqlalchemy import create_engine, event, case, delete, inspect, text
from sqlalchemy.schema import CreateSchema
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from werkzeug.security import check_password_hash, generate_password_hash


class InstituteSession(Session):
    def get_bind(self, mapper=None, clause=None, bind=None, **kwargs):
        # Identity tables always use the control engine, including during a
        # workspace request. All other ORM / Core work uses that request's DB.
        table = getattr(mapper, 'local_table', None)
        if table is not None and table.info.get('identity_control'):
            return super().get_bind(mapper=mapper, clause=clause, bind=bind, **kwargs)
        if has_request_context() and getattr(g, 'institute_engine', None) is not None:
            return g.institute_engine
        return super().get_bind(mapper=mapper, clause=clause, bind=bind, **kwargs)


def configure_identity(app, db):
    bp = Blueprint('identity', __name__, url_prefix='/auth')
    control = {'info': {'identity_control': True}}
    bind_key='identity' if 'identity' in app.config.get('SQLALCHEMY_BINDS',{}) else None
    app.extensions['identity_bind_key']=bind_key

    class Institute(db.Model):
        __bind_key__ = bind_key
        __tablename__ = 'identity_institute'
        __table_args__ = control
        id = db.Column(db.Integer, primary_key=True)
        code = db.Column(db.String(40), unique=True, nullable=False)
        name = db.Column(db.String(160), nullable=False)
        storage_key = db.Column(db.String(32), nullable=False, unique=True, default=lambda: secrets.token_hex(16))
        active = db.Column(db.Boolean, nullable=False, default=True)

    class Owner(db.Model):
        __bind_key__ = bind_key
        __tablename__ = 'identity_owner'
        __table_args__ = (db.UniqueConstraint('institute_id', 'email'), control)
        id = db.Column(db.Integer, primary_key=True)
        institute_id = db.Column(db.Integer, db.ForeignKey('identity_institute.id'), nullable=False)
        email = db.Column(db.String(254), nullable=False)
        password_hash = db.Column(db.String(300), nullable=False)
        active = db.Column(db.Boolean, nullable=False, default=True)
        version = db.Column(db.Integer, nullable=False, default=1)

    class Attempt(db.Model):
        __bind_key__ = bind_key
        __tablename__ = 'identity_attempt'
        __table_args__ = control
        key = db.Column(db.String(64), primary_key=True)
        count = db.Column(db.Integer, nullable=False, default=0)
        started = db.Column(db.Float, nullable=False)

    engines = {}
    dummy_hash = generate_password_hash(secrets.token_urlsafe(32))
    app.extensions['identity_models'] = dict(institute=Institute, owner=Owner, attempt=Attempt)
    app.config.setdefault('IDENTITY_ENFORCE_IN_TESTS', False)
    app.config.update(PERMANENT_SESSION_LIFETIME=timedelta(hours=8), SESSION_REFRESH_EACH_REQUEST=False)

    def control_engine():
        return db.engines[bind_key]

    def check_cutover():
        if not bind_key or not inspect(db.engine).has_table('identity_institute'):return
        with db.engine.connect() as connection:
            if connection.execute(text('SELECT count(*) FROM identity_institute')).scalar():
                raise RuntimeError('Existing private accounts require a verified backup and migration before changing identity storage.')

    def tenant_engine(institute_id):
        school = db.session.get(Institute, int(institute_id))
        if school is None or not re.fullmatch(r'[0-9a-f]{32}', school.storage_key):
            raise RuntimeError('Institute storage identity is unavailable.')
        identity_engine=control_engine()
        if identity_engine.dialect.name=='postgresql':
            schema='school_'+school.storage_key
            key=(id(identity_engine),schema)
            if key not in engines:
                engines[key]=identity_engine.execution_options(schema_translate_map={None:schema})
            return engines[key]
        root = Path(app.config.get('INSTITUTE_DATABASE_DIR') or Path(app.instance_path) / 'institutes').resolve()
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        # Random immutable names prevent reconnecting an old file if control
        # rows are restored/reset and numeric IDs are reused.
        filename = root / f'institute-{school.storage_key}.db'
        key = str(filename)
        if key not in engines:
            engine = create_engine('sqlite:///' + str(filename), connect_args={'timeout': 20})
            @event.listens_for(engine, 'connect')
            def foreign_keys(connection, record):
                connection.execute('PRAGMA foreign_keys=ON')
            engines[key] = engine
        return engines[key]

    def provision(code, name, email, password):
        code = code.strip().upper()
        email = email.strip().casefold()
        if not re.fullmatch(r'[A-Z0-9][A-Z0-9-]{2,39}', code) or code == 'DEMO':
            raise ValueError('Use an institute code of 3–40 letters, numbers or hyphens; DEMO is reserved.')
        if not name.strip() or len(name.strip()) > 160 or not valid_email(email):
            raise ValueError('Enter a school name and valid owner email.')
        if not 12 <= len(password) <= 128:
            raise ValueError('Use a password of 12–128 characters.')
        if Institute.query.filter_by(code=code).first():
            raise ValueError('This institute code is already registered.')
        institute = Institute(code=code, name=name.strip())
        db.session.add(institute)
        db.session.flush()
        engine = tenant_engine(institute.id)
        # create_all runs only at explicit provisioning / schema upgrade time,
        # never while a visitor chooses an arbitrary institute code.
        # PostgreSQL can atomically create the private schema, profile and
        # identity in one transaction. Do not leave orphan schemas on failure.
        connection=db.session.connection(bind_arguments={'mapper':Institute}) if engine.dialect.name=='postgresql' else None
        create_workspace(engine,connection)
        Profile=app.extensions.get('institute_setup_models',{}).get('profile')
        if Profile is not None:
            values=dict(id=1,data=dict(name=name.strip(),owner_email=email,ui_mode='light',ui_mode_revision=0))
            if connection is not None:
                schema=engine.get_execution_options()['schema_translate_map']
                try:connection.execution_options(schema_translate_map=schema).execute(Profile.__table__.insert().values(**values))
                finally:connection.execution_options(schema_translate_map=None)
            else:
                with engine.begin() as tenant_connection:tenant_connection.execute(Profile.__table__.insert().values(**values))
        db.session.add(Owner(institute_id=institute.id, email=email, password_hash=generate_password_hash(password)))
        db.session.commit()
        return institute

    def create_workspace(engine,connection=None):
        schema_map=engine.get_execution_options().get('schema_translate_map')
        def create(conn):
            if engine.dialect.name=='postgresql':conn.execute(CreateSchema(schema_map[None],if_not_exists=True))
            db.metadata.create_all(conn,tables=workspace_tables())
        if connection is not None:
            try:create(connection.execution_options(schema_translate_map=schema_map))
            finally:connection.execution_options(schema_translate_map=None)
        else:
            with engine.begin() as conn:create(conn)

    def workspace_tables():
        return [t for t in db.metadata.sorted_tables if not t.info.get('identity_control')]

    def valid_email(value):
        return len(value) <= 254 and bool(re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', value))

    def csrf():
        token = request.form.get('_csrf', '')
        if not token or not hmac.compare_digest(token, session.get('record_csrf', '')):
            abort(400, 'Your form session expired. Reload the page.')

    def limited(scope, identity=''):
        # Do not trust visitor-supplied X-Forwarded-For. Persist failures across
        # workers, and key both a peer and a named account independently.
        keys = [(f'{scope}:peer:{request.remote_addr or "unknown"}', 100)]
        if identity:
            keys.append((f'{scope}:account:{identity}', 10))
        now = time.time()
        blocked = False
        insert = postgres_insert if control_engine().dialect.name == 'postgresql' else sqlite_insert
        # Atomic upserts avoid lost increments / first-attempt insertion races
        # between gunicorn workers. Expired throttle keys are not retained.
        db.session.execute(delete(Attempt).where(Attempt.started < now - 86400))
        for raw, limit in keys:
            key = hashlib.sha256(raw.encode()).hexdigest()
            statement = insert(Attempt).values(key=key, count=1, started=now)
            statement = statement.on_conflict_do_update(index_elements=['key'], set_={
                'count': case((Attempt.started <= now-900, 1), else_=Attempt.count+1),
                'started': case((Attempt.started <= now-900, now), else_=Attempt.started),
            }).returning(Attempt.count)
            blocked = db.session.execute(statement).scalar_one() > limit or blocked
        db.session.commit()
        return blocked

    @app.before_request
    def require_institute():
        g.school_identity = None
        g.institute_engine = None
        g.staff_principal = None
        g.access_campuses = None
        g.attendance_device_actor = None
        if app.testing and not app.config['IDENTITY_ENFORCE_IN_TESTS']:
            return
        # Never carry ORM identity-map entries across school selections, even
        # when a hosting/test harness holds an application context open.
        db.session.remove()
        if request.url_rule is None:
            return
        if request.endpoint in ('home', 'favicon', 'health', 'static','attendance_devices.heartbeat','attendance_devices.ingest','attendance_devices.identity_card','sms_gateway.heartbeat','sms_gateway.claim','sms_gateway.start','sms_gateway.result','school_apps.claim','school_apps.signing','school_apps.complete','school_apps.fail','school_apps.public_download') or request.blueprint in ('identity','parent_portal','mobile_clients','vendor'):
            return
        if session.get('demo') and app.config.get('PUBLIC_DEMO_ENABLED', True):
            # Demo always uses the original fictional-data database, never a
            # real institute ID supplied by a visitor.
            g.school_identity = dict(name='SchoolFlow Demo', code='DEMO', demo=True)
            return
        if session.get('staff_id'):
            school=db.session.get(Institute,session.get('institute_id'))
            if school and school.active and time.time()-session.get('signed_in_at',0)<=8*3600:
                g.institute_engine=tenant_engine(school.id);db.session.remove()
                helper=app.extensions.get('staff_access_helpers',{})
                staff=helper.get('resolve',lambda *args:None)(session['staff_id'],session.get('staff_version'))
                if staff:
                    g.staff_principal=staff
                    g.school_identity=dict(name=school.name,code=school.code,scope=school.storage_key,demo=False,email=staff.email or staff.username)
                    return
            session.clear()
            if request.path.startswith('/api/'):return jsonify(error='Institute sign-in required'),401
            return redirect(url_for('identity.institute'))
        owner = db.session.get(Owner, session.get('owner_id')) if session.get('owner_id') else None
        school = db.session.get(Institute, owner.institute_id) if owner else None
        if (not owner or not owner.active or not school or not school.active
                or session.get('owner_version') != owner.version
                or time.time() - session.get('signed_in_at', 0) > 8 * 3600
                or session.get('institute_id') != school.id):
            session.clear()
            if request.path.startswith('/api/'):
                return jsonify(error='Institute sign-in required'), 401
            return redirect(url_for('identity.institute'))
        engine=tenant_engine(school.id)
        identity=dict(name=school.name,code=school.code,scope=school.storage_key,demo=False,email=owner.email)
        db.session.remove()
        g.institute_engine=engine
        g.school_identity=identity

    @app.context_processor
    def identity_context():
        return dict(school_identity=getattr(g, 'school_identity', None))

    @bp.route('/institute', methods=['GET', 'POST'])
    def institute():
        error = None
        if request.method == 'POST':
            csrf()
            if limited('institute'):
                return render_template('identity.html', step='institute', error='Too many attempts. Try again in 15 minutes.'), 429
            code = request.form.get('code', '').strip().upper()[:40]
            school = Institute.query.filter_by(code=code, active=True).first()
            session.clear()
            session['record_csrf'] = secrets.token_urlsafe(32)
            if school:
                session['pending_institute'] = school.id
                session['pending_at'] = time.time()
                return redirect(url_for('identity.login'))
            error = 'Institute code not recognised. Check the code supplied by your school.'
        return render_template('identity.html', step='institute', error=error)

    def pending_school():
        if time.time() - session.get('pending_at', 0) > 900:
            return None
        school = db.session.get(Institute, session.get('pending_institute')) if session.get('pending_institute') else None
        return school if school and school.active else None

    @bp.route('/login', methods=['GET', 'POST'])
    def login():
        school = pending_school()
        if not school:
            return redirect(url_for('identity.institute'))
        error = None
        if request.method == 'POST':
            csrf()
            email = request.form.get('email', '').strip().casefold()[:254]
            if limited('login', f'{school.id}:{email}'):
                return render_template('identity.html', step='login', school=school, error='Too many attempts. Try again in 15 minutes.'), 429
            owner = Owner.query.filter_by(institute_id=school.id, email=email, active=True).first()
            password = request.form.get('password', '')
            valid = check_password_hash(owner.password_hash if owner else dummy_hash, password[:129])
            if owner and valid and len(password) <= 128:
                session.clear()
                session.permanent = True
                session.update(owner_id=owner.id, owner_version=owner.version, institute_id=school.id,
                               signed_in_at=time.time(), record_csrf=secrets.token_urlsafe(32))
                return redirect(url_for('ops.dashboard'))
            helper=app.extensions.get('staff_access_helpers',{})
            staff=helper.get('authenticate',lambda *args:None)(school,email,password)
            if staff:
                session.clear();session.permanent=True
                session.update(staff_id=staff['id'],staff_version=staff['version'],institute_id=school.id,signed_in_at=time.time(),record_csrf=secrets.token_urlsafe(32))
                return redirect(url_for('ops.dashboard'))
            error = 'Email or password is incorrect.'
        return render_template('identity.html', step='login', school=school, error=error)

    @bp.route('/forgot-password')
    def forgot_password():
        return render_template('identity.html', step='forgot', school=pending_school())

    @bp.route('/demo', methods=['POST'])
    def demo():
        csrf()
        if not app.config.get('PUBLIC_DEMO_ENABLED', True):
            abort(404)
        session.clear()
        session.update(demo=True, record_csrf=secrets.token_urlsafe(32))
        return redirect(url_for('ops.dashboard'))

    @bp.route('/logout', methods=['POST'])
    def logout():
        csrf()
        session.clear()
        return redirect(url_for('home'))

    @app.cli.command('institute-create')
    @click.option('--code', prompt='Institute code')
    @click.option('--name', prompt='School name')
    @click.option('--email', prompt='Owner email')
    @click.password_option(confirmation_prompt=True)
    def institute_create(code, name, email, password):
        """Provision a separate school DB and its first owner (operator only)."""
        try:
            school = provision(code, name, email, password)
        except ValueError as error:
            db.session.rollback()
            raise click.ClickException(str(error))
        click.echo(f'Institute {school.code} created. Owner can now sign in. No pupil records were copied.')

    @app.cli.command('institute-create-generated')
    @click.option('--code',required=True,help='Client institute code, e.g. CLIENT-001.')
    @click.option('--name',required=True,help='The client school name, not the SchoolFlow product name.')
    @click.option('--login',default=None,help='Optional owner login email. This does not create a mailbox.')
    @click.option('--credentials-file',required=True,type=click.Path(dir_okay=False,path_type=Path),help='New private file for one-time handover. Never commit this file.')
    def institute_create_generated(code,name,login,credentials_file):
        """Vendor provisions a client with a generated login and random password."""
        code=code.strip().upper()
        if not re.fullmatch(r'[A-Z0-9][A-Z0-9-]{2,39}',code) or code=='DEMO':
            raise click.ClickException('Choose a valid non-DEMO institute code.')
        email=(login or f'owner@{code.lower()}.schoolflow.invalid').strip().casefold()
        password=secrets.token_urlsafe(24)
        if credentials_file.resolve().is_relative_to(Path(app.root_path).resolve()):
            raise click.ClickException('Save private credentials outside the application checkout.')
        # Exclusive creation also rejects symlinks and accidental overwrites.
        try:
            descriptor=os.open(credentials_file,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        except OSError:
            raise click.ClickException('Choose a new writable private credentials file.')
        try:
            with os.fdopen(descriptor,'w',encoding='utf-8') as output:
                json.dump(dict(product='SchoolFlow',school_name=name.strip(),institute_code=code,
                               login=email,password=password,mailbox_created=False),output,indent=2)
                output.flush();os.fsync(output.fileno())
            school=provision(code,name,email,password)
        except Exception as error:
            db.session.rollback()
            credentials_file.unlink(missing_ok=True)
            if isinstance(error,ValueError):raise click.ClickException(str(error))
            raise
        click.echo(f'Client {school.code} created. Private handover file saved. No password was printed.')
        click.echo('Generated email-style logins are identifiers only; no mailbox or email delivery was created.')

    @app.cli.command('institute-reset-password')
    @click.option('--code', prompt='Institute code')
    @click.option('--email', prompt='Owner email')
    @click.password_option(confirmation_prompt=True)
    def reset_password(code, email, password):
        """Operator recovery; invalidate all existing owner sessions."""
        school = Institute.query.filter_by(code=code.strip().upper()).first()
        owner = Owner.query.filter_by(institute_id=school.id, email=email.strip().casefold()).first() if school else None
        if not owner or not 12 <= len(password) <= 128:
            raise click.ClickException('Owner not found or password is outside 12–128 characters.')
        owner.password_hash = generate_password_hash(password)
        owner.version += 1
        db.session.commit()
        click.echo('Password updated. Previous sessions have been invalidated.')

    def upgrade_missing_tables():
        ids=[s.id for s in Institute.query.all()]
        db.session.remove()
        for sid in ids:
            engine=tenant_engine(sid);db.session.remove();create_workspace(engine)
        db.session.remove()

    @app.cli.command('institute-upgrade')
    def upgrade_institutes():
        """Create missing tables in all institute databases; no destructive DDL."""
        upgrade_missing_tables()
        click.echo('Missing institute tables created. Existing columns require a versioned migration.')

    app.extensions['identity_helpers'] = dict(provision=provision, engine=tenant_engine, control_engine=control_engine, check_cutover=check_cutover, csrf=csrf, limited=limited, valid_email=valid_email, workspace_tables=workspace_tables,create_workspace=create_workspace,upgrade_missing_tables=upgrade_missing_tables)
    app.register_blueprint(bp)
