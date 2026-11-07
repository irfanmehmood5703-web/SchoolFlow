"""App release registry and the complete 37-widget reference workspace."""
import hmac
from datetime import date,datetime
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo
from flask import Blueprint,abort,flash,g,redirect,render_template,request,session,url_for
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import StaleDataError
from widget_catalog import WIDGETS,KEYS,APPS
from widget_sources import build_widgets

ROLES=('Super Admin','Admin','User','Teacher')
LEGACY={'queries':'admission-queries','active':'active-students','classes':'strength-chart','capacity':'admission-capacity','collected':'fee-collection','due':'unpaid-amount','unpaid':'unpaid-challans','defaulters':'fee-defaulters','months':'month-chart','average':'class-results','attendance':'attendance-donut','employees':'employee-status','pending':'employee-approvals','staff':'staff-attendance'}

def configure_general_tools(app,db,Student,Employee):
    bp=Blueprint('general_tools',__name__,url_prefix='/workspace/general')
    Item=app.extensions['school_settings_models']['item'];Audit=app.extensions['ops_models']['audit']
    class Preference(db.Model):
        __tablename__='widget_center_preference'
        actor=db.Column(db.String(80),primary_key=True)
        data=db.Column(db.JSON,nullable=False,default=dict)
        version=db.Column(db.Integer,nullable=False,default=1)
        __mapper_args__={'version_id_col':version}
    class Policy(db.Model):
        __tablename__='widget_center_policy'
        id=db.Column(db.Integer,primary_key=True)
        data=db.Column(db.JSON,nullable=False,default=dict)
        version=db.Column(db.Integer,nullable=False,default=1)
        __mapper_args__={'version_id_col':version}
    app.extensions['general_tools_models']=dict(preference=Preference,policy=Policy)
    def today():return datetime.now(ZoneInfo('Asia/Karachi')).date()
    def actor():
        if session.get('demo'):return None
        if session.get('staff_id'):return 'staff:'+str(session['staff_id'])
        if session.get('owner_id'):return 'owner:'+str(session['owner_id'])
        return None
    def prefs():
        key=actor();row=db.session.get(Preference,key) if key else None
        defaults=dict(selected=list(KEYS),order=list(KEYS),columns=2,mode='widgets',default=False)
        data=row.data if row else session.get('widget_center_layout',{})
        return {**defaults,**data},row
    def policy():return db.session.get(Policy,1)
    def allowed():
        p=getattr(g,'staff_principal',None)
        if p is None:return list(KEYS)
        helper=app.extensions['staff_access_helpers'];scope=set(getattr(g,'access_campuses',None) or helper['grant'](p,'widgets.view'))
        config=policy();rules=config.data.get('roles',{}) if config else {}
        role=p.data.get('role','User')
        grant_cache={permission:helper['grant'](p,permission) for permission in {r[3] for r in WIDGETS}}
        all_campuses=set(helper['campuses']())
        return [key for key,_,_,permission in WIDGETS if scope and scope<=grant_cache[permission] and (not permission.startswith('finance.') or grant_cache[permission]==all_campuses) and (key not in rules or role in rules[key])]
    def full_scope():
        p=getattr(g,'staff_principal',None)
        if p is not None and set(g.access_campuses)!=set(app.extensions['staff_access_helpers']['campuses']()):abort(403,'This setting requires access to every configured campus.')
    def releases():
        items={r.name:r for r in Item.query.filter_by(kind='app-release',scope='').all()}
        return [dict(key=key,label=label,platform=platform,url=items[key].data.get('url','') if key in items else '',version=items[key].data.get('version','') if key in items else '',size=items[key].data.get('size','') if key in items else '',notes=items[key].data.get('notes','') if key in items else '',revision=items[key].version if key in items else 0) for key,label,platform in APPS]
    def days():
        t=today();period=request.args.get('period','month')
        if period not in ('today','month','session','custom'):raise ValueError('Choose a valid period.')
        start=t if period=='today' else t.replace(day=1)
        if period=='session':
            Profile=app.extensions['institute_setup_models']['profile'];profile=db.session.get(Profile,1)
            try:start=date.fromisoformat(profile.data.get('year_start','')) if profile else t.replace(month=1,day=1)
            except ValueError:start=t.replace(month=1,day=1)
        end=t
        if period=='custom':
            try:start=date.fromisoformat(request.args.get('from',''));end=date.fromisoformat(request.args.get('to',''))
            except ValueError:raise ValueError('Choose valid From / To dates.')
        if end<start or (end-start).days>366:raise ValueError('Choose an ordered range of at most 367 days.')
        return start,end,period
    def specs(keys):
        catalog={k:dict(key=k,group=group,label=label,permission=permission,permission_label=app.extensions['staff_access_helpers']['permissions'].get(permission,permission)) for k,group,label,permission in WIDGETS}
        return [catalog[k] for k in keys if k in catalog]
    def data(keys):
        start,end,period=days();config=policy()
        result=build_widgets(app,db,Student,Employee,set(keys),start,end,today(),releases(),config.data.get('tuition_head','') if config else '')
        return result,start,end,period
    def default_url():
        current,_=prefs()
        p=getattr(g,'staff_principal',None)
        if p is not None and not app.extensions['staff_access_helpers']['grant'](p,'widgets.view'):return None
        return url_for('general_tools.widgets') if current.get('default') else None
    app.extensions['general_tools_helpers']=dict(allowed=allowed,legacy=LEGACY,releases=releases,default_url=default_url)
    @bp.context_processor
    def widget_context():
        p=getattr(g,'staff_principal',None);h=app.extensions['staff_access_helpers']
        return dict(can_manage_widgets=p is None or h['grant'](p,'widgets.manage')==set(h['campuses']()))
    @bp.before_request
    def protect():
        if request.method=='POST':
            if not request.form.get('_csrf') or not hmac.compare_digest(request.form['_csrf'],session.get('record_csrf','')):abort(400,'Reload this form before saving.')
            app.extensions['admission_capacity']['lock']()
    @bp.errorhandler(ValueError)
    def invalid(e):db.session.rollback();return render_template('operation_error.html',title='Check General options',error=str(e)),422
    @bp.errorhandler(IntegrityError)
    @bp.errorhandler(StaleDataError)
    def conflict(e):db.session.rollback();return render_template('operation_error.html',title='Reload General options',error='Another tab changed this record. Reload before saving.'),409
    @bp.route('/app-links',methods=['GET','POST'])
    def app_links():
        if request.method=='POST':
            full_scope();key=request.form.get('app','')
            if key not in dict((k,label) for k,label,_ in APPS):raise ValueError('Choose a valid app.')
            row=Item.query.filter_by(kind='app-release',scope='',name=key).first()
            if request.form.get('version_token')!=str(row.version if row else 0):raise ValueError('This release changed. Reload first.')
            values={k:request.form.get(k,'').strip() for k in ('url','version','size','notes')}
            if any(len(values[k])>limit for k,limit in [('url',1500),('version',80),('size',80),('notes',2000)]):raise ValueError('Release details are too long.')
            if values['url']:
                try:parsed=urlsplit(values['url']);port=parsed.port
                except ValueError:raise ValueError('Enter a valid HTTPS public release URL.')
                if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password or parsed.fragment or any(c.isspace() for c in values['url']):raise ValueError('Use a public HTTPS link without login credentials or a fragment.')
                if not values['version']:raise ValueError('Enter a version for a published release.')
            if row:row.data=values
            else:row=Item(kind='app-release',scope='',name=key,data=values);db.session.add(row)
            db.session.add(Audit(action='Update app release',data=dict(app=key,owner_id=session.get('owner_id'),staff_id=session.get('staff_id'))));db.session.commit();flash('Release registry saved. No app file was generated or message sent.','success');return redirect(url_for('general_tools.app_links'))
        p=getattr(g,'staff_principal',None);helper=app.extensions['staff_access_helpers']
        can_edit=p is None or helper['grant'](p,'apps.update')==set(helper['campuses']())
        return render_template('app_links.html',title='SchoolFlow App Links',apps=releases(),can_edit=can_edit)
    @bp.get('/widgets')
    def widgets():
        current,row=prefs();visible=allowed();selected=[k for k in current['order'] if k in current['selected'] and k in visible]
        if current['mode']=='simple':selected=[k for k in ('active-students','paid-amount','attendance-donut','employee-status') if k in visible]
        summaries,start,end,period=data(selected)
        return render_template('widget_center.html',title='Widgets',tab='dashboard',catalog=specs(visible),selected=specs(selected),summaries=summaries,layout=current,version=row.version if row else 0,start=start,end=end,period=period,groups=list(dict.fromkeys(item['group'] for item in specs(selected))))
    @bp.get('/widgets/library')
    def library():
        current,row=prefs();visible=allowed();ordered=[k for k in current['order'] if k in visible];catalog={r['key']:r for r in specs(visible)}
        return render_template('widget_center.html',title='Widget Library',tab='library',catalog=[catalog[k] for k in ordered],layout=current,version=row.version if row else 0,groups=list(dict.fromkeys(w[1] for w in WIDGETS)))
    @bp.post('/widgets/layout')
    def layout():
        current,row=prefs()
        if request.form.get('version')!=str(row.version if row else 0):raise ValueError('Your layout changed. Reload first.')
        action=request.form.get('action');visible=allowed()
        if action in ('simple','widgets'):current['mode']=action
        elif action=='default':current['default']=True
        elif action=='classic':current['default']=False
        elif action=='save':
            selected=request.form.getlist('selected');order=request.form.getlist('order')
            if len(set(selected))!=len(selected) or any(k not in visible for k in selected):raise ValueError('Choose widgets you are allowed to see.')
            if len(set(order))!=len(order) or set(order)!=set(visible):raise ValueError('Widget order is incomplete. Reload the library.')
            columns=request.form.get('columns','2')
            if columns not in ('1','2','3'):raise ValueError('Choose one, two or three columns.')
            current.update(selected=selected+[k for k in current['selected'] if k not in visible and k in KEYS],order=order+[k for k in KEYS if k not in visible],columns=int(columns))
        else:raise ValueError('Choose a valid layout action.')
        if actor():
            if row:row.data=current
            else:db.session.add(Preference(actor=actor(),data=current))
            db.session.commit()
        else:session['widget_center_layout']=current
        flash('Widget layout saved.','success');return redirect(url_for('general_tools.widgets'))
    @bp.route('/widgets/permissions',methods=['GET','POST'])
    def permissions():
        full_scope();config=policy()
        if request.method=='POST':
            if request.form.get('version')!=str(config.version if config else 0):raise ValueError('Permissions changed. Reload first.')
            roles={}
            for key in KEYS:
                chosen=list(dict.fromkeys(request.form.getlist(key+'_roles')))
                if any(role not in ROLES for role in chosen):raise ValueError('Choose configured role types.')
                if request.form.get(key+'_all')!='1':roles[key]=chosen
            head=request.form.get('tuition_head','')
            if head and not db.session.get(app.extensions['fee_setup_models']['head'],head):raise ValueError('Choose a configured tuition fee particular.')
            values=dict(roles=roles,tuition_head=head)
            if config:config.data=values
            else:db.session.add(Policy(id=1,data=values))
            db.session.add(Audit(action='Update widget permissions',data=dict(owner_id=session.get('owner_id'),staff_id=session.get('staff_id'))));db.session.commit();flash('Widget permissions saved. Source-module access is still required.','success');return redirect(url_for('general_tools.permissions'))
        return render_template('widget_center.html',title='Widget Permissions',tab='permissions',catalog=specs(KEYS),roles=ROLES,policy=config.data if config else {},version=config.version if config else 0,heads=app.extensions['fee_setup_models']['head'].query.order_by(app.extensions['fee_setup_models']['head'].label).all())
    @bp.get('/widgets/report/<key>')
    def report(key):
        if key not in KEYS:abort(404)
        if key not in allowed():abort(403,'This widget or its source module is not granted.')
        summaries,start,end,period=data([key]);summary=summaries[key];spec=next(s for s in specs([key]))
        if request.args.get('export')=='xlsx':
            from report_exports import report_xlsx
            return report_xlsx(summary['headers'],summary['rows'],'widget-'+key)
        try:page=max(1,int(request.args.get('page','1')))
        except ValueError:raise ValueError('Choose a valid page.')
        rows=summary['rows'];total=len(rows)
        return render_template('widget_report.html',title=spec['label'],key=key,summary=summary,rows=rows[(page-1)*50:page*50],total=total,page=page,start=start,end=end,period=period)
    app.register_blueprint(bp)
