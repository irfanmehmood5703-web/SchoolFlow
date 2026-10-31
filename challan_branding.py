"""Institute/campus print settings; monetary values always come from saved bills."""
import hmac,re
from collections import OrderedDict
from flask import Blueprint,abort,render_template,request,session,redirect,url_for
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import StaleDataError

DEFAULTS=dict(layout='landscape',primary='#176b4a',secondary='#e7f3ec',paper='#ffffff',ink='#243c30',
              copy_1='Student Copy',copy_2='Bank Copy',copy_3='Office Copy',
              address='',contact='',bank_name='',account_title='',account_no='',iban='',
              note='',footer='Received by: __________     Stamp & Signature: __________',
              show_logo=True,show_address=True,show_contact=True,show_father=True,show_photo=False,
              hide_zero=True,hide_status=False)
FLAGS=('show_logo','show_address','show_contact','show_father','show_photo','hide_zero','hide_status')
TEXT_LIMITS=dict(copy_1=60,copy_2=60,copy_3=60,address=500,contact=200,bank_name=160,account_title=160,account_no=100,iban=100,note=1500,footer=500)


def configure_challan_branding(app,db,Student):
    bp=Blueprint('challan_branding',__name__,url_prefix='/workspace/core/fees/challan-branding')
    Item=app.extensions['school_settings_models']['item'];rm=app.extensions['record_models'];ops=app.extensions['ops_models']
    def campuses():return sorted({r.value for r in rm['settings'].query.filter_by(category='campus').all()})
    def rows():return Item.query.filter_by(kind='challan-branding',name='Fee Challan').all()
    def saved(scope):return next((r for r in rows() if r.scope==scope),None)
    def settings(scope,all_rows=None):
        found={r.scope:r for r in (rows() if all_rows is None else all_rows)}
        row=found.get(scope) or found.get('')
        return {**DEFAULTS,**(row.data if row else {})}
    def parse():
        data={}
        for key,limit in TEXT_LIMITS.items():
            value=request.form.get(key,'').strip()
            if len(value)>limit:raise ValueError('Too long: '+key.replace('_',' ')+'.')
            data[key]=value
        labels=[data['copy_'+str(i)].casefold() for i in range(1,4) if data['copy_'+str(i)]]
        if not labels or len(labels)!=len(set(labels)):raise ValueError('Enter one to three distinct copy labels; blank labels omit that copy.')
        for key in ('primary','secondary','paper','ink'):
            value=request.form.get(key,'')
            if not re.fullmatch(r'#[0-9a-fA-F]{6}',value):raise ValueError('Choose a valid six-digit theme color.')
            data[key]=value.lower()
        data['layout']=request.form.get('layout','')
        if data['layout'] not in ('landscape','portrait'):raise ValueError('Choose A4 landscape or portrait.')
        data.update({key:request.form.get(key)=='1' for key in FLAGS})
        return data
    @bp.before_request
    def protect():
        if request.method=='POST':
            token=request.form.get('_csrf','')
            if not token or not hmac.compare_digest(token,session.get('record_csrf','')):abort(400,'Reload this form.')
            app.extensions['admission_capacity']['lock']()
    @bp.errorhandler(ValueError)
    def invalid(error):
        db.session.rollback();return render_template('operation_error.html',title='Check challan branding',error=str(error)),422
    @bp.route('',methods=['GET','POST'])
    def index():
        scope=request.values.get('campus','')
        if scope and scope not in campuses():raise ValueError('Choose a configured campus.')
        row=saved(scope)
        if request.method=='POST':
            action=request.form.get('action')
            if action not in ('save','reset','preview'):raise ValueError('Choose Save, Preview or Reset.')
            if request.form.get('version')!=str(row.version if row else 0):raise ValueError('These settings changed. Reload before saving.')
            data=parse() if action!='reset' else None
            if action=='preview':
                # Fictional preview only. Do not read or mutate a student's financial record.
                return render_template('challan_branding_preview.html',title='Challan branding preview',config=data,school=app.extensions['branding_values']['school'](scope),campus=scope)
            before=dict(row.data) if row else None
            if action=='reset':
                if row:db.session.delete(row)
            elif row:row.data=data
            else:db.session.add(Item(kind='challan-branding',scope=scope,name='Fee Challan',data=data))
            db.session.add(ops['audit'](action='Reset challan branding' if action=='reset' else 'Save challan branding',data=dict(campus=scope,before=before,after=data,owner_id=session.get('owner_id'))))
            try:db.session.commit()
            except (IntegrityError,StaleDataError):db.session.rollback();raise ValueError('Another save changed these settings. Reload before retrying.')
            return redirect(url_for('challan_branding.index',campus=scope))
        return render_template('challan_branding.html',title='Challan branding',config=settings(scope),row=row,campus=scope,campuses=campuses(),flags=FLAGS)

    def print_context(bills,action,form):
        students={s.id:s for s in Student.query.filter(Student.id.in_({b.student_id for b in bills})).all()}
        details=app.extensions['record_helpers']['raw_many']('student',list(students.values()))
        brand=app.extensions['branding_values'];all_rows=rows();photos=brand['prefetch_photos']('student',list(students.values())) if any(settings(details.get(s.id,{}).get('campus',''),all_rows)['show_photo'] for s in students.values()) else {}
        groups=OrderedDict()
        for bill in sorted(bills,key=lambda b:(b.student_id,b.month,b.id)):
            s=students[bill.student_id];d=details.get(s.id,{});campus=d.get('campus','')
            # Blank family IDs are never treated as one family; campus scopes remain separate.
            key=(campus,'family',str(d['family_no'])) if action=='family' and d.get('family_no') else (campus,'student',s.id) if action=='family' else (campus,'bill',bill.id)
            if key not in groups:
                config=settings(campus,all_rows)
                if action in ('horizontal','vertical'):config['layout']='portrait' if action=='horizontal' else 'landscape'
                if form.get('print_options_present')=='1':
                    for flag in ('hide_zero','hide_status'):config[flag]=bool(form.get(flag))
                groups[key]=dict(config=config,school=brand['school'](campus),campus=campus,entries=[],family=d.get('family_no','') if action=='family' else '',total=0)
            photo=photos.get(('student',s.id))
            groups[key]['entries'].append(dict(bill=bill,student=s,details=d,photo=url_for('records.record_file',id=photo) if photo else ''))
            groups[key]['total']+=bill.remaining
        return dict(sheets=list(groups.values()))
    app.extensions['challan_branding_helpers']=dict(settings=settings,print_context=print_context)
    app.register_blueprint(bp)
