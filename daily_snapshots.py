"""Observed daily history; never reconstruct earlier balances from today's rows."""
from datetime import date,datetime,timezone
import hmac
import click
from flask import Blueprint,abort,g,redirect,render_template,request,session,url_for,flash
from sqlalchemy import func
from sqlalchemy.exc import OperationalError


def configure_daily_snapshots(app,db,Student):
    bp=Blueprint('daily_snapshots',__name__,url_prefix='/workspace/finance/snapshots');H=app.extensions['ledger_helpers'];rm=app.extensions['record_models'];ops=app.extensions['ops_models']
    class Control(db.Model):
        __tablename__='daily_snapshot_control'
        id=db.Column(db.Integer,primary_key=True)
        enabled=db.Column(db.Boolean,nullable=False,default=True)
    class Snapshot(db.Model):
        __tablename__='daily_school_snapshot'
        id=db.Column(db.Integer,primary_key=True)
        day=db.Column(db.Date,nullable=False,index=True)
        campus=db.Column(db.String(160),nullable=False,index=True)
        captured=db.Column(db.DateTime,nullable=False)
        metrics=db.Column(db.JSON,nullable=False)
        students=db.deferred(db.Column(db.JSON,nullable=False))
        __table_args__=(db.UniqueConstraint('day','campus'),)
    app.extensions['snapshot_models']=dict(control=Control,snapshot=Snapshot)
    def today():return H['today']()
    def capture_unscoped():
        """Current date only, serialized with source writes; past rows stay frozen."""
        app.extensions['admission_capacity']['lock']();day=today();now=datetime.now(timezone.utc)
        previous_day=db.session.query(func.max(Snapshot.day)).filter(Snapshot.day<=day).scalar()
        latest=db.session.query(Snapshot.campus.label('campus'),func.max(Snapshot.day).label('day')).filter(Snapshot.day<=day).group_by(Snapshot.campus).subquery()
        old=Snapshot.query.join(latest,(Snapshot.campus==latest.c.campus)&(Snapshot.day==latest.c.day)).all() if previous_day else []
        previous={s.campus:s for s in old};prior_ids={i['id'] for s in old for i in s.students if i['active']}
        details={d.student_id:d.data for d in rm['student'].query.all()};students=Student.query.order_by(Student.id).all();active_ids={s.id for s in students if s.status=='Active'}
        fees={}
        for bill in ops['bill'].query.filter(ops['bill'].month<=day.strftime('%Y-%m')).all():
            values=fees.setdefault(bill.student_id,[0,0,0,0]);values[0]+=bill.total;values[1]+=bill.paid;values[2]+=bill.discount;values[3]+=bill.remaining
        attendance={a.person_id:a.status for a in ops['daily'].query.filter_by(kind='student',day=day).all()}
        cohorts={}
        for s in students:
            campus=details.get(s.id,{}).get('campus') or 'Unassigned';f=fees.get(s.id,[0,0,0,0]);status=attendance.get(s.id)
            cohorts.setdefault(campus,[]).append(dict(id=s.id,name=s.name,class_name=s.class_name or 'Unassigned',status=s.status,active=s.status=='Active',expected=f[0],collected=f[1],discount=f[2],outstanding=f[3],marked=bool(status and status!='Off Day'),present=status in ('Present','Late')))
        campuses=set(H['campuses']())|set(cohorts)|set(previous)
        if not campuses:raise ValueError('Configure a campus or student campus before recording snapshots.')
        for campus in sorted(campuses):
            people=cohorts.get(campus,[]);old_row=previous.get(campus);existing=Snapshot.query.filter_by(day=day,campus=campus).first()
            before=old_row.students if old_row else [];own_ids={i['id'] for i in people if i['active']};prior_own={i['id'] for i in before if i['active']}
            joined=len(own_ids-prior_ids) if previous_day else 0;left=len((prior_own-active_ids)) if previous_day else 0
            old_metrics=existing.metrics if existing else {}
            metrics=dict(strength=len(own_ids),joined=old_metrics.get('joined',0)+joined,left=old_metrics.get('left',0)+left,marked=sum(p['marked'] for p in people),present=sum(p['present'] for p in people),expected=sum(p['expected'] for p in people),collected=sum(p['collected'] for p in people),discount=sum(p['discount'] for p in people),outstanding=sum(p['outstanding'] for p in people),income=None,expense=None,baseline=old_metrics.get('baseline',not bool(previous_day)))
            if existing:existing.metrics=metrics;existing.students=people;existing.captured=now
            else:db.session.add(Snapshot(day=day,campus=campus,captured=now,metrics=metrics,students=people))
        db.session.commit()
    def capture():
        # Internal capture records the whole institute after scoped source saves;
        # none of this internal data is returned to the requesting staff member.
        principal=getattr(g,'staff_principal',None);allowed=getattr(g,'access_campuses',None)
        g.staff_principal=None;g.access_campuses=None
        try:return capture_unscoped()
        finally:g.staff_principal=principal;g.access_campuses=allowed
    def render(template,**kw):return render_template(template,title='Daily Snapshot Report',**kw)
    @bp.errorhandler(ValueError)
    def invalid(exc):db.session.rollback();return render_template('operation_error.html',title='Check snapshot filters',error=str(exc)),422
    @bp.post('/capture')
    def start():
        if not request.form.get('_csrf') or not hmac.compare_digest(request.form['_csrf'],session.get('record_csrf','')):abort(400,'Reload the snapshot page.')
        app.extensions['admission_capacity']['lock']()
        if not db.session.get(Control,1):db.session.add(Control(id=1,enabled=True))
        capture();flash('Current snapshot recorded. Earlier unrecorded days were not backfilled.','success');return redirect(url_for('daily_snapshots.index'))
    @bp.get('')
    def index():
        first=db.session.query(func.min(Snapshot.day)).scalar();start_raw=request.args.get('from',(first or today()).isoformat());end_raw=request.args.get('to',today().isoformat())
        try:start_day=date.fromisoformat(start_raw);end_day=date.fromisoformat(end_raw)
        except ValueError:raise ValueError('Choose valid From/To dates.')
        if end_day<start_day or (end_day-start_day).days>366:raise ValueError('Choose an ordered date range of at most 367 days.')
        campuses=sorted(set(H['campuses']())|{x[0] for x in db.session.query(Snapshot.campus).distinct()});campus=request.args.get('campus','')
        if campus and campus not in campuses:raise ValueError('Choose a campus from the report.')
        q=Snapshot.query.filter(Snapshot.day>=start_day,Snapshot.day<=end_day)
        if campus:q=q.filter_by(campus=campus)
        if q.count()>5000:raise ValueError('Narrow the date or campus filter to at most 5,000 daily rows.')
        rows=q.order_by(Snapshot.day,Snapshot.campus).all();closing={}
        for r in rows:closing[r.campus]=r
        totals={k:sum(r.metrics[k] for r in closing.values()) for k in ('strength','expected','collected','discount','outstanding')}
        totals.update({k:sum(r.metrics[k] for r in rows) for k in ('joined','left','marked','present')});totals['attendance']=totals['present']*100/totals['marked'] if totals['marked'] else None
        return render('daily_snapshots.html',first=first,start=start_day,end=end_day,campuses=campuses,campus=campus,rows=rows,totals=totals,closing_day=max((r.day for r in rows),default=None),enabled=bool(db.session.get(Control,1)),snapshot_today=today().isoformat())
    @bp.get('/<int:sid>/<mode>')
    def detail(sid,mode):
        if mode not in ('classes','students'):abort(404)
        row=db.get_or_404(Snapshot,sid);classes={}
        for p in row.students:
            total=classes.setdefault(p['class_name'],dict(strength=0,expected=0,collected=0,outstanding=0))
            total['strength']+=p['active']
            for k in ('expected','collected','outstanding'):total[k]+=p[k]
        return render('snapshot_detail.html',row=row,mode=mode,classes=classes)
    @app.after_request
    def update_after_source(response):
        prefixes=('records.','ops.','student_plans.','fee_setup.','yearly_fees.','fine_automation.','attendance_fines.','late_fees.')
        if request.method=='POST' and response.status_code<400 and (request.endpoint or '').startswith(prefixes):
            try:
                control=db.session.get(Control,1)
                if control and control.enabled:capture()
            except Exception:
                db.session.rollback();app.logger.exception('Daily snapshot capture failed; source operation response preserved')
        return response
    def tick_all():
        with app.app_context():
            School=app.extensions['identity_models']['institute'];schools=[(s.id,app.extensions['identity_helpers']['engine'](s.id)) for s in School.query.filter_by(active=True).all()];db.session.remove()
            for school_id,engine in schools:
                with app.test_request_context('/internal/snapshot-worker'):
                    g.institute_engine=engine
                    try:
                        control=db.session.get(Control,1)
                        if control and control.enabled:capture()
                    except OperationalError:db.session.rollback() # An old institute must be upgraded first.
                    except Exception:db.session.rollback();app.logger.exception('Daily snapshot worker failed for institute %s',school_id)
                    finally:db.session.remove();g.pop('institute_engine',None)
    @app.cli.command('snapshot-capture')
    @click.option('--code',required=True)
    def capture_cli(code):
        School=app.extensions['identity_models']['institute'];school=School.query.filter_by(code=code.strip().upper(),active=True).first()
        if not school:raise click.ClickException('Active institute not found.')
        engine=app.extensions['identity_helpers']['engine'](school.id)
        with app.test_request_context('/operator/snapshot-capture'):
            g.institute_engine=engine;db.session.remove()
            try:
                if not db.session.get(Control,1):db.session.add(Control(id=1,enabled=True))
                capture();click.echo('Current snapshot recorded.')
            finally:db.session.remove();g.pop('institute_engine',None)
    app.extensions['snapshot_helpers']=dict(capture=capture,tick_all=tick_all)
    app.register_blueprint(bp)
