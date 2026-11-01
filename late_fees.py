"""Explicit fixed/per-day late fee policies and reviewed, cumulative assessments."""
import copy,hashlib,hmac,json,re
import click
from datetime import date,datetime
from zoneinfo import ZoneInfo
from decimal import Decimal,ROUND_HALF_UP
from flask import Blueprint,abort,flash,g,redirect,render_template,request,session,url_for
from itsdangerous import BadData,URLSafeTimedSerializer
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import StaleDataError
from operations import money

MODES={'none':'No late fee','fixed':'Fixed amount once','fixed_double':'Fixed, double after expiry','daily':'Amount per chargeable day','daily_double':'Per day, double after expiry','percent_actual':'Percentage of actual tuition','percent_decided':'Percentage of decided tuition','percent_owing':'Percentage of remaining original challan','revoke_discount':'Reverse tuition concession'}
PERCENT_MODES=('percent_actual','percent_decided','percent_owing')
TUITION_MODES=('percent_actual','percent_decided','revoke_discount')
DEFAULT=dict(mode='none',rate=0,grace=0,maximum=None,head='',head_label='')


def late_calculation(config,due,asof,basis=None):
    overdue=max(0,(asof-due).days);days=overdue if overdue>config['grace'] else 0
    mode=config['mode'];total=0;basis=basis or {}
    if days and mode!='none':
        if mode=='fixed':total=config['rate']
        elif mode=='daily':total=config['rate']*days
        elif mode=='fixed_double':total=config['rate']*(2 if overdue>config['expiry'] else 1)
        elif mode=='daily_double':total=config['rate']*(min(days,config['expiry'])+2*max(0,days-config['expiry']))
        elif mode in PERCENT_MODES:
            key={'percent_actual':'actual','percent_decided':'decided','percent_owing':'owing'}[mode]
            if key not in basis:raise ValueError('This formula requires a saved '+key+' fee basis.')
            total=int((Decimal(basis[key])*config['rate']/10000).quantize(Decimal('1'),rounding=ROUND_HALF_UP))
        elif mode=='revoke_discount':
            if not all(k in basis for k in ('actual','decided')):raise ValueError('Discount reversal requires saved actual and decided tuition.')
            total=max(0,basis['actual']-basis['decided'])
        else:raise ValueError('Unsupported late-fee formula.')
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
        if mode not in MODES:raise ValueError('Choose a supported late-fee method.')
        grace=request.form.get('grace','0')
        if not grace.isdigit() or not 0<=int(grace)<=3660:raise ValueError('Enter 0–3,660 grace days.')
        maximum=request.form.get('maximum','').strip();cap=money(maximum) if maximum else None
        config=dict(mode=mode,rate=0,grace=int(grace),maximum=cap,head='',head_label='',next_challan=request.form.get('next_challan')=='1')
        if mode in ('fixed_double','daily_double'):
            expiry=request.form.get('expiry','')
            if not expiry.isdigit() or not 1<=int(expiry)<=3660:raise ValueError('Enter an expiry of 1–3,660 days after the due date.')
            config['expiry']=int(expiry)
        if mode!='none':
            rate=request.form.get('rate','').strip()
            if mode=='revoke_discount':rate='0'
            elif not rate or not money(rate):raise ValueError('Enter a positive amount or percentage.')
            if mode in PERCENT_MODES and money(rate)>10000:raise ValueError('The percentage must be at most 100.')
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
                due=day(request.form.get('due'));asof=day(request.form.get('asof'));basis={k:money(request.form.get('basis_'+k,'0')) for k in ('actual','decided','owing')}
                if basis['decided']>basis['actual']:raise ValueError('Decided tuition cannot exceed actual tuition in the simulator.')
                result=late_calculation(config,due,asof,basis)
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
        Charge=app.extensions['fine_charge_model'];forwarded=Charge.query.filter(Charge.kind=='late',Charge.origin_bill_id.in_(ids)).all()
        for b in bills:
            s=students[b.student_id];d=details.get(s.id,{});campus=d.get('campus','');cls=s.class_name
            queued=[c for c in forwarded if c.origin_bill_id==b.id]
            existing=[x for x in b.lines if x.get('kind')=='late_fee']+[copy.deepcopy(c.data['line']) for c in queued]
            config=copy.deepcopy(existing[0]['policy']) if existing else resolved(campus,cls,settings)[1]
            row=None if existing else resolved(campus,cls,settings)[0]
            head=heads.get(config['head']);stamp=existing[0].get('policy_source',['saved-on-challan']) if existing else [row.id if row else None,row.version if row else 0,head['version'] if head else 0]
            if not existing and head:config['head_label']=head['label']
            basis_due=day(existing[0].get('basis_due',b.due.isoformat())) if existing else b.due
            basis=copy.deepcopy(existing[0].get('basis_values',{})) if existing else {}
            if not existing:
                basis['owing']=max(0,sum(x['amount'] for x in b.lines if x.get('kind') not in ('late_fee','late_fee_forward','attendance_fine'))-b.paid-b.discount)
                if config['mode'] in TUITION_MODES:
                    tuition=[x for x in b.lines if x.get('particular')=='Tuition Fee' and not x.get('arrears_key') and x.get('kind')!='late_fee']
                    if len(tuition)!=1 or not all(k in tuition[0] for k in ('actual','plan_discount')):raise ValueError('This challan has no unambiguous saved actual/decided tuition. Review it manually; no fine was saved.')
                    basis.update(actual=tuition[0]['actual'],decided=tuition[0]['amount'])
                    if basis['actual']-tuition[0]['plan_discount']!=basis['decided']:raise ValueError('The saved tuition basis is inconsistent. Review the challan manually.')
            calculation=late_calculation(config,basis_due,asof,basis);previous=sum(x['amount'] for x in existing);delta=max(0,calculation['total']-previous)
            reason='Ready for explicit application' if delta else 'No additional late fee due'
            if existing and any(x.get('origin_bill_id')!=b.id for x in existing):reason='Transferred fine needs manual review';delta=0
            elif s.status!='Active':reason='Inactive student: no assessment';delta=0
            elif b.frozen:reason='Frozen challan: no assessment';delta=0
            elif b.paid or b.discount:reason='Paid/part-paid or discounted challan needs manual review';delta=0
            elif sum(x['amount'] for x in b.lines if x.get('kind') not in ('late_fee','late_fee_forward','attendance_fine'))<=0:reason='No original fee amount remains on this challan';delta=0
            elif config['mode']=='none':reason='No enabled late-fee policy';delta=0
            elif not existing and (not head or head['timing']!='fine'):raise ValueError('The configured fine head changed. Review its policy before assessment.')
            elif any(x.get('particular')==config['head'] and x.get('kind')!='late_fee' for x in b.lines):reason='An untracked amount already uses this fine head; manual review required';delta=0
            digest=hashlib.sha256(json.dumps(b.lines,sort_keys=True,separators=(',',':')).encode()).hexdigest()
            sources.append([b.id,b.version,b.due.isoformat(),b.paid,b.discount,b.frozen,digest,s.id,s.status,s.name,campus,cls,stamp,config,[[c.id,c.version,c.amount,c.bill_id] for c in queued]])
            policy_scope=copy.deepcopy(existing[0].get('assessment_scope',{})) if existing else dict(campus=campus,class_name=cls,policy_campus=row.scope if row else '',policy_class=row.name if row else '')
            rows.append(dict(bill=b,student=s,campus=campus,class_name=cls,policy_scope=policy_scope,config=config,basis_due=basis_due,stamp=stamp,basis_values=basis,calculation=calculation,existing=previous,delta=delta,reason=reason,saved_policy=bool(existing)))
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
            b=row['bill'];line=dict(particular=row['config']['head'],display_name=row['config']['head_label'],amount=row['delta'],kind='late_fee',origin_bill_id=b.id,basis_due=row['basis_due'].isoformat(),basis_values=row['basis_values'],policy_source=row['stamp'],assessment_scope=row['policy_scope'],assessed_through=asof.isoformat(),policy=copy.deepcopy(row['config']),cumulative_target=row['calculation']['total'])
            before=copy.deepcopy(b.lines)
            if row['config'].get('next_challan'):
                first=date.fromisoformat(b.month+'-01')
                if first.year==9999 and first.month==12:raise ValueError('The source challan month cannot be forwarded.')
                target=first.replace(year=first.year+1,month=1) if first.month==12 else first.replace(month=first.month+1)
                Charge=app.extensions['fine_charge_model']
                db.session.add(Charge(student_id=b.student_id,kind='late',origin_bill_id=b.id,source=f"late:{b.id}:{row['calculation']['total']}",target_month=target.strftime('%Y-%m'),amount=row['delta'],data=dict(line=copy.deepcopy(line))))
            else:b.lines=[*b.lines,line]
            changed.append(dict(bill_id=b.id,before=before,added=line))
        if changed:db.session.add(Audit(action='Apply reviewed late fees',data=dict(asof=asof.isoformat(),owner_id=session.get('owner_id'),changes=changed)))
        commit();flash(f'{len(changed)} challans assessed; next-challan policies were queued and no duplicate fine was added.','success');return redirect(url_for('ops.fees',mode='payments'))
    @app.cli.command('institute-late-policy')
    @click.option('--code',required=True)
    @click.option('--campus',default='')
    @click.option('--show',is_flag=True)
    @click.option('--reset',is_flag=True)
    @click.option('--expected-version',type=int)
    @click.option('--mode',type=click.Choice(list(MODES)))
    @click.option('--rate',default='')
    @click.option('--grace',default='0')
    @click.option('--expiry',default='')
    @click.option('--maximum',default='')
    @click.option('--head',default='')
    @click.option('--accept-formula',is_flag=True)
    @click.option('--next-challan',is_flag=True)
    def operator_policy(code,campus,show,reset,expected_version,mode,rate,grace,expiry,maximum,head,accept_formula,next_challan):
        """Private provider operation; --show first, then use its version for updates."""
        School=app.extensions['identity_models']['institute']
        school=School.query.filter_by(code=code.strip().upper(),active=True).first()
        if not school:raise click.ClickException('Active institute not found.')
        engine=app.extensions['identity_helpers']['engine'](school.id)
        data=dict(mode=mode or '',rate=rate,grace=grace,expiry=expiry,maximum=maximum,head=head,next_challan='1' if next_challan else '')
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
