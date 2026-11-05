"""Calendar scheduling, signed enablement and durable automatic assessment claims."""
import copy,html,os,re,unittest
from datetime import date,datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo
os.environ['DATABASE_URL']='sqlite:///:memory:'
from app import app,db,Student
from fine_automation import first_run_day


class FineAutomationTests(unittest.TestCase):
    path='/workspace/core/fees/automation'
    now=datetime(2026,10,12,10,0,tzinfo=ZoneInfo('Asia/Karachi'))
    def setUp(self):
        app.config.update(TESTING=True,IDENTITY_ENFORCE_IN_TESTS=False,SECRET_KEY='automation-test',FINE_WORKER_ENABLED=False)
        self.ctx=app.app_context();self.ctx.push();db.drop_all();db.create_all()
        self.ops=app.extensions['ops_models'];self.rm=app.extensions['record_models'];self.Item=app.extensions['school_settings_models']['item'];self.Head=app.extensions['fee_setup_models']['head'];self.Run=app.extensions['fine_automation_run_model'];self.Charge=app.extensions['fine_charge_model'];self.helper=app.extensions['fine_automation_helpers']
        db.session.add(self.rm['settings'](category='campus',value='Campus A',class_name=''));db.session.add(self.Head(key='Late Fine',label='Late Fine',timing='fine',months=[],custom=True))
        self.policy=self.Item(kind='late-fee-policy',scope='Campus A',name='',data=dict(mode='daily',rate=1000,grace=0,maximum=None,head='Late Fine',head_label='Late Fine'))
        self.s=Student(admission_no='AUTO-1',name='Fictional auto pupil',status='Active',class_name='One');db.session.add_all([self.policy,self.s]);db.session.flush();self.sid=self.s.id
        db.session.add(self.rm['student'](student_id=self.sid,data={'campus':'Campus A'}));self.bill=self.ops['bill'](student_id=self.sid,month='2026-10',due=date(2026,10,11),lines=[dict(particular='Tuition Fee',amount=100000)]);db.session.add(self.bill);db.session.commit()
        self.clock=patch('fine_automation.local_now',return_value=self.now);self.clock.start();self.c=app.test_client();self.c.get(self.path)
        with self.c.session_transaction() as sess:self.csrf=sess['record_csrf']
    def tearDown(self):self.clock.stop();db.session.remove();db.drop_all();self.ctx.pop()
    def row(self):return self.Item.query.filter_by(kind='late-fee-automation').first()
    def form(self,**changes):
        row=self.row();data=dict(_csrf=self.csrf,campus='Campus A',version=str(row.version if row else 0),enabled='1',delay='1',time='00:05',defer='1',off_days=['6'],holidays='');data.update(changes);return data
    def post(self,action,**changes):return self.c.post(self.path,data={**self.form(**changes),'action':action})
    def token(self,response):
        self.assertEqual(response.status_code,200,response.data[:300]);match=re.search(rb'name="preview_token" value="([^"]+)"',response.data);self.assertIsNotNone(match);return html.unescape(match[1].decode())
    def enable(self,**changes):
        data=self.form(**changes);token=self.token(self.c.post(self.path,data={**data,'action':'preview'}));response=self.c.post(self.path,data={**data,'action':'save','preview_token':token});self.assertEqual(response.status_code,302,response.data[:300]);return self.row()
    def tick(self,day=12):
        now=self.now.replace(day=day)
        with app.test_request_context('/'):
            result=self.helper['execute'](self.row(),now)
        return result
    def test_calendar_boundaries_grace_weekends_holidays_and_no_assumed_off(self):
        cfg=dict(delay=0,defer=True,off_days=[6],holidays=['2026-10-12'])
        self.assertEqual(first_run_day(date(2026,10,10),dict(grace=0),cfg),date(2026,10,13))
        cfg['defer']=False;self.assertEqual(first_run_day(date(2026,10,10),dict(grace=0),cfg),date(2026,10,11))
        cfg.update(delay=1,defer=True,off_days=[],holidays=[]);self.assertEqual(first_run_day(date(2026,10,10),dict(grace=2),cfg),date(2026,10,13))
    def test_pages_and_preview_do_not_create_schedule_or_charge(self):
        for path in [self.path,self.path+'?campus=Campus+A']:
            response=self.c.get(path);self.assertEqual(response.status_code,200);ids=re.findall(rb'\bid="([^"]+)"',response.data);self.assertEqual(len(ids),len(set(ids)))
        page=self.post('preview');self.token(page);self.assertIn(b'10.00',page.data);self.assertIsNone(self.row());self.assertEqual(self.bill.total,100000);self.assertEqual(self.Run.query.count(),0)
    def test_enable_requires_exact_fresh_preview_and_active_nonzero_policy(self):
        self.assertEqual(self.post('save').status_code,422)
        token=self.token(self.post('preview'));self.assertEqual(self.post('save',preview_token=token,delay='2').status_code,422)
        self.policy.data={**self.policy.data,'rate':2000};db.session.commit();self.assertEqual(self.post('save',preview_token=token).status_code,422)
        self.policy.data={**self.policy.data,'maximum':0};db.session.commit();self.assertEqual(self.post('save',preview_token=self.token(self.post('preview'))).status_code,422)
        self.assertIsNone(self.row());self.assertEqual(self.bill.total,100000)
    def test_disable_saves_without_preview_but_enable_does_not_charge_itself(self):
        self.assertEqual(self.post('save',enabled='').status_code,302);self.assertFalse(self.row().data['enabled']);self.assertEqual(self.tick()['applied'],0)
        self.enable();self.assertEqual(self.bill.total,100000);self.assertEqual(self.Run.query.count(),0)
    def test_invalid_calendar_time_scope_and_csrf(self):
        self.assertEqual(self.post('save',_csrf='').status_code,400)
        for changes in [dict(campus='Other'),dict(delay='-1'),dict(delay='3661'),dict(time='25:00'),dict(off_days=[str(i) for i in range(7)]),dict(holidays='2026-02-30'),dict(holidays='2026-1-01')]:
            self.assertEqual(self.post('preview',**changes).status_code,422,changes)
    def test_automatic_daily_differences_are_claimed_once_and_stop_after_payment(self):
        self.enable();self.assertEqual(self.tick()['applied'],1);self.assertEqual(self.bill.total,101000)
        self.assertEqual(self.tick()['applied'],0);self.assertEqual(self.bill.total,101000)
        self.assertEqual(self.tick(13)['total'],1000);self.assertEqual(self.bill.total,102000);self.assertEqual(self.Run.query.filter_by(status='Applied').count(),2)
        self.bill.paid=1;db.session.commit();self.assertEqual(self.tick(14)['applied'],0);self.assertEqual(self.bill.total,102000)
    def test_closed_days_defer_then_accumulate_without_first_enable_backfill(self):
        self.enable(holidays='2026-10-12');self.assertEqual(self.tick()['applied'],0);self.assertEqual(self.Run.query.one().status,'Deferred')
        self.assertEqual(self.tick(13)['total'],2000);self.assertEqual(self.bill.total,102000)
        old=self.ops['bill'](student_id=self.sid,month='2026-09',due=date(2026,9,1),lines=[dict(particular='Tuition Fee',amount=100000)]);db.session.add(old);db.session.commit();self.tick(14);self.assertEqual(old.total,100000)
    def test_manual_assessment_or_changed_fine_stops_automation(self):
        self.enable();self.bill.lines=[*self.bill.lines,dict(particular='Late Fine',amount=100,kind='late_fee',origin_bill_id=self.bill.id,policy=self.policy.data,basis_due='2026-10-11')];db.session.commit()
        self.assertEqual(self.tick()['applied'],0)
        self.bill.lines=[dict(particular='Tuition Fee',amount=100000)];db.session.commit();self.tick()
        lines=copy.deepcopy(self.bill.lines);lines[-1]['amount']=200;self.bill.lines=lines;db.session.commit()
        self.assertEqual(self.tick(13)['applied'],0)
    def test_forwarded_automatic_fine_posts_later_without_stopping_accrual(self):
        self.policy.data={**self.policy.data,'next_challan':True};db.session.commit();self.enable();self.tick();self.assertEqual(self.bill.total,100000)
        charge=self.Charge.query.one();self.assertEqual(charge.amount,1000)
        target=self.ops['bill'](student_id=self.sid,month='2026-11',due=date(2026,11,10),lines=[dict(particular='Tuition Fee',amount=100000)]);db.session.add(target);db.session.commit()
        with app.test_request_context('/'):app.extensions['fine_queue_helpers']['post'](charge,target);db.session.commit()
        self.assertEqual(self.tick(13)['total'],1000);self.assertEqual(self.bill.total,100000);self.assertEqual(target.total,101000)
        self.assertEqual(self.Charge.query.count(),2)
    def test_cancelled_auto_queue_stops_further_automatic_recreation(self):
        self.policy.data={**self.policy.data,'next_challan':True};db.session.commit();self.enable();self.tick();db.session.delete(self.Charge.query.one());db.session.commit()
        self.assertEqual(self.tick(13)['applied'],0);self.assertEqual(self.Charge.query.count(),0)
    def test_run_now_requires_saved_enabled_settings_and_new_review(self):
        self.enable();self.assertEqual(self.post('run').status_code,422)
        self.assertEqual(self.post('run',preview_token=self.token(self.post('preview'))).status_code,302);self.assertEqual(self.bill.total,101000)
        run=self.Run.query.one();self.assertEqual(run.data['mode'],'manual')
    def test_disabled_schedule_never_runs_and_saved_policy_change_keeps_prior_basis(self):
        self.enable();self.tick();self.policy.data={**self.policy.data,'rate':90000};db.session.commit()
        self.assertEqual(self.tick(13)['total'],1000)
        self.assertEqual(self.post('save',enabled='').status_code,302);self.assertEqual(self.tick(14)['applied'],0)
    def test_preview_rejects_cross_session_and_changed_challan(self):
        token=self.token(self.post('preview'));other=app.test_client();other.get(self.path)
        with other.session_transaction() as sess:csrf=sess['record_csrf']
        self.assertEqual(other.post(self.path,data={**self.form(),'_csrf':csrf,'action':'save','preview_token':token}).status_code,422)
        self.bill.due=date(2026,10,10);db.session.commit();self.assertEqual(self.post('save',preview_token=token).status_code,422)

    def test_concurrent_manual_runs_claim_one_bill_day(self):
        import tempfile,threading
        from concurrent.futures import ThreadPoolExecutor
        from flask import g,request
        from sqlalchemy import create_engine,select
        self.enable();db.session.remove()
        with tempfile.TemporaryDirectory() as directory:
            engine=create_engine('sqlite:///'+directory+'/automation.db',connect_args={'timeout':20});tables=app.extensions['identity_helpers']['workspace_tables']();db.metadata.create_all(engine,tables=tables)
            with db.engine.connect() as source,engine.begin() as target:
                for table in tables:
                    rows=[dict(row) for row in source.execute(select(table)).mappings().all()]
                    if rows:target.execute(table.insert(),rows)
            barrier=threading.Barrier(2)
            def bind():
                if request.endpoint=='fine_automation.index':
                    g.institute_engine=engine
                    if request.form.get('action')=='run':barrier.wait(timeout=10)
            app.before_request_funcs.setdefault(None,[]).append(bind)
            def client():
                c=app.test_client()
                with c.session_transaction() as sess:sess['record_csrf']='concurrent-auto'
                return c
            data=dict(_csrf='concurrent-auto',campus='Campus A',version='1',enabled='1',delay='1',time='00:05',defer='1',off_days=['6'],holidays='')
            try:
                token=self.token(client().post(self.path,data={**data,'action':'preview'}))
                def run(_):return client().post(self.path,data={**data,'action':'run','preview_token':token}).status_code
                with ThreadPoolExecutor(max_workers=2) as pool:statuses=list(pool.map(run,range(2)))
                self.assertEqual(sorted(statuses),[302,422])
                with engine.connect() as connection:
                    runs=connection.execute(select(self.Run.__table__.c.amount)).scalars().all();lines=connection.execute(select(self.ops['bill'].__table__.c.lines)).scalar_one()
                self.assertEqual(runs,[1000]);self.assertEqual(len(lines),2)
            finally:app.before_request_funcs[None].remove(bind);db.session.remove();g.pop('institute_engine',None);engine.dispose()

    def holiday(self,**changes):
        form=dict(_csrf=self.csrf,action='save',version='0',name='Fictional closure',date='2026-10-12',campus='Campus A',notes='Test only');form.update(changes)
        return self.c.post('/workspace/core/holidays',data=form)
    def test_holiday_calendar_crud_restore_and_read_only_export(self):
        import io
        from openpyxl import load_workbook
        self.assertEqual(self.c.get('/workspace/core/holidays').status_code,200);self.assertEqual(self.Item.query.filter_by(kind='calendar-holiday').count(),0)
        self.assertEqual(self.holiday().status_code,302);row=self.Item.query.filter_by(kind='calendar-holiday').one()
        self.assertEqual(self.holiday(id=str(row.id),version='0',name='Stale').status_code,422)
        self.assertEqual(self.holiday(id=str(row.id),version='1',name='Updated closure',repeats='1').status_code,302)
        response=self.c.get('/workspace/core/holidays?campus=Campus+A&q=updated&export=xlsx');self.assertEqual(response.status_code,200);self.assertEqual(list(load_workbook(io.BytesIO(response.data)).active.values)[1][0],'Updated closure')
        self.assertEqual(self.c.post('/workspace/core/holidays',data=dict(_csrf=self.csrf,action='restore')).status_code,302)
        self.assertEqual(self.c.post('/workspace/core/holidays',data=dict(_csrf=self.csrf,action='restore')).status_code,302);self.assertEqual(self.Item.query.filter_by(kind='calendar-holiday').count(),7)
        self.assertEqual(self.c.post('/workspace/core/holidays',data=dict(_csrf=self.csrf,action='delete',id=str(row.id),version=str(row.version))).status_code,302)
        self.assertEqual(self.bill.total,100000);self.assertEqual(self.Run.query.count(),0)
    def test_calendar_scope_repeat_and_edit_invalidates_automation_preview(self):
        self.assertEqual(self.holiday(date='2020-10-12',repeats='1',campus='').status_code,302)
        row=self.enable();result=self.tick();self.assertEqual(result['applied'],0);self.assertIn('holiday',result['reason'])
        holiday=self.Item.query.filter_by(kind='calendar-holiday').one();holiday.scope='Other campus';db.session.commit()
        self.assertEqual(self.tick()['applied'],1)
        token=self.token(self.post('preview'));holiday.data={**holiday.data,'notes':'Changed calendar'};holiday.scope='Campus A';db.session.commit()
        self.assertEqual(self.post('run',preview_token=token).status_code,422)
    def test_weekly_and_holiday_deferral_are_independent_and_notice_is_only_queued(self):
        self.holiday();self.enable(calendar_controls='1',defer_weekly='1',defer_holidays='',notify='1')
        self.assertEqual(self.tick()['applied'],1);message=self.ops['workflow'].query.filter_by(kind='message').one();self.assertEqual(message.status,'Provider not configured');self.assertEqual(message.data['audience'],'owner')
        self.assertEqual(self.tick()['applied'],0);self.assertEqual(self.ops['workflow'].query.filter_by(kind='message').count(),1)
    def test_invalid_holidays_and_foreign_item_ids_do_not_change_settings(self):
        for changes in [dict(date='2026-02-30'),dict(campus='Unknown'),dict(name='')]:self.assertEqual(self.holiday(**changes).status_code,422)
        self.assertEqual(self.holiday(id=str(self.policy.id),version='1').status_code,404)
        self.assertEqual(self.Item.query.filter_by(kind='calendar-holiday').count(),0)
        self.assertEqual(self.c.post('/workspace/core/holidays',data=dict(action='restore')).status_code,400)
