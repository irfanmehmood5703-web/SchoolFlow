"""Personal dashboard layouts; saved preferences belong to one institute owner."""
from datetime import date
from flask import Blueprint, abort, flash, g, redirect, render_template, request, session, url_for
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import StaleDataError

# These are implemented live-data widgets, not a claim of all 37 reference tiles.
WIDGETS = [
    ('queries','Admissions','Admission Queries','queries','Saved admission enquiries.','/workspace/register/queries'),
    ('active','Admissions','Active Students','active','Students whose current status is Active.','/records/student'),
    ('classes','Admissions','Student Strength by Class',None,'Current active enrolment grouped by class.','/records/student'),
    ('capacity','Admissions','Admission Capacity',None,'Configured seat limits per campus, class and session, across sections. Only Active students occupy seats.','/workspace/admission-capacity'),
    ('collected','Finance','Total Collected','collected','All non-voided receipts, across all receipt dates.','/workspace/history'),
    ('due','Finance','Unpaid Amount','due','Current challan total less payments and discounts; not a historical balance.','/workspace/history?view=defaulters'),
    ('unpaid','Finance','Unpaid Challans','unpaid','Challans with a positive current remaining balance.','/workspace/fees/payments'),
    ('defaulters','Finance','Fee Defaulters','defaulters','Distinct students with at least one outstanding challan.','/workspace/history?view=defaulters'),
    ('months','Finance','Month-wise Fee Chart',None,'Billed amounts and receipts against that bill month, for the current year.','/workspace/reports/fees/class-fees'),
    ('average','Exam & Attendance','Results Average','average','Mean of numeric paper percentages. Absent, leave and unmarked papers are excluded.','/workspace/examination/awards'),
    ('attendance','Exam & Attendance','Student Attendance Today',None,'Saved student attendance statuses today; unmarked pupils are not counted absent.','/workspace/reports/attendance/attendance-summary'),
    ('employees','HRM','Employee Status','active_employees','Employees whose current status is Active.','/records/employee'),
    ('pending','HRM','Pending Approvals','pending','All saved workspace workflows with Pending status.','/workspace/dashboard/pending'),
    ('staff','HRM','Staff Attendance · This Month',None,'Saved staff attendance entries from the start of this month through today.','/workspace/reports/attendance/staff-attendance-report'),
]
KEYS = [w[0] for w in WIDGETS]
MONEY = {'collected','due'}


def default_layout():
    return dict(widgets=list(KEYS), mode='widgets', columns=3, compact=False, quick=True)


def configure_dashboard(app, db):
    bp = Blueprint('dashboard_layout', __name__, url_prefix='/workspace/dashboard')

    class DashboardPreference(db.Model):
        owner_key = db.Column(db.String(60), primary_key=True)
        layout = db.Column(db.JSON, nullable=False)
        version = db.Column(db.Integer, nullable=False, default=1)
        __mapper_args__ = {'version_id_col':version}

    app.extensions['dashboard_preference_model'] = DashboardPreference

    def owner_key():
        if session.get('owner_id') and not session.get('demo'):
            return 'owner:'+str(session['owner_id'])
        return None

    def saved():
        key = owner_key()
        if key:
            record = db.session.get(DashboardPreference,key)
            return (record.layout,record.version) if record else (default_layout(),0)
        return session.get('dashboard_default',default_layout()),0

    def current():
        layout,version = saved()
        return session.get('dashboard_layout',layout),version

    def validate():
        selected = request.form.getlist('widgets')
        order = request.form.getlist('order')
        if len(selected)!=len(set(selected)) or any(k not in KEYS for k in selected):
            raise ValueError('Choose valid dashboard widgets.')
        if len(order)!=len(KEYS) or set(order)!=set(KEYS):
            raise ValueError('Widget order is incomplete or invalid. Reload the dashboard.')
        if request.form.get('mode') not in ('simple','widgets') or request.form.get('columns') not in ('1','2','3'):
            raise ValueError('Choose a valid dashboard mode and column count.')
        return dict(widgets=[k for k in order if k in selected],mode=request.form['mode'],columns=int(request.form['columns']),
                    compact=request.form.get('compact')=='on',quick=request.form.get('quick')=='on')

    @bp.before_request
    def csrf():
        import hmac
        if request.method=='POST':
            token = request.form.get('_csrf','')
            if not token or not hmac.compare_digest(token,session.get('record_csrf','')):
                abort(400,'Your form session expired. Reload the dashboard.')

    def render_dashboard():
        layout,version = current()
        catalog = {w[0]:dict(key=w[0],group=w[1],label=w[2],stat=w[3],note=w[4],link=w[5],money=w[0] in MONEY) for w in WIDGETS}
        today=date.today()
        catalog['attendance']['link']+=f'?from={today}&to={today}'
        catalog['staff']['link']+=f'?from={today.replace(day=1)}&to={today}'
        selected = [catalog[k] for k in layout['widgets'] if k in catalog]
        ordered = selected+[catalog[k] for k in KEYS if k not in layout['widgets']]
        scope = (getattr(g,'school_identity',None) or {}).get('scope','demo')
        scope += ':'+str(session.get('owner_id','demo'))
        stats=app.extensions['operation_helpers']['dashboard']()
        if any(item['key']=='capacity' for item in selected):stats['capacity_rows']=app.extensions['admission_capacity']['rows']()
        return render_template('dashboard.html',title='Dashboard',stats=stats,
                               layout=layout,layout_version=version,widgets=selected,catalog=ordered,scope=scope,
                               personal=owner_key() is not None,groups=list(dict.fromkeys(w[1] for w in WIDGETS)))

    @bp.route('/pending')
    def pending():
        from module_catalog import TITLES,SCHEMAS
        model=app.extensions['ops_models']['workflow']
        rows=model.query.filter_by(status='Pending').order_by(model.id).all()
        links={kind:url_for('ops.register',kind=kind) for kind in SCHEMAS}
        links['salary-plans']=url_for('ops.plans')
        return render_template('dashboard_pending.html',title='Pending Approvals',rows=rows,titles=TITLES,links=links)

    @bp.route('/layout',methods=['POST'])
    def update():
        try:
            action = request.form.get('action')
            if action in ('simple','widgets'):
                layout,_ = current()
                session['dashboard_layout'] = dict(layout,mode=action)
            elif action=='restore':
                session.pop('dashboard_layout',None)
            elif action in ('apply','default'):
                layout = validate()
                if action=='default':
                    key = owner_key()
                    if key:
                        record = db.session.get(DashboardPreference,key)
                        expected = int(request.form.get('version','-1'))
                        if expected != (record.version if record else 0):
                            raise ValueError('Your saved default changed in another tab. Reload before saving.')
                        if record:
                            record.layout = layout
                        else:
                            db.session.add(DashboardPreference(owner_key=key,layout=layout))
                        db.session.commit()
                    else:
                        # Demo visitors cannot change each other's dashboard or
                        # add arbitrary anonymous rows to the shared database.
                        session['dashboard_default'] = layout
                session['dashboard_layout'] = layout
            else:
                raise ValueError('Choose a dashboard action.')
        except (ValueError,IntegrityError,StaleDataError) as error:
            db.session.rollback()
            return render_template('operation_error.html',title='Check dashboard settings',
                                   error=str(error) if isinstance(error,ValueError) else 'Your default changed. Reload and try again.'),422
        flash('Default dashboard saved.' if action=='default' else 'Dashboard view updated.','success')
        return redirect(url_for('ops.dashboard'))

    app.extensions['dashboard_render'] = render_dashboard
    app.register_blueprint(bp)
