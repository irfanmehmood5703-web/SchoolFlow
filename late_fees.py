"""Explicit fixed/per-day late fee policies and reviewed, cumulative assessments."""
import copy,hashlib,hmac,json,re
import click
from datetime import date,datetime
from zoneinfo import ZoneInfo
from flask import Blueprint,abort,flash,g,redirect,render_template,request,session,url_for
from itsdangerous import BadData,URLSafeTimedSerializer
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import StaleDataError
from operations import money

MODES={'none':'No late fee','fixed':'Fixed amount once','daily':'Amount per chargeable day'}
DEFAULT=dict(mode='none',rate=0,grace=0,maximum=None,head='',head_label='')


def late_calculation(config,due,asof):
    overdue=max(0,(asof-due).days);days=overdue if overdue>config['grace'] else 0
    total=0 if not days or config['mode']=='none' else config['rate']*(days if config['mode']=='daily' else 1)
    if config['maximum'] is not None:total=min(total,config['maximum'])
    if total>99999999900:raise ValueError('Calculated fine exceeds the supported amount. Set a maximum or review the rate/date.')
    return dict(overdue=overdue,days=days,total=total)


def configure_late_fees(app,db,Student):
    bp=Blueprint('late_fees',__name__,url_prefix='/workspace/core/fees/late-policy')
    Item=app.extensions['school_settings_models']['item'];rm=app.extensions['record_models'];ops=app.extensions['ops_models'];Bill=ops['bill'];Audit=ops['audit']
    def today():return datetime.now(ZoneInfo('Asia/Karachi')).date()
    def editable():return bool((app.testing and not app.config.get('IDENTITY_ENFORCE_IN_TESTS')) or session.get('demo'))
    def policies():return Item.query.filter_by(kind='late-fee-policy').all()
    def options(kind):return sorted({r.value for r in rm['settings'].query.filter_by(category=kind).all()})
    def head_map():return {h['key']:h for h in app.extensions['fee_setup_helpers']['heads']()}
    def row_for(campus,cls):return Item.query.filter_by(kind='late-fee-policy',scope=campus,name=cls).first()
    def resolved(campus,cls,rows):
        found={(r.scope,r.name):r for r in rows}
        row=found.get((campus,'')) or found.get(('',''))
        return row,copy.deepcopy(row.data if row else DEFAULT)
    def parse():
        mode=request.form.get('mode','')
        if mode not in MODES:raise ValueError('Choose No late fee, Fixed amount or Per day. Other formulas need verification.')
        grace=request.form.get('grace','0')
        if not grace.isdigit() or not 0<=int(grace)<=3660:raise ValueError('Enter 0–3,660 grace days.')
        maximum=request.form.get('maximum','').strip();cap=money(maximum) if maximum else None
        config=dict(mode=mode,rate=0,grace=int(grace),maximum=cap,head='',head_label='')
        if mode!='none':
            rate=request.form.get('rate','').strip()
            if not rate or not money(rate):raise ValueError('Enter a positive fixed/per-day amount.')
            head=head_map().get(request.form.get('head',''))
            if not head or head['timing']!='fine':raise ValueError('Choose a fee head configured as By fine policy.')
            config.update(rate=money(rate),head=head['key'],head_label=head['label'])
        return config
    def day(raw):
        if not re.fullmatch(r'\d{4}-\d{2}-\d{2}',raw or ''):raise ValueError('Choose a valid date.')
        try:return date.fromisoformat(raw)
        except ValueError:raise ValueError('Choose a valid date.')
    def actor():return dict(scope=(getattr(g,'school_identity',None) or {}).get('scope'),institute=session.get('institute_id'),owner=session.get('owner_id'),demo=bool(session.get('demo')),csrf=hashlib.sha256(session.get('record_csrf','').encode()).hexdigest())
    def signer():return URLSafeTimedSerializer(app.config['SECRET_KEY'],salt='schoolflow-late-fee-v1')
    def commit():
        try:db.session.commit()
        except (IntegrityError,StaleDataError):db.session.rollback();raise ValueError('A policy or challan changed. Reload and preview again; no batch changes were saved.')
    @bp.before_request
    def protect():
        if request.method=='POST':
            token=request.form.get('_csrf','')
            if not token or not hmac.compare_digest(token,session.get('record_csrf','')):abort(400,'Reload this form.')
            app.extensions['admission_capacity']['lock']()
    @bp.errorhandler(ValueError)
    def invalid(error):
        db.session.rollback();return render_template('operation_error.html',title='Check late fee',error=str(error)),422
    @bp.route('',methods=['GET','POST'])
    def index():
        campus=request.values.get('campus','');cls=request.values.get('class_name','')
        if campus and campus not in options('campus'):raise ValueError('Choose a configured campus.')
        if cls:raise ValueError('Late-fee policies are managed per campus; class overrides are not used.')
        row=row_for(campus,cls)
        if request.method=='POST':
            action=request.form.get('action')
            if action not in ('save','reset','simulate'):raise ValueError('Choose Save, Reset or Simulate.')
            if action in ('save','reset') and not editable():abort(403,'Late-fee policies are provider-managed. Contact your SchoolFlow operator.')
            if request.form.get('version')!=str(row.version if row else 0):raise ValueError('These settings changed. Reload before saving.')
            config=parse() if action!='reset' else None
            if action=='simulate':
                due=day(request.form.get('due'));asof=day(request.form.get('asof'));result=late_calculation(config,due,asof)
                response=render_template('late_fee_simulator.html',title='Unsaved late-fee simulation',config=config,due=due,asof=asof,result=result,modes=MODES)
                db.session.rollback();return response
            if action=='save' and config['mode']!='none' and request.form.get('accept_formula')!='1':raise ValueError('Review and accept the displayed grace/counting formula before saving an enabled policy.')
            before=copy.deepcopy(row.data) if row else None
            if action=='reset':
                if row:db.session.delete(row)
            elif row:row.data=config
            else:db.session.add(Item(kind='late-fee-policy',scope=campus,name=cls,data=config))
            db.session.add(Audit(action='Reset late fee policy' if action=='reset' else 'Save late fee policy',data=dict(campus=campus,class_name=cls,before=before,after=config,owner_id=session.get('owner_id'))))
            commit();flash('Late-fee settings saved. No fine was charged.','success');return redirect(url_for('late_fees.index',campus=campus,class_name=cls))
        inherited,config=resolved(campus,cls,policies())
        return render_template('late_fee_policy.html',title='Late-fee policy',campus=campus,class_name=cls,row=row,inherited=inherited,config=config,campuses=options('campus'),classes=options('class_name'),heads=[h for h in head_map().values() if h['timing']=='fine'],modes=MODES,today=today().isoformat(),editable=editable())

    def selection(bills):
        if not bills or len(bills)>100:raise ValueError('Select 1–100 challans per assessment.')
        students={s.id:s for s in Student.query.filter(Student.id.in_({b.student_id for b in bills})).all()}
        return render_template('late_fee_select.html',title='Preview selected late fees',bills=bills,students=students,today=today().isoformat())
    def assessed(ids,asof):
        bills=Bill.query.filter(Bill.id.in_(ids)).order_by(Bill.id).all()
        if len(bills)!=len(ids):raise ValueError('A selected challan is missing. Select again.')
        students={s.id:s for s in Student.query.filter(Student.id.in_({b.student_id for b in bills})).all()}
        if any(b.student_id not in students for b in bills):raise ValueError('A selected challan has no student record. Review it before assessment.')
        details=app.extensions['record_helpers']['raw_many']('student',list(students.values()));settings=policies();heads=head_map();rows=[];sources=[]
        for b in bills:
            s=students[b.student_id];d=details.get(s.id,{});campus=d.get('campus','');cls=s.class_name
            existing=[x for x in b.lines if x.get('kind')=='late_fee']
            config=copy.deepcopy(existing[0]['policy']) if existing else resolved(campus,cls,settings)[1]
            row=None if existing else resolved(campus,cls,settings)[0]
            head=heads.get(config['head']);stamp=existing[0].get('policy_source',['saved-on-challan']) if existing else [row.id if row else None,row.version if row else 0,head['version'] if head else 0]
            if not existing and head:config['head_label']=head['label']
            basis_due=day(existing[0].get('basis_due',b.due.isoformat())) if existing else b.due
            calculation=late_calculation(config,basis_due,asof);previous=sum(x['amount'] for x in existing);delta=max(0,calculation['total']-previous)
            reason='Ready for explicit application' if delta else 'No additional late fee due'
            if existing and any(x.get('origin_bill_id')!=b.id for x in existing):reason='Transferred fine needs manual review';delta=0
            elif s.status!='Active':reason='Inactive student: no assessment';delta=0
            elif b.frozen:reason='Frozen challan: no assessment';delta=0
            elif b.paid or b.discount:reason='Paid/part-paid or discounted challan needs manual review';delta=0
            elif b.total-previous<=0:reason='No original fee amount remains on this challan';delta=0
            elif config['mode']=='none':reason='No enabled late-fee policy';delta=0
            elif not existing and (not head or head['timing']!='fine'):raise ValueError('The configured fine head changed. Review its policy before assessment.')
            elif any(x.get('particular')==config['head'] and x.get('kind')!='late_fee' for x in b.lines):reason='An untracked amount already uses this fine head; manual review required';delta=0
            digest=hashlib.sha256(json.dumps(b.lines,sort_keys=True,separators=(',',':')).encode()).hexdigest()
            sources.append([b.id,b.version,b.due.isoformat(),b.paid,b.discount,b.frozen,digest,s.id,s.status,s.name,campus,cls,stamp,config])
            policy_scope=copy.deepcopy(existing[0].get('assessment_scope',{})) if existing else dict(campus=campus,class_name=cls,policy_campus=row.scope if row else '',policy_class=row.name if row else '')
            rows.append(dict(bill=b,student=s,campus=campus,class_name=cls,policy_scope=policy_scope,config=config,basis_due=basis_due,stamp=stamp,calculation=calculation,existing=previous,delta=delta,reason=reason,saved_policy=bool(existing)))
        return rows,sources
    @bp.route('/assess',methods=['GET','POST'])
    def assess():
        if request.method=='GET':return redirect(url_for('ops.fees',mode='payments'))
        action=request.form.get('action')
        if action=='preview':
            raw=request.form.getlist('ids')
            if not raw or len(raw)>100 or any(not re.fullmatch(r'[1-9]\d*',x) for x in raw):raise ValueError('Select 1–100 valid challans.')
            ids=sorted({int(x) for x in raw});asof=day(request.form.get('asof'));rows,sources=assessed(ids,asof)
            token=signer().dumps(dict(v=1,actor=actor(),ids=ids,asof=asof.isoformat(),sources=sources))
            response=render_template('late_fee_preview.html',title='Review late-fee assessment',rows=rows,asof=asof,token=token,total=sum(r['delta'] for r in rows),future=asof>today(),modes=MODES)
            db.session.rollback();return response
        if action!='apply':raise ValueError('Preview the selected challans before applying a fine.')
        token=request.form.get('preview_token','')
        if len(token)>131072:raise ValueError('Invalid preview. Preview again.')
        try:payload=signer().loads(token,max_age=900)
        except BadData:raise ValueError('This preview expired or changed. Preview again.')
        if not isinstance(payload,dict) or payload.get('v')!=1 or payload.get('actor')!=actor():raise ValueError('This preview belongs to another institute or sign-in session.')
        asof=day(payload['asof'])
        if asof>today():raise ValueError('Future dates are simulation only. Choose today or an earlier assessment date.')
        rows,sources=assessed(payload['ids'],asof)
        if sources!=payload['sources']:raise ValueError('A selected challan, student or policy changed. Preview again; no fines were saved.')
        changed=[]
        for row in rows:
            if not row['delta']:continue
            b=row['bill'];line=dict(particular=row['config']['head'],display_name=row['config']['head_label'],amount=row['delta'],kind='late_fee',origin_bill_id=b.id,basis_due=row['basis_due'].isoformat(),policy_source=row['stamp'],assessment_scope=row['policy_scope'],assessed_through=asof.isoformat(),policy=copy.deepcopy(row['config']),cumulative_target=row['calculation']['total'])
            before=copy.deepcopy(b.lines);b.lines=[*b.lines,line]
            changed.append(dict(bill_id=b.id,before=before,added=line))
        if changed:db.session.add(Audit(action='Apply reviewed late fees',data=dict(asof=asof.isoformat(),owner_id=session.get('owner_id'),changes=changed)))
        commit();flash(f'{len(changed)} challans assessed; no duplicate fine was added.','success');return redirect(url_for('ops.fees',mode='payments'))
    @app.cli.command('institute-late-policy')
    @click.option('--code',required=True)
    @click.option('--campus',default='')
    @click.option('--show',is_flag=True)
    @click.option('--reset',is_flag=True)
    @click.option('--expected-version',type=int)
    @click.option('--mode',type=click.Choice(list(MODES)))
    @click.option('--rate',default='')
    @click.option('--grace',default='0')
    @click.option('--maximum',default='')
    @click.option('--head',default='')
    @click.option('--accept-formula',is_flag=True)
    def operator_policy(code,campus,show,reset,expected_version,mode,rate,grace,maximum,head,accept_formula):
        """Private provider operation; --show first, then use its version for updates."""
        School=app.extensions['identity_models']['institute']
        school=School.query.filter_by(code=code.strip().upper(),active=True).first()
        if not school:raise click.ClickException('Active institute not found.')
        engine=app.extensions['identity_helpers']['engine'](school.id)
        data=dict(mode=mode or '',rate=rate,grace=grace,maximum=maximum,head=head)
        with app.test_request_context('/operator/late-policy',method='POST',data=data):
            g.institute_engine=engine;db.session.remove()
            try:
                if campus and campus not in options('campus'):raise ValueError('Choose a configured campus.')
                row=row_for(campus,'')
                if show:
                    click.echo(json.dumps(dict(campus=campus,version=row.version if row else 0,policy=(row.data if row else None)),ensure_ascii=True));return
                app.extensions['admission_capacity']['lock']()
                # Re-read under the gate after the operator's --show/version check.
                db.session.expire_all();row=row_for(campus,'')
                if expected_version is None or expected_version!=(row.version if row else 0):raise ValueError('Use --show, then supply the current --expected-version.')
                config=None if reset else parse()
                if config and config['mode']!='none' and not accept_formula:raise ValueError('Use --accept-formula after reviewing the grace/counting formula.')
                before=copy.deepcopy(row.data) if row else None
                if reset:
                    if row:db.session.delete(row)
                elif row:row.data=config
                else:db.session.add(Item(kind='late-fee-policy',scope=campus,name='',data=config))
                db.session.add(Audit(action='Provider reset late fee policy' if reset else 'Provider save late fee policy',data=dict(campus=campus,before=before,after=config,actor='provider-cli')))
                commit();click.echo('Late-fee policy saved for this institute only. No challan was charged.')
            except ValueError as error:
                db.session.rollback();raise click.ClickException(str(error))
            finally:
                db.session.remove();g.pop('institute_engine',None)

    app.extensions['late_fee_helpers']=dict(selection=selection,head_used=lambda key:any(r.data.get('head')==key for r in policies()))
    app.register_blueprint(bp)
