"""Explicit campus/class/year increment policies, applied through reviewed plans."""
import hmac
from datetime import datetime
from zoneinfo import ZoneInfo
from flask import Blueprint,abort,flash,redirect,render_template,request,session,url_for
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import StaleDataError
from student_fee_plans import fee_percentage

def configure_yearly_fees(app,db):
    bp=Blueprint('yearly_fees',__name__,url_prefix='/workspace/core/fees/yearly-increment')
    models=app.extensions['school_settings_models'];Item=models['item'];Config=models['setting'];Settings=app.extensions['record_models']['settings'];Audit=app.extensions['ops_models']['audit'];Map=app.extensions['institute_setup_models']['mapping']
    def options(category):return sorted({r.value for r in Settings.query.filter_by(category=category).all()})
    def classes(campus):
        linked=Map.query.filter_by(campus=campus).all()
        return sorted({r.class_name for r in linked if r.active}) if linked else options('class_name')
    def year(raw):
        if not raw.isascii() or not raw.isdigit() or len(raw)!=4 or not 1900<=int(raw)<=9999:raise ValueError('Choose a year from 1900 to 9999.')
        return int(raw)
    @bp.before_request
    def protect():
        if request.method=='POST':
            if not request.form.get('_csrf') or not hmac.compare_digest(request.form['_csrf'],session.get('record_csrf','')):abort(400,'Reload this form.')
            app.extensions['admission_capacity']['lock']()
    @bp.errorhandler(ValueError)
    def invalid(error):db.session.rollback();return render_template('operation_error.html',title='Check yearly increment',error=str(error)),422
    @bp.errorhandler(IntegrityError)
    @bp.errorhandler(StaleDataError)
    def conflict(error):db.session.rollback();return render_template('operation_error.html',title='Check yearly increment',error='This entry changed or already exists. Reload before saving.'),422
    @bp.route('',methods=['GET','POST'])
    def index():
        cfg=db.session.get(Config,'yearly-fee-years');years=cfg.data.get('years',[]) if cfg else []
        if request.method=='POST':
            action=request.form.get('action')
            if action=='add-year':
                if request.form.get('version')!=str(cfg.version if cfg else 0):raise ValueError('The year list changed. Reload first.')
                y=year(request.form.get('year',''))
                if y in years:raise ValueError('That year is already configured.')
                if len(years)>=100:raise ValueError('At most 100 configured years are supported.')
                data=dict(years=sorted(years+[y]))
                if cfg:cfg.data=data
                else:db.session.add(Config(key='yearly-fee-years',data=data))
            elif action=='add-plan':
                campus=request.form.get('campus','');cls=request.form.get('cohort_class','')
                if campus not in options('campus') or cls not in classes(campus):raise ValueError('Choose a configured campus and a class offered there.')
                db.session.add(Item(kind='yearly-fee-cohort',scope=campus,name=cls,data={'years':{}}))
            elif action=='save':
                rid=request.form.get('id','')
                if not rid.isdigit():abort(404)
                row=db.get_or_404(Item,int(rid))
                if row.kind!='yearly-fee-cohort':abort(404)
                if request.form.get('version')!=str(row.version):raise ValueError('This yearly plan changed. Reload before saving.')
                y=year(request.form.get('year',''))
                if y not in years:raise ValueError('Add that year first.')
                raw=request.form.get('percentage','').strip();data=dict(row.data.get('years',{}))
                if raw=='':data.pop(str(y),None)
                else:data[str(y)]=str(fee_percentage(raw))
                row.data={'years':data}
            else:raise ValueError('Choose Add year, Add fee plan or Save changes.')
            db.session.add(Audit(action='Configure yearly fee '+action,data=dict(owner_id=session.get('owner_id'))));db.session.commit();flash('Yearly settings saved. No student fee or challan was changed. Review selected student plans to apply a rate.','success');return redirect(url_for('yearly_fees.index'))
        current=datetime.now(ZoneInfo('Asia/Karachi')).year
        default_end=max(years) if years else current;default_start=max(min(years),default_end-20) if years else current
        start=year(request.args.get('from_year',str(default_start)));end=year(request.args.get('to_year',str(default_end)))
        if end<start or end-start>20:raise ValueError('Choose an ordered range spanning at most 21 years.')
        campus=request.args.get('campus','');cls=request.args.get('class_name','')
        if campus and campus not in options('campus'):raise ValueError('Choose a configured campus.')
        query=Item.query.filter_by(kind='yearly-fee-cohort')
        if campus:query=query.filter_by(scope=campus)
        if cls:query=query.filter_by(name=cls)
        rows=query.order_by(Item.scope,Item.name).all()
        return render_template('yearly_fees.html',title='Student Yearly Fee Increment',cfg=cfg,years=[y for y in years if start<=y<=end],all_years=years,start=start,end=end,rows=rows,campus=campus,class_name=cls,campuses=options('campus'),classes=classes(campus) if campus else [])
    @bp.route('/add',methods=['GET','POST'])
    def add_plan():
        if request.method=='POST':
            if request.form.get('action')!='add-plan':raise ValueError('Choose Add fee plan.')
            return index()
        campus=request.args.get('campus','');names=options('campus')
        if campus and campus not in names:raise ValueError('Choose a configured campus.')
        offerings={name:classes(name) for name in names}
        return render_template('yearly_fee_add.html',title='Add Yearly Fee Plan',campuses=names,campus=campus,offerings=offerings)
    app.register_blueprint(bp)
