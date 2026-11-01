"""Provider-managed student attendance fines with reviewed next-month charges."""
import calendar,copy,hashlib,hmac,json,re
import click
from datetime import date,datetime
from zoneinfo import ZoneInfo
from flask import Blueprint,abort,flash,g,redirect,render_template,request,session,url_for
from itsdangerous import BadData,URLSafeTimedSerializer
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import StaleDataError
from operations import money

STATUSES=('Absent','Late','Leave','Short Leave')


def attendance_calculation(rules,counts):
    rows=[]
    for status in STATUSES:
        rule=rules.get(status,{});count=counts.get(status,0);extra=max(0,count-rule.get('free',0))
        amount=extra*rule.get('rate',0) if rule.get('enabled') else 0
        if amount>99999999900:raise ValueError('Attendance fine exceeds the supported amount.')
        rows.append(dict(status=status,count=count,free=rule.get('free',0),extra=extra,rate=rule.get('rate',0),enabled=bool(rule.get('enabled')),amount=amount))
    total=sum(r['amount'] for r in rows)
    if total>99999999900:raise ValueError('Combined attendance fine exceeds the supported amount.')
    return dict(rows=rows,total=total)


def configure_attendance_fines(app,db,Student):
    bp=Blueprint('attendance_fines',__name__,url_prefix='/workspace/core/fees/attendance-fines')
    Item=app.extensions['school_settings_models']['item'];rm=app.extensions['record_models'];ops=app.extensions['ops_models'];Daily=ops['daily'];Audit=ops['audit'];Charge=app.extensions['fine_charge_model']
    def today():return datetime.now(ZoneInfo('Asia/Karachi')).date()
    def month(raw):
        if not re.fullmatch(r'\d{4}-\d{2}',raw or ''):raise ValueError('Choose a valid attendance month.')
        try:first=date.fromisoformat(raw+'-01')
        except ValueError:raise ValueError('Choose a valid attendance month.')
        return first
    def next_month(first):
        if first.year==9999 and first.month==12:raise ValueError('Choose an earlier attendance month.')
        return first.replace(year=first.year+1,month=1) if first.month==12 else first.replace(month=first.month+1)
    def editable():return bool((app.testing and not app.config.get('IDENTITY_ENFORCE_IN_TESTS')) or session.get('demo'))
    def campuses():return sorted({r.value for r in rm['settings'].query.filter_by(category='campus').all()})
    def policy(campus):return Item.query.filter_by(kind='attendance-fine-policy',scope=campus,name='').first()
    def resolve(campus):return policy(campus) or (policy('') if campus else None)
    def parse():
        head=request.form.get('head','');rules={}
        for i,status in enumerate(STATUSES):
            free=request.form.get('free_'+str(i),'0')
            if not free.isdigit() or not 0<=int(free)<=31:raise ValueError('Free days must be whole numbers from 0 to 31.')
            rules[status]=dict(enabled=request.form.get('enabled_'+str(i))=='1',free=int(free),rate=money(request.form.get('rate_'+str(i),'0')))
        if any(r['enabled'] for r in rules.values()):
            feehead=next((h for h in app.extensions['fee_setup_helpers']['heads']() if h['key']==head and h['timing']=='fine'),None)
            if not feehead:raise ValueError('Choose a fee head configured as By fine policy.')
        return dict(head=head,rules=rules,sandwich_leave=False)
    def actor():return dict(scope=(getattr(g,'school_identity',None) or {}).get('scope'),owner=session.get('owner_id'),csrf=session.get('record_csrf'))
    def signer():return URLSafeTimedSerializer(app.config['SECRET_KEY'],salt='schoolflow-attendance-fines-v1')
    def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    def checked_campus():
        campus=request.values.get('campus','')
        if campus and campus not in campuses():raise ValueError('Choose a configured campus.')
        return campus
    @bp.before_request
    def protect():
        if request.method=='POST':
            if not request.form.get('_csrf') or not hmac.compare_digest(request.form['_csrf'],session.get('record_csrf','')):abort(400,'Reload attendance-fine settings.')
            app.extensions['admission_capacity']['lock']()
    @bp.errorhandler(ValueError)
    def invalid(error):
        db.session.rollback();return render_template('operation_error.html',title='Check attendance fines',error=str(error)),422
    @bp.errorhandler(IntegrityError)
    @bp.errorhandler(StaleDataError)
    def conflict(error):
        db.session.rollback();return render_template('operation_error.html',title='Check attendance fines',error='An attendance fine or policy changed. Preview again; no partial batch was saved.'),422
    @bp.route('',methods=['GET','POST'])
    def index():
        campus=checked_campus();row=policy(campus);resolved=resolve(campus);config=resolved.data if resolved else dict(head='',rules={})
        result=None
        if request.method=='POST':
            action=request.form.get('action')
            if action not in ('save','reset','simulate'):raise ValueError('Choose Save, Reset or Simulate.')
            if action!='simulate' and not editable():abort(403,'Attendance-fine policies are provider-managed. Contact your SchoolFlow operator.')
            if request.form.get('version')!=str(row.version if row else 0):raise ValueError('This policy changed. Reload before saving.')
            config=parse() if action!='reset' else None
            if action=='simulate':
                counts={}
                for i,status in enumerate(STATUSES):
                    value=request.form.get('count_'+str(i),'0')
                    if not value.isdigit() or not 0<=int(value)<=31:raise ValueError('Simulator counts must be 0–31.')
                    counts[status]=int(value)
                if sum(counts.values())>31:raise ValueError('A day can have only one attendance status; total simulator days cannot exceed 31.')
                result=attendance_calculation(config['rules'],counts)
            else:
                before=copy.deepcopy(row.data) if row else None
                if action=='reset':
                    if row:db.session.delete(row)
                elif row:row.data=config
                else:db.session.add(Item(kind='attendance-fine-policy',scope=campus,name='',data=config))
                db.session.add(Audit(action='Save attendance fine policy' if action=='save' else 'Reset attendance fine policy',data=dict(campus=campus,before=before,after=config if action=='save' else None,owner_id=session.get('owner_id'))));db.session.commit()
                flash('Policy saved. No student was charged.','success');return redirect(url_for('attendance_fines.index',campus=campus))
        response=render_template('attendance_fine_policy.html',title='Student attendance fines',campus=campus,campuses=campuses(),row=row,config=config,statuses=STATUSES,heads=[h for h in app.extensions['fee_setup_helpers']['heads']() if h['timing']=='fine'],editable=editable(),result=result)
        if request.method=='POST':db.session.rollback()
        return response

    def assess(ids,first):
        end=first.replace(day=calendar.monthrange(first.year,first.month)[1]);key=first.strftime('%Y-%m');target=next_month(first).strftime('%Y-%m')
        pupils=Student.query.filter(Student.id.in_(ids)).order_by(Student.id).all()
        if len(pupils)!=len(ids):raise ValueError('A selected student is missing.')
        details=app.extensions['record_helpers']['raw_many']('student',pupils)
        attendance=Daily.query.filter(Daily.kind=='student',Daily.person_id.in_(ids),Daily.day>=first,Daily.day<=end).order_by(Daily.id).all()
        heads={h['key']:h for h in app.extensions['fee_setup_helpers']['heads']()};rows=[];sources=[]
        policies={p.scope:p for p in Item.query.filter_by(kind='attendance-fine-policy').all()}
        existing_charges={c.source:c for c in Charge.query.filter(Charge.source.in_([f'attendance:{sid}:{key}' for sid in ids])).all()}
        for pupil in pupils:
            d=details.get(pupil.id,{});campus=d.get('campus','')
            p=policies.get(campus) or policies.get('');config=copy.deepcopy(p.data) if p else dict(head='',rules={})
            head=heads.get(config['head']);saved=[r for r in attendance if r.person_id==pupil.id]
            # Never fabricate Absent entries. Only saved attendance since admission is chargeable.
            admitted=d.get('admission_date','');eligible=[r for r in saved if not admitted or r.day.isoformat()>=admitted]
            counts={status:sum(r.status==status for r in eligible) for status in STATUSES};result=attendance_calculation(config.get('rules',{}),counts)
            source=f'attendance:{pupil.id}:{key}';existing=existing_charges.get(source);reason='Ready for reviewed next-month charge'
            if pupil.status!='Active':reason='Inactive student';result['total']=0
            elif not p or not any(r.get('enabled') for r in config.get('rules',{}).values()):reason='No enabled policy';result['total']=0
            elif existing:reason='Already assessed for this student and month';result['total']=0
            elif not head or head['timing']!='fine':raise ValueError('The attendance fine head changed. Review its policy before assessment.')
            elif not result['total']:reason='No attendance fine due'
            line=dict(particular=config['head'],display_name=head['label'] if head else config['head'],attendance_month=key,policy=copy.deepcopy(config),policy_source=[p.id,p.version] if p else None,counts=counts,calculation=result['rows'],assessment_scope=dict(campus=campus,class_name=pupil.class_name))
            source_data=[pupil.id,pupil.status,pupil.name,pupil.class_name,campus,admitted,[p.id,p.version,config] if p else None,head,[r.id for r in eligible],[[r.id,r.day.isoformat(),r.status] for r in saved],[existing.id,existing.version,existing.bill_id] if existing else None]
            sources.append(source_data);rows.append(dict(student=pupil,source=source,result=result,target=target,reason=reason,line=line))
        return rows,digest(sources)
    @bp.route('/assess',methods=['GET','POST'])
    def assessment():
        default=(today().replace(day=1).toordinal()-1);first=month(request.values.get('month',date.fromordinal(default).strftime('%Y-%m')));campus=checked_campus()
        if request.method=='POST':
            action=request.form.get('action')
            if action=='preview':
                raw=request.form.getlist('student_ids')
                if not raw or len(raw)>100 or any(not x.isdigit() for x in raw):raise ValueError('Select 1–100 students.')
                ids=sorted({int(x) for x in raw});rows,stamp=assess(ids,first)
                token=signer().dumps(dict(actor=actor(),ids=ids,month=first.strftime('%Y-%m'),stamp=stamp))
                response=render_template('attendance_fine_review.html',title='Review attendance fines',rows=rows,month=first.strftime('%Y-%m'),token=token,future=first>=today().replace(day=1))
                db.session.rollback();return response
            if action!='apply':raise ValueError('Preview attendance fines before applying.')
            raw=request.form.get('preview_token','')
            if len(raw)>131072:raise ValueError('Invalid attendance review.')
            try:payload=signer().loads(raw,max_age=900)
            except BadData:raise ValueError('Attendance review expired or changed. Preview again.')
            if not isinstance(payload,dict) or payload.get('actor')!=actor():raise ValueError('This attendance review belongs to another institute or session.')
            first=month(payload['month'])
            if first>=today().replace(day=1):raise ValueError('Only completed attendance months can be charged. Current/future months are simulation only.')
            rows,stamp=assess(payload['ids'],first)
            if stamp!=payload['stamp']:raise ValueError('Attendance, student, fine head or policy changed. Preview again; no fines were saved.')
            count=0
            for r in rows:
                if not r['result']['total']:continue
                charge=Charge(student_id=r['student'].id,kind='attendance',source=r['source'],target_month=r['target'],amount=r['result']['total'],data=dict(line=r['line']))
                db.session.add(charge);count+=1
            db.session.add(Audit(action='Assess student attendance fines',data=dict(month=payload['month'],count=count,source_digest=stamp,owner_id=session.get('owner_id'))));db.session.commit()
            flash(f'{count} reviewed attendance fines saved for later challans. Existing bills were unchanged.','success');return redirect(url_for('fine_queue.index'))
        query=Student.query.filter_by(status='Active')
        if campus:query=query.join(rm['student'],rm['student'].student_id==Student.id).filter(rm['student'].data['campus'].as_string()==campus)
        pupils=query.order_by(Student.name).limit(1001).all()
        return render_template('attendance_fine_assess.html',title='Assess monthly student attendance fines',month=first.strftime('%Y-%m'),campus=campus,campuses=campuses(),students=pupils[:1000],more=len(pupils)>1000)

    @app.cli.command('institute-attendance-fine-policy')
    @click.option('--code',required=True)
    @click.option('--campus',default='')
    @click.option('--show',is_flag=True)
    @click.option('--expected-version',type=int)
    @click.option('--head',default='')
    @click.option('--rule',multiple=True,help='STATUS:FREE_DAYS:PKR_PER_EXTRA_DAY. Omitted statuses are disabled.')
    def operator(code,campus,show,expected_version,head,rule):
        school=app.extensions['identity_models']['institute'].query.filter_by(code=code.strip().upper(),active=True).first()
        if not school:raise click.ClickException('Active institute not found.')
        form=dict(head=head)
        for raw in rule:
            parts=raw.split(':')
            if len(parts)!=3 or parts[0] not in STATUSES:raise click.ClickException('Use Absent, Late, Leave or Short Leave:FREE_DAYS:RATE; Sandwich Leave is disabled.')
            i=STATUSES.index(parts[0]);form.update({'enabled_'+str(i):'1','free_'+str(i):parts[1],'rate_'+str(i):parts[2]})
        with app.test_request_context('/operator/attendance-fines',method='POST',data=form):
            g.institute_engine=app.extensions['identity_helpers']['engine'](school.id);db.session.remove()
            try:
                if campus and campus not in campuses():raise ValueError('Choose a configured campus.')
                if show:
                    p=policy(campus);click.echo(json.dumps(dict(version=p.version if p else 0,policy=p.data if p else None)));return
                app.extensions['admission_capacity']['lock']();db.session.expire_all();p=policy(campus)
                if expected_version is None or expected_version!=(p.version if p else 0):raise ValueError('Use --show and the current --expected-version.')
                config=parse();before=copy.deepcopy(p.data) if p else None
                if p:p.data=config
                else:db.session.add(Item(kind='attendance-fine-policy',scope=campus,name='',data=config))
                db.session.add(Audit(action='Provider save attendance fine policy',data=dict(campus=campus,before=before,after=config,actor='provider-cli')));db.session.commit();click.echo('Policy saved for this institute only. No student was charged.')
            except ValueError as error:db.session.rollback();raise click.ClickException(str(error))
            finally:db.session.remove();g.pop('institute_engine',None)
    app.extensions['attendance_fine_helpers']=dict(head_used=lambda key:any(p.data.get('head')==key for p in Item.query.filter_by(kind='attendance-fine-policy').all()))
    app.register_blueprint(bp)
