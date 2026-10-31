"""Institute-owned setup and explicit campus/class relationships.

Catalog choices remain in RecordSettings; mappings constrain new admissions.
Unmapped legacy campuses keep their existing behavior until explicitly configured.
"""
import hmac, io
from datetime import date
from PIL import Image, UnidentifiedImageError
from flask import Blueprint, abort, flash, g, jsonify, redirect, render_template, request, send_file, session, url_for
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import StaleDataError

LINKED = ('campus','class_name','section','group_name','academic_session','fee_plan')


def configure_institute_setup(app, db):
    bp=Blueprint('institute_setup',__name__,url_prefix='/workspace/core')
    Settings=app.extensions['record_models']['settings'];Audit=app.extensions['ops_models']['audit']

    class SchoolSetup(db.Model):
        id=db.Column(db.Integer,primary_key=True)
        data=db.Column(db.JSON,nullable=False,default=dict)
        logo=db.deferred(db.Column(db.LargeBinary))
        logo_mime=db.Column(db.String(50))
        version=db.Column(db.Integer,nullable=False,default=1)
        __mapper_args__={'version_id_col':version}

    class SchoolCampus(db.Model):
        name=db.Column(db.String(160),primary_key=True)
        short_name=db.Column(db.String(50),nullable=False,default='')
        city=db.Column(db.String(160),nullable=False,default='')
        active=db.Column(db.Boolean,nullable=False,default=True)
        version=db.Column(db.Integer,nullable=False,default=1)
        __mapper_args__={'version_id_col':version}

    class SchoolClassMap(db.Model):
        campus=db.Column(db.String(160),primary_key=True)
        class_name=db.Column(db.String(160),primary_key=True)
        data=db.Column(db.JSON,nullable=False)
        active=db.Column(db.Boolean,nullable=False,default=True)
        version=db.Column(db.Integer,nullable=False,default=1)
        __mapper_args__={'version_id_col':version}

    app.extensions['institute_setup_models']=dict(profile=SchoolSetup,campus=SchoolCampus,mapping=SchoolClassMap)

    @bp.before_request
    def csrf():
        if request.method=='POST':
            token=request.form.get('_csrf','')
            if not token or not hmac.compare_digest(token,session.get('record_csrf','')):abort(400,'Reload this form before saving.')
            if request.form.get('action') in ('map','campus'):app.extensions['admission_capacity']['lock']()

    @bp.errorhandler(ValueError)
    def invalid(exc):
        db.session.rollback()
        return render_template('operation_error.html',title='Check school setup',error=str(exc)),422

    def text(key,required=False,limit=160):
        value=request.form.get(key,'').strip()
        if len(value)>limit or (required and not value):raise ValueError(f'Enter a valid {key.replace("_"," ")} (up to {limit} characters).')
        return value

    def choices():
        out={}
        for row in Settings.query.order_by(Settings.value).all():out.setdefault(row.category,[]).append(row.value)
        # Fee plan names are shared with the actual configured fee schedules.
        Workflow=app.extensions['ops_models']['workflow']
        for row in Workflow.query.filter_by(kind='fee-plans',status='Active').all():
            if row.data.get('name'):out.setdefault('fee_plan',[]).append(row.data['name'])
        return {key:sorted(set(values)) for key,values in out.items()}

    def add_catalog(category,value):
        if not Settings.query.filter_by(category=category,value=value,class_name='').first():db.session.add(Settings(category=category,value=value,class_name=''))

    def version(row):
        if request.form.get('version','0')!=str(row.version if row else 0):raise ValueError('This setup changed. Reload the page before saving.')

    def commit(action,**data):
        db.session.add(Audit(action=action,data=data))
        try:db.session.commit()
        except (IntegrityError,StaleDataError):
            db.session.rollback();raise ValueError('Another user saved this setup. Reload before retrying.')

    def payload(refresh=False):
        # Memoized only within one request, after tenant selection. Never shared.
        if not refresh and hasattr(request,'school_mapping_payload'):return request.school_mapping_payload
        campuses={row.name:row.active for row in SchoolCampus.query.all()};maps={}
        for row in SchoolClassMap.query.order_by(SchoolClassMap.class_name).all():
            maps.setdefault(row.campus,[])
            if row.active:maps[row.campus].append(dict(class_name=row.class_name,**row.data))
        request.school_mapping_payload=dict(campuses=campuses,maps=maps)
        return request.school_mapping_payload

    def validate_admission(data,old=None,fresh=False):
        # Historical selections can be retained when the student's linked cohort
        # is unchanged; new combinations must pass server-side map validation.
        if old and data.get('status')==old.get('status') and all(data.get(k,'')==old.get(k,'') for k in LINKED):return {}
        p=payload(refresh=fresh);campus=data.get('campus','');errors={}
        if p['campuses'].get(campus) is False:errors['campus']='This campus is inactive. Choose an active campus.'
        if campus not in p['maps']:return errors
        selected=next((r for r in p['maps'][campus] if r['class_name']==data.get('class_name')),None)
        if not selected:return dict(errors,class_name='Choose a class enabled for this campus in Institute Setup.')
        for key,source in [('section','sections'),('group_name','groups'),('fee_plan','fee_plans')]:
            if data.get(key) not in selected.get(source,[]):errors[key]='Choose an option linked to this campus and class in Institute Setup.'
        if data.get('academic_session')!=selected.get('academic_session'):errors['academic_session']='Choose the session assigned to this campus and class.'
        return errors

    app.extensions['institute_setup_helpers']=dict(payload=payload,validate_admission=validate_admission)

    @app.context_processor
    def context():
        # Public sign-in pages do not require or expose tenant workspace settings.
        if request.endpoint in ('home','favicon','health','static') or request.blueprint=='identity':return {}
        row=db.session.get(SchoolSetup,1)
        return dict(school_profile=row.data if row else {},school_has_logo=bool(row and row.logo_mime))

    @bp.get('/logo')
    def logo():
        row=db.get_or_404(SchoolSetup,1)
        if not row.logo:abort(404)
        response=send_file(io.BytesIO(row.logo),mimetype='image/png',max_age=0)
        response.headers['Cache-Control']='private, no-store';return response

    @bp.route('/institute',methods=['GET','POST'])
    def index():
        if request.method=='POST':
            action=request.form.get('action')
            if action=='profile':
                row=db.session.get(SchoolSetup,1);version(row)
                data=dict(row.data or {}) if row else {}
                for key in ('name','slogan','website','contact','address','owner_name','owner_designation'):
                    data[key]=text(key,required=key=='name',limit=500 if key=='address' else 160)
                if data['website'] and not data['website'].startswith(('https://','http://')):raise ValueError('Website must start with https:// or http://.')
                row=row or SchoolSetup(id=1,data={});row.data=data
                upload=request.files.get('logo')
                if upload and upload.filename:
                    content=upload.read(5*1024*1024+1)
                    if not content or len(content)>5*1024*1024:raise ValueError('Use a logo up to 5 MB.')
                    try:
                        with Image.open(io.BytesIO(content)) as image:
                            if image.format not in ('JPEG','PNG','WEBP') or image.width*image.height>16000000:raise ValueError('Use a JPG, PNG or WebP logo up to 16 megapixels.')
                            image.load();image.thumbnail((800,800));clean=image.convert('RGBA');stream=io.BytesIO();clean.save(stream,format='PNG')
                    except (UnidentifiedImageError,OSError,Image.DecompressionBombError):raise ValueError('Choose a readable JPG, PNG or WebP logo.')
                    row.logo=stream.getvalue();row.logo_mime='image/png'
                elif request.form.get('remove_logo'):row.logo=None;row.logo_mime=None
                db.session.add(row);commit('Update institute profile')
            elif action=='campus':
                name=text('campus',True);row=db.session.get(SchoolCampus,name);version(row)
                row=row or SchoolCampus(name=name)
                row.short_name=text('short_name',limit=50);row.city=text('city');row.active=request.form.get('active')=='1'
                db.session.add(row);add_catalog('campus',name);commit('Update campus',campus=name,active=row.active)
            elif action=='map':
                catalog=choices();campus=text('campus',True);cls=text('class_name',True)
                if campus not in catalog.get('campus',[]) or cls not in catalog.get('class_name',[]):raise ValueError('Configure the campus and class first.')
                row=db.session.get(SchoolClassMap,(campus,cls));version(row)
                data={}
                for source,category in [('sections','section'),('groups','group_name'),('fee_plans','fee_plan')]:
                    values=list(dict.fromkeys(request.form.getlist(source)))
                    if not values or any(v not in catalog.get(category,[]) for v in values):raise ValueError('Choose configured '+source.replace('_',' ')+'.')
                    data[source]=values
                data['academic_session']=text('academic_session',True)
                if data['academic_session'] not in catalog.get('academic_session',[]):raise ValueError('Choose a configured session.')
                for name in data['fee_plans']:add_catalog('fee_plan',name)
                row=row or SchoolClassMap(campus=campus,class_name=cls)
                row.data=data;row.active=request.form.get('active')=='1';db.session.add(row);commit('Update class map',campus=campus,class_name=cls,active=row.active)
            elif action=='academic':
                row=db.session.get(SchoolSetup,1);version(row)
                current=text('current_session',True);catalog=choices()
                if current not in catalog.get('academic_session',[]):raise ValueError('Add the session in the catalog first.')
                try:start=date.fromisoformat(text('year_start',True));end=date.fromisoformat(text('year_end',True))
                except ValueError:raise ValueError('Enter valid academic year start and end dates.')
                if end<start:raise ValueError('Academic year end cannot precede its start.')
                data=dict(row.data or {}) if row else {};data.update(current_session=current,year_start=start.isoformat(),year_end=end.isoformat())
                row=row or SchoolSetup(id=1);row.data=data;db.session.add(row);commit('Update academic year',current_session=current)
            else:raise ValueError('Choose a supported setup action.')
            flash('School setup saved. Admission choices use the saved class map.','success')
            return redirect(url_for('institute_setup.index'))
        profile=db.session.get(SchoolSetup,1);campuses=SchoolCampus.query.order_by(SchoolCampus.name).all();maps=SchoolClassMap.query.order_by(SchoolClassMap.campus,SchoolClassMap.class_name).all()
        edit_campus=db.session.get(SchoolCampus,request.args['campus_edit']) if request.args.get('campus_edit') else None
        edit_map=db.session.get(SchoolClassMap,(request.args.get('campus'),request.args.get('class_name'))) if request.args.get('edit')=='map' else None
        return render_template('institute_setup.html',title='Institute Setup',profile=profile,config=profile.data if profile else {},campuses=campuses,mappings=maps,options=choices(),edit_campus=edit_campus,edit_map=edit_map)

    @bp.get('/admission-options')
    def admission_options():return jsonify(payload())

    app.register_blueprint(bp)
