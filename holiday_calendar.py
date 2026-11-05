"""Institute holiday lists consumed dynamically by late-fee schedules."""
import hashlib,hmac
from datetime import date
from flask import Blueprint,abort,flash,redirect,render_template,request,session,url_for
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import StaleDataError

NATIONAL=[('Kashmir Day','02-05'),('Pakistan Day','03-23'),('Labour Day','05-01'),('Independence Day','08-14'),('Iqbal Day','11-09'),('Quaid-e-Azam Day / Christmas','12-25')]

def configure_holiday_calendar(app,db):
    bp=Blueprint('holiday_calendar',__name__,url_prefix='/workspace/core/holidays')
    Item=app.extensions['school_settings_models']['item'];Settings=app.extensions['record_models']['settings'];Audit=app.extensions['ops_models']['audit']
    def campuses():return sorted({r.value for r in Settings.query.filter_by(category='campus').all()})
    def rows(campus=None):
        query=Item.query.filter_by(kind='calendar-holiday')
        if campus is not None:query=query.filter(Item.scope.in_(['',campus]))
        return query.order_by(Item.scope,Item.name).all()
    def entry_key(label,day):return hashlib.sha256((label+'\0'+day).encode()).hexdigest()
    app.extensions['holiday_calendar_helpers']=dict(rows=rows)
    @bp.before_request
    def protect():
        if request.method=='POST':
            if not request.form.get('_csrf') or not hmac.compare_digest(request.form['_csrf'],session.get('record_csrf','')):abort(400,'Reload the holiday form.')
            app.extensions['admission_capacity']['lock']()
    @bp.errorhandler(ValueError)
    def invalid(error):db.session.rollback();return render_template('operation_error.html',title='Check holiday calendar',error=str(error)),422
    @bp.errorhandler(IntegrityError)
    @bp.errorhandler(StaleDataError)
    def conflict(error):db.session.rollback();return render_template('operation_error.html',title='Check holiday calendar',error='This holiday changed or already exists. Reload before saving.'),422
    @bp.route('',methods=['GET','POST'])
    def index():
        row=None
        if request.method=='POST':
            action=request.form.get('action');rid=request.form.get('id','')
            if rid:
                if not rid.isdigit():abort(404)
                row=db.get_or_404(Item,int(rid))
                if row.kind!='calendar-holiday':abort(404)
            if action=='restore':
                # Explicit action only: no school calendar is assumed on GET.
                for label,day in NATIONAL:
                    key=entry_key(label,'2000-'+day)
                    if not Item.query.filter_by(kind='calendar-holiday',scope='',name=key).first():db.session.add(Item(kind='calendar-holiday',scope='',name=key,data=dict(label=label,date='2000-'+day,repeats=True,notes='',source='Restored fixed-date template')))
            elif action in ('save','delete'):
                if request.form.get('version')!=str(row.version if row else 0):raise ValueError('This holiday changed. Reload first.')
                if action=='delete':
                    if not row:raise ValueError('Choose a saved holiday.')
                    db.session.delete(row)
                else:
                    label=request.form.get('name','').strip();raw=request.form.get('date','');scope=request.form.get('campus','');notes=request.form.get('notes','').strip()
                    if not label or len(label)>160 or len(notes)>1000:raise ValueError('Enter a holiday name up to 160 characters and notes up to 1,000.')
                    try:day=date.fromisoformat(raw)
                    except ValueError:raise ValueError('Choose a valid holiday date.')
                    if day.isoformat()!=raw:raise ValueError('Use a full YYYY-MM-DD date.')
                    if scope and scope not in campuses():raise ValueError('Choose a configured campus or All campuses.')
                    data=dict(label=label,date=raw,repeats=request.form.get('repeats')=='1',notes=notes,source='School calendar',owner_id=session.get('owner_id'))
                    key=entry_key(label,raw)
                    if row:row.name=key;row.scope=scope;row.data=data
                    else:db.session.add(Item(kind='calendar-holiday',scope=scope,name=key,data=data))
            else:raise ValueError('Choose Add, Update, Delete or Restore.')
            db.session.add(Audit(action='Holiday calendar '+action,data=dict(id=rid,owner_id=session.get('owner_id'))));db.session.commit();flash('Holiday calendar saved. Enabled schedules read this calendar on their next preview/run.','success');return redirect(url_for('holiday_calendar.index'))
        if request.args.get('edit'):
            rid=request.args['edit']
            if not rid.isdigit():abort(404)
            row=db.get_or_404(Item,int(rid))
            if row.kind!='calendar-holiday':abort(404)
        scope=request.args.get('campus','');q=request.args.get('q','').strip().casefold()
        if scope and scope not in campuses():raise ValueError('Choose a configured campus filter.')
        matching=[r for r in rows() if (not scope or r.scope in ('',scope)) and (not q or q in (r.data['label']+' '+r.data.get('notes','')+' '+r.scope).casefold())]
        if request.args.get('export')=='xlsx':
            from report_exports import report_xlsx
            return report_xlsx(['Holiday','Date','Repeats','Campus','Notes'],[[r.data['label'],r.data['date'],bool(r.data['repeats']),r.scope or 'All campuses',r.data.get('notes','')] for r in matching],'holiday-calendar')
        return render_template('holiday_calendar.html',title='Holiday Calendar',rows=matching,row=row,campuses=campuses(),campus=scope,q=request.args.get('q',''))
    app.register_blueprint(bp)
