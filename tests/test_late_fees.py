"""Explicit late-fee policies, saved rule snapshots and atomic assessments."""
import copy,html,os,re,unittest
from datetime import date
from unittest.mock import patch
os.environ['DATABASE_URL']='sqlite:///:memory:'
from app import app,db,Student
from late_fees import late_calculation

class LateFeeTests(unittest.TestCase):
    path='/workspace/core/fees/late-policy'
    def setUp(self):
        app.config.update(TESTING=True,IDENTITY_ENFORCE_IN_TESTS=False,SECRET_KEY='late-test')
        self.ctx=app.app_context();self.ctx.push();db.drop_all();db.create_all()
        self.rm=app.extensions['record_models'];self.ops=app.extensions['ops_models'];self.B=self.ops['bill'];self.Item=app.extensions['school_settings_models']['item'];self.Head=app.extensions['fee_setup_models']['head']
        for category,values in {'campus':['Campus A','Campus B'],'class_name':['One','Two']}.items():
            for value in values:db.session.add(self.rm['settings'](category=category,value=value,class_name=''))
        db.session.add(self.Head(key='Late Fee',label='Late Fee',timing='fine',months=[],custom=True))
        self.s=Student(admission_no='FINE-1',name='Fictional Fine Student',class_name='One',status='Active');db.session.add(self.s);db.session.flush();db.session.add(self.rm['student'](student_id=self.s.id,data={'campus':'Campus A'}))
        self.b=self.B(student_id=self.s.id,month='2026-10',due=date(2026,10,10),lines=[dict(particular='Tuition Fee',display_name='Saved Tuition',amount=200000)]);db.session.add(self.b);db.session.commit();self.bid=self.b.id
        self.c=app.test_client();self.c.get(self.path)
        with self.c.session_transaction() as sess:self.csrf=sess['record_csrf']
    def tearDown(self):db.session.remove();db.drop_all();self.ctx.pop()
    def policy_row(self,campus='',cls=''):return self.Item.query.filter_by(kind='late-fee-policy',scope=campus,name=cls).first()
    def policy(self,**changes):
        row=self.policy_row(changes.get('campus',''),changes.get('class_name',''))
        data=dict(_csrf=self.csrf,action='save',version=str(row.version if row else 0),campus='',class_name='',mode='daily',rate='10',grace='2',maximum='',head='Late Fee',accept_formula='1');data.update(changes)
        return self.c.post(self.path,data=data)
    def preview(self,**changes):
        data=dict(_csrf=self.csrf,action='preview',ids=str(self.bid),asof='2026-10-13');data.update(changes);return self.c.post(self.path+'/assess',data=data)
    def token(self,r):
        self.assertEqual(r.status_code,200,r.data[:400]);m=re.search(rb'name="preview_token" value="([^"]+)"',r.data);self.assertIsNotNone(m);return html.unescape(m[1].decode())
    def apply(self,token,**changes):
        data=dict(_csrf=self.csrf,action='apply',preview_token=token);data.update(changes);return self.c.post(self.path+'/assess',data=data)
    def fees(self):return [x for x in self.b.lines if x.get('kind')=='late_fee']
    def test_get_does_not_enable_policy_and_ids_are_unique(self):
        for query in ('','?campus=Campus+A','?campus=Campus+B'):
            r=self.c.get(self.path+query);self.assertEqual(r.status_code,200)
            ids=re.findall(rb'\bid="([^"]+)"',r.data);self.assertEqual(len(ids),len(set(ids)))
        self.assertEqual(self.Item.query.count(),0);self.assertEqual(self.ops['audit'].query.count(),0)
        preview=self.preview();self.assertIn(b'No enabled late-fee policy',preview.data);self.apply(self.token(preview));self.assertEqual(self.b.total,200000);self.assertFalse(self.fees())
    def test_formula_due_date_grace_boundaries_and_cap(self):
        config=dict(mode='daily',rate=1000,grace=2,maximum=2500)
        for at,days,total in [('2026-10-09',0,0),('2026-10-10',0,0),('2026-10-11',0,0),('2026-10-12',0,0),('2026-10-13',3,2500),('2026-10-14',4,2500),('2026-10-20',10,2500)]:
            result=late_calculation(config,date(2026,10,10),date.fromisoformat(at));self.assertEqual((result['days'],result['total']),(days,total))
        config.update(mode='fixed');self.assertEqual(late_calculation(config,date(2026,10,10),date(2026,10,20))['total'],1000)
        config.update(mode='none');self.assertEqual(late_calculation(config,date(2026,10,10),date(2026,10,20))['total'],0)
    def test_policy_validation_csrf_versions_scope_and_formula_acceptance(self):
        self.assertEqual(self.policy(_csrf='').status_code,400)
        for change in [dict(mode='percent'),dict(mode='double'),dict(mode='daily',accept_formula=''),dict(rate='NaN'),dict(rate='0'),dict(rate='-1'),dict(grace='1.5'),dict(grace='3661'),dict(maximum='-1'),dict(head='Tuition Fee'),dict(campus='Other'),dict(class_name='One'),dict(action='other')]:
            self.assertEqual(self.policy(**change).status_code,422,change);self.assertIsNone(self.policy_row())
        self.assertEqual(self.policy().status_code,302)
        self.assertEqual(self.policy(version='0').status_code,422);self.assertEqual(self.b.total,200000)
    def test_simulator_is_unsaved_and_handles_leap_dates_and_rounding(self):
        before=self.ops['audit'].query.count();r=self.policy(action='simulate',due='2024-02-28',asof='2024-03-01',grace='0',rate='10.005')
        self.assertEqual(r.status_code,200);self.assertIn(b'20.02',r.data);self.assertIsNone(self.policy_row());self.assertEqual(self.ops['audit'].query.count(),before);self.assertEqual(self.b.total,200000)
        for value in ('bad','2026-02-30','2026-1-01'):self.assertEqual(self.policy(action='simulate',due=value,asof='2026-10-13').status_code,422)
    def test_scope_priority_disabled_override_and_reset(self):
        self.policy(mode='fixed',rate='100');self.policy(campus='Campus B',mode='fixed',rate='200');self.policy(campus='Campus A',mode='none',accept_formula='')
        r=self.preview();self.assertIn(b'No enabled late-fee policy',r.data);self.apply(self.token(r));self.assertFalse(self.fees())
        self.policy(campus='Campus A',action='reset');self.assertIn(b'100.00',self.preview().data)
        d=self.rm['student'].query.one();d.data={'campus':'Campus B'};db.session.commit();self.assertIn(b'200.00',self.preview().data)
        self.policy(campus='Campus B',action='reset');self.policy(action='reset');self.assertIsNone(self.policy_row());self.assertFalse(self.fees())
    def test_apply_daily_delta_is_cumulative_capped_and_replay_safe(self):
        self.policy(maximum='45');original=copy.deepcopy(self.b.lines)
        token=self.token(self.preview());self.assertEqual(self.apply(token,amount='9999',ids='999',asof='2099-01-01').status_code,302)
        self.assertEqual(self.b.total,203000);self.assertEqual(self.b.lines[0],original[0]);self.assertEqual(self.fees()[0]['amount'],3000)
        self.assertEqual(self.apply(token).status_code,422)
        count=self.ops['audit'].query.filter_by(action='Apply reviewed late fees').count()
        self.assertEqual(self.apply(self.token(self.preview())).status_code,302);self.assertEqual(self.ops['audit'].query.filter_by(action='Apply reviewed late fees').count(),count)
        self.apply(self.token(self.preview(asof='2026-10-14')));self.assertEqual([x['amount'] for x in self.fees()],[3000,1000])
        self.apply(self.token(self.preview(asof='2026-10-20')));self.assertEqual([x['amount'] for x in self.fees()],[3000,1000,500]);self.assertEqual(self.b.total,204500)
        self.apply(self.token(self.preview(asof='2026-10-25')));self.assertEqual(len(self.fees()),3)
        self.apply(self.token(self.preview(asof='2026-10-12')));self.assertEqual(self.b.total,204500)
    def test_fixed_fine_is_charged_once(self):
        self.policy(mode='fixed',rate='100')
        self.apply(self.token(self.preview()));self.apply(self.token(self.preview(asof='2026-10-25')))
        self.assertEqual(len(self.fees()),1);self.assertEqual(self.b.total,210000)
    def test_saved_policy_due_and_display_label_survive_later_edits(self):
        self.policy();self.apply(self.token(self.preview()));first=copy.deepcopy(self.fees()[0])
        self.policy(mode='fixed',rate='999');head=db.session.get(self.Head,'Late Fee');head.label='Renamed Fine';head.timing='monthly';db.session.commit()
        self.b.due=date(2026,10,1);db.session.commit()
        self.apply(self.token(self.preview(asof='2026-10-14')))
        self.assertEqual(self.fees()[0],first);self.assertEqual(self.fees()[1]['display_name'],'Late Fee');self.assertEqual(self.fees()[1]['amount'],1000);self.assertEqual(self.fees()[1]['basis_due'],'2026-10-10')
    def test_new_assessment_detects_changed_head_and_referenced_head_cannot_delete(self):
        self.policy();head=db.session.get(self.Head,'Late Fee')
        response=self.c.post('/workspace/core/fees/heads',data=dict(_csrf=self.csrf,action='delete',key=head.key,version=str(head.version)))
        self.assertEqual(response.status_code,422)
        head.timing='manual';db.session.commit();self.assertEqual(self.preview().status_code,422);self.assertFalse(self.fees())
    def test_policy_and_payment_changes_make_entire_preview_stale(self):
        self.policy();token=self.token(self.preview());self.policy(rate='20');self.assertEqual(self.apply(token).status_code,422)
        token=self.token(self.preview());self.b.paid=10000;db.session.commit();self.assertEqual(self.apply(token).status_code,422);self.assertFalse(self.fees())
    def test_freeze_student_move_status_or_name_changes_invalidate_preview(self):
        self.policy()
        for key,value in [('frozen',True)]:
            token=self.token(self.preview());setattr(self.b,key,value);db.session.commit();self.assertEqual(self.apply(token).status_code,422);setattr(self.b,key,False);db.session.commit()
        for key,value in [('status','Inactive'),('name','Changed'),('class_name','Two')]:
            token=self.token(self.preview());old=getattr(self.s,key);setattr(self.s,key,value);db.session.commit();self.assertEqual(self.apply(token).status_code,422);setattr(self.s,key,old);db.session.commit()
        token=self.token(self.preview());d=self.rm['student'].query.one();d.data={'campus':'Campus B'};db.session.commit();self.assertEqual(self.apply(token).status_code,422);self.assertFalse(self.fees())
    def test_paid_discounted_frozen_inactive_and_zero_base_are_skipped(self):
        self.policy()
        for key,value in [('paid',1),('discount',1),('frozen',True)]:
            setattr(self.b,key,value);db.session.commit();r=self.preview();self.assertEqual(r.status_code,200);self.apply(self.token(r));self.assertFalse(self.fees());setattr(self.b,key,False if key=='frozen' else 0);db.session.commit()
        self.s.status='Inactive';db.session.commit();self.apply(self.token(self.preview()));self.assertFalse(self.fees())
        self.s.status='Active';self.b.lines=[];db.session.commit();self.apply(self.token(self.preview()));self.assertFalse(self.fees())
    def test_untracked_fine_row_requires_manual_review(self):
        self.policy();self.b.lines=[*self.b.lines,dict(particular='Late Fee',amount=500)];db.session.commit()
        r=self.preview();self.assertIn(b'untracked amount',r.data);self.apply(self.token(r));self.assertFalse(self.fees());self.assertEqual(self.b.total,200500)
    def test_future_assessment_is_simulation_only(self):
        self.policy();r=self.preview(asof='2099-01-01');self.assertIn(b'Future date: simulation only',r.data);self.assertEqual(self.apply(self.token(r)).status_code,422);self.assertFalse(self.fees())
    def test_tamper_expiry_session_and_selection_guards(self):
        from itsdangerous import URLSafeTimedSerializer
        self.policy();token=self.token(self.preview());self.assertEqual(self.apply(token+'bad').status_code,422)
        serializer=URLSafeTimedSerializer(app.config['SECRET_KEY'],salt='schoolflow-late-fee-v1');payload=serializer.loads(token)
        with patch('itsdangerous.timed.TimestampSigner.get_timestamp',return_value=1000):expired=serializer.dumps(payload)
        self.assertEqual(self.apply(expired).status_code,422)
        other=app.test_client();other.get(self.path)
        with other.session_transaction() as sess:csrf=sess['record_csrf']
        self.assertEqual(other.post(self.path+'/assess',data=dict(_csrf=csrf,action='apply',preview_token=token)).status_code,422)
        for changes in [dict(ids=[]),dict(ids=['1']*101),dict(ids='bad'),dict(ids='999'),dict(asof='bad'),dict(action='apply',preview_token=''),dict(action='save')]:self.assertEqual(self.preview(**changes).status_code,422)
        self.assertEqual(self.preview(_csrf='').status_code,400);self.assertFalse(self.fees())
    def test_missing_bill_rejects_batch_and_changed_one_leaves_others_unmodified(self):
        self.policy();second=self.B(student_id=self.s.id,month='2026-09',due=date(2026,9,10),lines=copy.deepcopy(self.b.lines));db.session.add(second);db.session.commit()
        self.assertEqual(self.preview(ids=[str(self.bid),'999']).status_code,422)
        token=self.token(self.preview(ids=[str(self.bid),str(second.id)]));second.frozen=True;db.session.commit()
        self.assertEqual(self.apply(token).status_code,422);self.assertFalse(self.fees());self.assertEqual(len(second.lines),1)
    def test_fee_action_selection_and_print_use_saved_fine_label(self):
        self.policy();response=self.c.post('/workspace/fee-action',data=dict(_csrf=self.csrf,action='fine',ids=str(self.bid)))
        self.assertEqual(response.status_code,200);self.assertIn(b'Calculate preview',response.data);self.assertFalse(self.fees())
        self.apply(self.token(self.preview()));head=db.session.get(self.Head,'Late Fee');head.label='Changed label';db.session.commit()
        page=self.c.post('/workspace/fee-action',data=dict(_csrf=self.csrf,action='branded',ids=str(self.bid)))
        self.assertEqual(page.status_code,200);self.assertIn(b'Late Fee',page.data);self.assertNotIn(b'Changed label',page.data);self.assertIn(b'2,030.00',page.data)
    def test_assessed_fine_cannot_lose_history_through_installment(self):
        self.policy();self.apply(self.token(self.preview()));before=copy.deepcopy(self.b.lines)
        response=self.c.post('/workspace/installment/'+str(self.bid),data=dict(_csrf=self.csrf,month='2026-11',due='2026-11-10',amount_0='100',amount_1='0'))
        self.assertEqual(response.status_code,422);self.assertEqual(self.b.lines,before);self.assertEqual(self.B.query.count(),1)
    def test_maximum_zero_and_overflow_simulation_are_explicit(self):
        self.policy(maximum='0');self.apply(self.token(self.preview()));self.assertFalse(self.fees())
        r=self.policy(action='simulate',due='1900-01-01',asof='9999-01-01',rate='999999999',maximum='');self.assertEqual(r.status_code,422)
        r=self.policy(action='simulate',due='1900-01-01',asof='9999-01-01',rate='999999999',maximum='100');self.assertEqual(r.status_code,200);self.assertIn(b'100.00',r.data)
    def test_audit_retains_before_rows_and_only_added_difference(self):
        self.policy();self.apply(self.token(self.preview()));self.apply(self.token(self.preview(asof='2026-10-14')))
        audits=self.ops['audit'].query.filter_by(action='Apply reviewed late fees').order_by(self.ops['audit'].id).all();self.assertEqual(len(audits),2)
        self.assertEqual(audits[0].data['changes'][0]['before'][0]['amount'],200000);self.assertEqual(audits[1].data['changes'][0]['added']['amount'],1000)
        self.assertEqual(len(audits[1].data['changes'][0]['before']),2)

    def test_concurrent_confirmation_applies_one_delta(self):
        import tempfile,threading
        from concurrent.futures import ThreadPoolExecutor
        from flask import g,request
        from sqlalchemy import create_engine,select
        with tempfile.TemporaryDirectory() as directory:
            engine=create_engine('sqlite:///'+directory+'/late.db',connect_args={'timeout':20})
            db.metadata.create_all(engine,tables=app.extensions['identity_helpers']['workspace_tables']())
            with app.test_request_context('/'):
                g.institute_engine=engine;db.session.remove()
                db.session.add(Student(id=1,admission_no='CONCURRENT-LATE',name='Fictional Concurrent',status='Active'));db.session.flush()
                db.session.add(self.Head(key='Late Fee',label='Late Fee',timing='fine',months=[],custom=True))
                db.session.add(self.Item(kind='late-fee-policy',scope='',name='',data=dict(mode='daily',rate=1000,grace=2,maximum=None,head='Late Fee',head_label='Late Fee')))
                db.session.add(self.B(id=1,student_id=1,month='2026-10',due=date(2026,10,10),lines=[dict(particular='Tuition Fee',amount=200000)]));db.session.commit();db.session.remove()
            barrier=threading.Barrier(2)
            def bind_test_database():
                if request.endpoint=='late_fees.assess':
                    g.institute_engine=engine
                    if request.form.get('action')=='apply':barrier.wait(timeout=10)
            app.before_request_funcs.setdefault(None,[]).append(bind_test_database)
            def client():
                c=app.test_client()
                with c.session_transaction() as sess:sess['record_csrf']='late-concurrent'
                return c
            try:
                preview=client().post(self.path+'/assess',data=dict(_csrf='late-concurrent',action='preview',ids='1',asof='2026-10-13'));token=self.token(preview)
                def apply(_):return client().post(self.path+'/assess',data=dict(_csrf='late-concurrent',action='apply',preview_token=token)).status_code
                with ThreadPoolExecutor(max_workers=2) as pool:statuses=list(pool.map(apply,range(2)))
                self.assertEqual(sorted(statuses),[302,422])
                with engine.connect() as connection:lines=connection.execute(select(self.B.__table__.c.lines).where(self.B.__table__.c.id==1)).scalar_one()
                self.assertEqual(len(lines),2);self.assertEqual(lines[1]['amount'],3000)
            finally:app.before_request_funcs[None].remove(bind_test_database);engine.dispose()

    def test_batch_queries_are_bounded_and_photos_are_never_loaded(self):
        from sqlalchemy import event
        self.policy()
        bills=[self.b]
        for i in range(24):
            student=Student(admission_no='BATCH-'+str(i),name='Batch '+str(i),class_name='One',status='Active');db.session.add(student);db.session.flush()
            db.session.add(self.rm['student'](student_id=student.id,data={'campus':'Campus A'}))
            b=self.B(student_id=student.id,month='2026-10',due=date(2026,10,10),lines=[dict(particular='Tuition Fee',amount=200000)]);db.session.add(b);bills.append(b)
        db.session.commit();ids=[str(b.id) for b in bills];queries=[]
        def tally(conn,cursor,statement,parameters,context,executemany):
            if statement.lstrip().lower().startswith('select'):queries.append(statement.lower())
        db.session.remove();event.listen(db.engine,'before_cursor_execute',tally)
        try:preview=self.preview(ids=ids)
        finally:event.remove(db.engine,'before_cursor_execute',tally)
        self.token(preview);self.assertLessEqual(len(queries),12,queries);self.assertFalse(any('record_file' in q for q in queries))

    def test_configuration_has_only_the_nine_implemented_entries_and_nested_fee_tools(self):
        page=self.c.get('/workspace/dashboard').data
        menu=page.split(b'<div class="workspace-utility"',1)[1].split(b'<div class="brand-row"',1)[0]
        keys=re.findall(rb'data-core-key="([^"]+)"',menu)
        self.assertEqual(keys,[x.encode() for x in ['institute','exam','hrm','roll-series','late-automation','yearly-increment','users','certificates','user-logging']])
        self.assertNotIn(b'>Fee Settings</a>',menu);self.assertNotIn(b'>Challan Branding</a>',menu)
        self.assertNotIn(b'aria-disabled="true"',menu);self.assertIn(b'Late Fee Automation',menu);self.assertNotIn(b'Subscription',menu)
        setup=self.c.get('/workspace/core/institute').data
        for path in (b'/workspace/core/fees/heads',b'/workspace/core/fees/schedules',b'/workspace/core/fees/challan-branding'):self.assertIn(path,setup)

    def test_double_expiry_boundaries_split_days_and_caps(self):
        config=dict(mode='fixed_double',rate=20000,grace=0,maximum=None,expiry=10)
        for days,total in [(0,0),(1,20000),(10,20000),(11,40000)]:
            from datetime import timedelta
            self.assertEqual(late_calculation(config,date(2026,10,1),date(2026,10,1)+timedelta(days=days))['total'],total)
        config.update(mode='daily_double',rate=1000)
        self.assertEqual(late_calculation(config,date(2026,10,1),date(2026,10,31))['total'],50000)
        config['maximum']=42000;self.assertEqual(late_calculation(config,date(2026,10,1),date(2026,10,31))['total'],42000)
        config['maximum']=0;self.assertEqual(late_calculation(config,date(2026,10,1),date(2026,10,31))['total'],0)

    def test_percentage_and_concession_formulas_use_named_bases(self):
        basis=dict(actual=500000,decided=350000,owing=400000)
        config=dict(mode='percent_actual',rate=500,grace=0,maximum=None)
        for mode,total in [('percent_actual',25000),('percent_decided',17500),('percent_owing',20000),('revoke_discount',150000)]:
            config['mode']=mode;self.assertEqual(late_calculation(config,date(2026,10,10),date(2026,10,11),basis)['total'],total)
        config.update(mode='percent_actual',rate=333);self.assertEqual(late_calculation(config,date(2026,10,10),date(2026,10,11),dict(actual=10001))['total'],333)
        with self.assertRaises(ValueError):late_calculation(config,date(2026,10,10),date(2026,10,11))

    def test_new_policy_validation_and_unsaved_percentage_simulator(self):
        for changes in [dict(mode='fixed_double'),dict(mode='daily_double',expiry='0'),dict(mode='daily_double',expiry='3661'),dict(mode='percent_actual',rate='100.01')]:
            self.assertEqual(self.policy(**changes).status_code,422)
        result=self.policy(action='simulate',mode='percent_actual',rate='5',grace='0',due='2026-10-10',asof='2026-10-11',basis_actual='5000',basis_decided='3500',basis_owing='3500')
        self.assertEqual(result.status_code,200);self.assertIn(b'250.00',result.data);self.assertIsNone(self.policy_row())
        self.assertEqual(self.policy(mode='revoke_discount',rate='').status_code,302)

    def test_saved_tuition_basis_and_no_fine_on_fine(self):
        self.b.lines=[dict(particular='Tuition Fee',amount=350000,actual=500000,plan_discount=150000)];db.session.commit()
        self.assertEqual(self.policy(mode='revoke_discount',rate='').status_code,302)
        self.assertEqual(self.apply(self.token(self.preview())).status_code,302)
        fee=self.fees()[0];self.assertEqual(fee['amount'],150000);self.assertEqual(fee['basis_values']['actual'],500000)
        self.apply(self.token(self.preview(asof='2026-10-25')));self.assertEqual(len(self.fees()),1)
        # A saved percentage basis never includes an earlier late fee.
        self.b.lines=[dict(particular='Tuition Fee',amount=350000,actual=500000,plan_discount=150000)];db.session.commit()
        self.policy(mode='percent_owing',rate='5');self.apply(self.token(self.preview()))
        self.assertEqual(self.fees()[0]['amount'],17500)
        self.apply(self.token(self.preview(asof='2026-10-25')));self.assertEqual(len(self.fees()),1)

    def test_legacy_tuition_without_actual_discount_evidence_is_not_guessed(self):
        self.policy(mode='percent_actual',rate='5')
        self.assertEqual(self.preview().status_code,422);self.assertEqual(self.fees(),[])
