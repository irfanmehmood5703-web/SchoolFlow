"""Opt-in tenant late-fee schedules with durable per-bill/day claims.

The embedded worker runs only when explicitly enabled by the host. Free sleeping
hosting cannot promise an always-on clock; the same engine has an operator CLI.
"""
import copy,hashlib,hmac,json,re,threading
from datetime import date,datetime,timedelta,timezone
from zoneinfo import ZoneInfo
import click
from flask import Blueprint,abort,flash,g,redirect,render_template,request,session,url_for
from itsdangerous import BadData,URLSafeTimedSerializer
from sqlalchemy import and_,func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import StaleDataError


def local_now():return datetime.now(ZoneInfo('Asia/Karachi'))


def first_run_day(due,policy,schedule):
    at=due+timedelta(days=max(1,policy.get('grace',0)+1,schedule['delay']))
    for _ in range(3670):
        if not closed_day(at,schedule):return at
        at+=timedelta(days=1)
    raise ValueError('This calendar has no reachable working day.')


def closed_day(day,schedule):
    weekly=schedule.get('defer_weekly',schedule.get('defer',False)) and day.weekday() in schedule.get('off_days',[])
    holiday=schedule.get('defer_holidays',schedule.get('defer',False)) and (day.isoformat() in schedule.get('holidays',[]) or day.isoformat() in schedule.get('calendar_dates',[]) or day.strftime('%m-%d') in schedule.get('calendar_annual',[]))
    return bool(weekly or holiday)


def configure_fine_automation(app,db,Student):
    bp=Blueprint('fine_automation',__name__,url_prefix='/workspace/core/fees/automation')
    Item=app.extensions['school_settings_models']['item'];ops=app.extensions['ops_models'];Bill=ops['bill'];Audit=ops['audit'];Charge=app.extensions['fine_charge_model'];rm=app.extensions['record_models']
    class FineAutomationRun(db.Model):
        key=db.Column(db.String(120),primary_key=True)
        schedule_id=db.Column(db.Integer,nullable=False,index=True)
        campus=db.Column(db.String(160),nullable=False)
        day=db.Column(db.Date,nullable=False,index=True)
        bill_id=db.Column(db.Integer,db.ForeignKey('bill.id'))
        status=db.Column(db.String(30),nullable=False)
        amount=db.Column(db.Integer,nullable=False,default=0)
        data=db.Column(db.JSON,nullable=False)
        created=db.Column(db.DateTime,nullable=False,default=lambda:datetime.now(timezone.utc))
    app.extensions['fine_automation_run_model']=FineAutomationRun
    def campuses():return sorted({r.value for r in rm['settings'].query.filter_by(category='campus').all()})
    def schedule(campus):return Item.query.filter_by(kind='late-fee-automation',scope=campus,name='').first()
    def policy(campus):return Item.query.filter_by(kind='late-fee-policy',scope=campus,name='').first() or Item.query.filter_by(kind='late-fee-policy',scope='',name='').first()
    def defaults():return dict(enabled=False,activation_day=local_now().date().isoformat(),delay=1,time='02:00',defer=True,off_days=[6],holidays=[])
    def actor():return dict(scope=(getattr(g,'school_identity',None) or {}).get('scope'),owner=session.get('owner_id'),csrf=session.get('record_csrf'))
    def signer():return URLSafeTimedSerializer(app.config['SECRET_KEY'],salt='schoolflow-fine-schedule-v1')
    def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),default=str).encode()).hexdigest()
    def parse(row):
        delay=request.form.get('delay','1');when=request.form.get('time','00:05');off=request.form.getlist('off_days')
        if not delay.isdigit() or not 0<=int(delay)<=3660:raise ValueError('Choose 0–3,660 days after due date.')
        if not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d',when):raise ValueError('Choose a valid Pakistan-time run time.')
        if any(x not in tuple(str(n) for n in range(7)) for x in off):raise ValueError('Choose valid weekly off days.')
        holidays=[]
        for raw in re.split(r'[\s,]+',request.form.get('holidays','').strip()):
            if not raw:continue
            try:d=date.fromisoformat(raw)
            except ValueError:raise ValueError('Enter holiday dates as YYYY-MM-DD, one per line.')
            if d.isoformat()!=raw:raise ValueError('Use full YYYY-MM-DD holiday dates.')
            holidays.append(raw)
        if len(holidays)>366:raise ValueError('Save at most 366 holiday dates per campus.')
        enabled=request.form.get('enabled')=='1';defer=request.form.get('defer')=='1';extra={}
        if request.form.get('calendar_controls')=='1':
            extra=dict(defer_weekly=request.form.get('defer_weekly')=='1',defer_holidays=request.form.get('defer_holidays')=='1',notify=request.form.get('notify')=='1')
            defer=extra['defer_weekly'] or extra['defer_holidays']
        if extra.get('defer_weekly',defer) and len(set(off))==7:raise ValueError('Leave at least one working weekday.')
        activation=row.data.get('activation_day') if row and row.data.get('enabled') else local_now().date().isoformat()
        return dict(enabled=enabled,activation_day=activation,delay=int(delay),time=when,defer=defer,off_days=sorted({int(x) for x in off}),holidays=sorted(set(holidays)),**extra)
    def fingerprint(bill,charges):return digest([bill.due.isoformat(),bill.student_id,bill.lines,[[c.id,c.amount,c.data] for c in charges]])
    def plan(row,cfg,now):
        at=now.date();p=policy(row.scope if row else request.values.get('campus',''));campus=row.scope if row else request.values.get('campus','')
        calendar=app.extensions['holiday_calendar_helpers']['rows'](campus)
        effective={**cfg,'calendar_dates':[r.data['date'] for r in calendar if not r.data['repeats']],'calendar_annual':[r.data['date'][5:] for r in calendar if r.data['repeats']]}
        base=p.data if p else {};sid=row.id if row else 0;activation=date.fromisoformat(cfg['activation_day']);closed=closed_day(at,effective)
        state='Weekly off / holiday: defer to the next working day' if closed else ('Before configured Pakistan-time run time' if now.strftime('%H:%M')<cfg['time'] else '')
        if not p or base.get('mode')=='none':state='No active late-fee policy'
        if base.get('maximum')==0:state='Fine policy maximum is zero'
        details_model=rm['student']
        pupils=Student.query.join(details_model,details_model.student_id==Student.id).filter(Student.status=='Active',details_model.data['campus'].as_string()==campus).all()
        pupils_by={s.id:s for s in pupils}
        bills=Bill.query.filter(Bill.student_id.in_(pupils_by),Bill.due<=at,Bill.paid==0,Bill.discount==0,Bill.frozen==False).order_by(Bill.id).all()
        charges=Charge.query.filter(Charge.kind=='late',Charge.origin_bill_id.in_([b.id for b in bills])).order_by(Charge.id).all()
        latest={};done=set()
        if sid:
            last_days=db.session.query(FineAutomationRun.bill_id.label('bid'),func.max(FineAutomationRun.day).label('last_day')).filter(FineAutomationRun.schedule_id==sid,FineAutomationRun.status=='Applied',FineAutomationRun.bill_id.in_([b.id for b in bills])).group_by(FineAutomationRun.bill_id).subquery()
            recent=FineAutomationRun.query.join(last_days,and_(FineAutomationRun.bill_id==last_days.c.bid,FineAutomationRun.day==last_days.c.last_day)).filter(FineAutomationRun.schedule_id==sid,FineAutomationRun.status=='Applied').all()
            latest={r.bill_id:r for r in recent}
            done={bid for (bid,) in db.session.query(FineAutomationRun.bill_id).filter(FineAutomationRun.schedule_id==sid,FineAutomationRun.day==at).all()}
        ready=[];skips=[];sources=[];eligible=[];noops=[]
        helper=app.extensions['late_fee_helpers']
        for b in bills:
            owned=[c for c in charges if c.origin_bill_id==b.id];fine_lines=[x for x in b.lines if x.get('kind')=='late_fee']+[c.data['line'] for c in owned]
            prior=latest.get(b.id);reason=state
            saved_policy=fine_lines[0].get('policy',base) if fine_lines else base
            first=first_run_day(b.due,saved_policy,effective)
            stamp=fingerprint(b,owned)
            if not reason and b.id in done:reason='Already processed today'
            if not reason and first>at:reason='Scheduled for '+first.isoformat()
            if not reason and not prior and first<activation:reason='Old debt: no first-enable backfill'
            if not reason and fine_lines and any(x.get('automation')!=sid for x in fine_lines):reason='Manually assessed fine: automatic changes stopped'
            if not reason and prior and prior.data.get('after_fingerprint')!=stamp:reason='Fine/bill changed by hand: automatic changes stopped'
            sources.append([b.id,b.version,pupils_by[b.student_id].name,stamp,reason])
            if reason:skips.append(dict(bill=b,student=pupils_by[b.student_id],reason=reason));continue
            if len(eligible)<100:eligible.append(b.id)
        results=[]
        if eligible:
            try:
                results,source=helper['assessed'](eligible,at);sources.append(source)
            except ValueError:
                for bid in eligible:
                    try:
                        partial,source=helper['assessed']([bid],at);results.extend(partial);sources.append(source)
                    except ValueError as error:
                        b=next(b for b in bills if b.id==bid);skips.append(dict(bill=b,student=pupils_by[b.student_id],reason=str(error)))
        for r in results:
            if r['delta']:ready.append(r)
            else:
                noops.append(r);skips.append(dict(bill=r['bill'],student=r['student'],reason=r['reason']))
        return dict(rows=ready,noops=noops,skips=skips,reason=state,total=sum(r['delta'] for r in ready),stamp=digest([sid,row.version if row else 0,cfg,[[r.id,r.version,r.data] for r in calendar],[p.id,p.version,p.data] if p else None,sources]),candidate_count=len(bills))
    def execute(row,now,mode='schedule'):
        app.extensions['admission_capacity']['lock']();db.session.expire_all();row=db.session.get(Item,row.id)
        if not row or not row.data.get('enabled'):return dict(applied=0,total=0,reason='Schedule disabled')
        preview=plan(row,row.data,now);at=now.date();count=0;total=0
        if preview['reason']:
            key=f'{row.id}:{at}:deferred'
            if not db.session.get(FineAutomationRun,key):db.session.add(FineAutomationRun(key=key,schedule_id=row.id,campus=row.scope,day=at,status='Deferred',amount=0,data=dict(reason=preview['reason'],mode=mode)))
        else:
            for r in preview['noops']:
                key=f'{row.id}:{at}:{r["bill"].id}'
                if not db.session.get(FineAutomationRun,key):db.session.add(FineAutomationRun(key=key,schedule_id=row.id,campus=row.scope,day=at,bill_id=r['bill'].id,status='No change',amount=0,data=dict(mode=mode,reason=r['reason'])))
            for r in preview['rows']:
                key=f'{row.id}:{at}:{r["bill"].id}'
                if db.session.get(FineAutomationRun,key):continue
                helper=app.extensions['late_fee_helpers'];changes=helper['apply']([r],at,automation=row.id);db.session.flush()
                owned=Charge.query.filter_by(kind='late',origin_bill_id=r['bill'].id).order_by(Charge.id).all()
                amount=sum(c['added']['amount'] for c in changes)
                db.session.add(FineAutomationRun(key=key,schedule_id=row.id,campus=row.scope,day=at,bill_id=r['bill'].id,status='Applied',amount=amount,data=dict(mode=mode,owner_id=session.get('owner_id'),after_fingerprint=fingerprint(r['bill'],owned))))
                count+=1;total+=amount
        if count and row.data.get('notify'):
            db.session.add(ops['workflow'](kind='message',status='Provider not configured',data=dict(subject='Late-fee automation run',audience='owner',ids=[],campus=row.scope,day=at.isoformat(),applied=count,total=total,preferences={'parent_notification':False},messages=[])))
        db.session.commit();return dict(applied=count,total=total,reason=preview['reason'])
    @bp.before_request
    def protect():
        if request.method=='POST':
            if not request.form.get('_csrf') or not hmac.compare_digest(request.form['_csrf'],session.get('record_csrf','')):abort(400,'Reload the schedule form.')
            app.extensions['admission_capacity']['lock']()
    @bp.errorhandler(ValueError)
    def invalid(error):db.session.rollback();return render_template('operation_error.html',title='Check fine schedule',error=str(error)),422
    @bp.errorhandler(IntegrityError)
    @bp.errorhandler(StaleDataError)
    def conflict(error):db.session.rollback();return render_template('operation_error.html',title='Check fine schedule',error='A schedule, bill or run changed. Reload and preview again; no partial run was saved.'),422
    @bp.route('',methods=['GET','POST'])
    def index():
        campus=request.values.get('campus','')
        if not campus or campus not in campuses():
            if request.method=='POST':raise ValueError('Choose a configured campus.')
            return render_template('fine_automation.html',title='Late-fee automation',campus='',campuses=campuses(),row=None,config=defaults(),preview=None,token='',history=[],worker=bool(app.config.get('FINE_WORKER_ENABLED')))
        row=schedule(campus);cfg=copy.deepcopy(row.data) if row else defaults();preview=None;token=''
        if request.method=='POST':
            action=request.form.get('action');cfg=parse(row)
            if request.form.get('version')!=str(row.version if row else 0):raise ValueError('This schedule changed. Reload first.')
            if action=='preview':
                preview=plan(row,cfg,local_now());token=signer().dumps(dict(actor=actor(),campus=campus,version=row.version if row else 0,config=cfg,stamp=preview['stamp'],day=local_now().date().isoformat()))
            elif action in ('save','run'):
                if cfg['enabled'] or action=='run':
                    raw=request.form.get('preview_token','')
                    if len(raw)>131072:raise ValueError('Invalid preview.')
                    try:payload=signer().loads(raw,max_age=900)
                    except BadData:raise ValueError('Preview today’s run with these settings before enabling or running it.')
                    current=plan(row,cfg,local_now())
                    expected=dict(actor=actor(),campus=campus,version=row.version if row else 0,config=cfg,stamp=current['stamp'],day=local_now().date().isoformat())
                    if payload!=expected:raise ValueError('The preview, campus, settings, policy or challans changed. Preview again.')
                    p=policy(campus)
                    if not p or p.data.get('mode')=='none' or p.data.get('maximum')==0:raise ValueError('An active, nonzero late-fee policy is required before enabling automation.')
                if action=='run':
                    if not row or not row.data.get('enabled') or cfg!=row.data:raise ValueError('Save and enable the previewed schedule before Run now.')
                    result=execute(row,local_now(),mode='manual');flash(f"Run complete: {result['applied']} challans; PKR {result['total']/100:,.2f}.",'success');return redirect(url_for('fine_automation.index',campus=campus))
                before=copy.deepcopy(row.data) if row else None
                if row:row.data=cfg
                else:row=Item(kind='late-fee-automation',scope=campus,name='',data=cfg);db.session.add(row)
                db.session.add(Audit(action='Save late-fee automation',data=dict(campus=campus,before=before,after=cfg,owner_id=session.get('owner_id'))));db.session.commit();flash('Schedule saved. Saving itself did not charge a bill.','success');return redirect(url_for('fine_automation.index',campus=campus))
            else:raise ValueError('Choose Preview, Save or Run now.')
        history_query=FineAutomationRun.query.filter_by(campus=campus)
        history_q=request.args.get('q','').strip()
        if len(history_q)>160:raise ValueError('Use a history search up to 160 characters.')
        history=history_query.order_by(FineAutomationRun.created.desc()).all()
        if history_q:history=[r for r in history if history_q.casefold() in (' '.join(map(str,[r.day,r.bill_id or '',r.status,r.data.get('mode',''),r.data.get('reason','')]))).casefold()]
        if request.args.get('export')=='xlsx':
            from report_exports import report_xlsx
            return report_xlsx(['Run date','Challan','Result','Amount','Started by / reason'],[[r.day.isoformat(),r.bill_id or 'Campus',r.status,f'{r.amount/100:.2f}',r.data.get('mode','')+' / '+r.data.get('reason','')] for r in history],'late-fee-runs')
        history=history[:100]
        p=policy(campus);active_policy=bool(p and p.data.get('mode')!='none' and p.data.get('maximum')!=0)
        response=render_template('fine_automation.html',title='Late-fee automation',campus=campus,campuses=campuses(),row=row,config=cfg,preview=preview,token=token,history=history,worker=bool(app.config.get('FINE_WORKER_ENABLED')),active_policy=active_policy)
        if request.method=='POST':db.session.rollback()
        return response
    @app.cli.command('late-fee-tick')
    @click.option('--code',required=True)
    @click.option('--dry-run',is_flag=True)
    def tick_cli(code,dry_run):
        School=app.extensions['identity_models']['institute'];school=School.query.filter_by(code=code.strip().upper(),active=True).first()
        if not school:raise click.ClickException('Active institute not found.')
        engine=app.extensions['identity_helpers']['engine'](school.id)
        with app.test_request_context('/operator/fine-tick'):
            g.institute_engine=engine;db.session.remove()
            try:
                results=[]
                for row in Item.query.filter_by(kind='late-fee-automation').all():
                    if not row.data.get('enabled'):continue
                    if dry_run:
                        p=plan(row,row.data,local_now());results.append(dict(campus=row.scope,applied=0,preview_count=len(p['rows']),total=p['total'],reason=p['reason']))
                    else:results.append(dict(campus=row.scope,**execute(row,local_now(),mode='operator-cli')))
                click.echo(json.dumps(results));db.session.rollback()
            finally:db.session.remove();g.pop('institute_engine',None)
    def tick_all():
        with app.app_context():
            School=app.extensions['identity_models']['institute'];schools=[(s.id,app.extensions['identity_helpers']['engine'](s.id)) for s in School.query.filter_by(active=True).all()];db.session.remove()
            for school_id,engine in schools:
                with app.test_request_context('/internal/fine-worker'):
                    g.institute_engine=engine
                    try:
                        ids=[r.id for r in Item.query.filter_by(kind='late-fee-automation').all() if r.data.get('enabled')]
                        for sid in ids:execute(db.session.get(Item,sid),local_now())
                    except Exception:
                        db.session.rollback();app.logger.exception('Fine schedule tick failed for institute %s',school_id)
                    finally:db.session.remove();g.pop('institute_engine',None)
    def start_worker():
        if not app.config.get('FINE_WORKER_ENABLED'):return
        def loop():
            while True:
                threading.Event().wait(60)
                try:tick_all()
                except Exception:app.logger.exception('Fine schedule worker tick failed')
                try:app.extensions['attendance_device_helpers']['tick_all']()
                except Exception:app.logger.exception('Attendance schedule worker tick failed')
        thread=threading.Thread(target=loop,name='schoolflow-fine-worker',daemon=True);thread.start()
        app.logger.warning('SchoolFlow fine scheduler started: 60-second checks for enabled real-institute schedules.')
    app.extensions['fine_automation_helpers']=dict(plan=plan,execute=execute,tick_all=tick_all,start_worker=start_worker,bill_used=lambda bid:FineAutomationRun.query.filter_by(bill_id=bid).first() is not None)
    app.register_blueprint(bp)
