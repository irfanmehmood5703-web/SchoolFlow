"""Attendance evidence, immutable fine liabilities and reviewed later-bill posting."""
import copy,html,os,re,unittest
from datetime import date
os.environ['DATABASE_URL']='sqlite:///:memory:'
from app import app,db,Student
from attendance_fines import attendance_calculation


class AttendanceFineTests(unittest.TestCase):
    path='/workspace/core/fees/attendance-fines'
    queue='/workspace/core/fees/pending-fines'
    def setUp(self):
        app.config.update(TESTING=True,IDENTITY_ENFORCE_IN_TESTS=False,SECRET_KEY='attendance-fine-test')
        self.ctx=app.app_context();self.ctx.push();db.drop_all();db.create_all()
        self.ops=app.extensions['ops_models'];self.rm=app.extensions['record_models'];self.Item=app.extensions['school_settings_models']['item'];self.Head=app.extensions['fee_setup_models']['head'];self.Charge=app.extensions['fine_charge_model'];self.Bill=self.ops['bill'];self.Daily=self.ops['daily']
        for category,values in {'campus':['Campus A','Campus B'],'class_name':['One']}.items():
            for value in values:db.session.add(self.rm['settings'](category=category,value=value,class_name=''))
        db.session.add_all([self.Head(key='Attendance Fine',label='Attendance Fine',timing='fine',months=[],custom=True),self.Head(key='Tuition Fee',label='Tuition',timing='monthly',months=[],custom=False)])
        self.s=Student(admission_no='ATT-1',name='Fictional attendance pupil',class_name='One',status='Active');db.session.add(self.s);db.session.flush()
        self.detail=self.rm['student'](student_id=self.s.id,data=dict(campus='Campus A',admission_date='2026-09-03'));db.session.add(self.detail)
        for day,status in [(1,'Absent'),(3,'Absent'),(4,'Absent'),(5,'Absent'),(6,'Late'),(7,'Late'),(8,'Late'),(9,'Leave'),(10,'Short Leave'),(11,'Short Leave'),(12,'Off Day'),(13,'Sandwich Leave')]:
            db.session.add(self.Daily(kind='student',person_id=self.s.id,day=date(2026,9,day),status=status))
        db.session.commit();self.c=app.test_client();self.c.get(self.path)
        with self.c.session_transaction() as sess:self.csrf=sess['record_csrf']
    def tearDown(self):db.session.remove();db.drop_all();self.ctx.pop()
    def policy(self,**changes):
        row=self.Item.query.filter_by(kind='attendance-fine-policy',scope=changes.get('campus',''),name='').first()
        data=dict(_csrf=self.csrf,action='save',version=str(row.version if row else 0),head='Attendance Fine',campus='')
        for i,(free,rate) in enumerate([(1,'50'),(2,'10'),(0,'25'),(1,'5')]):data.update({'enabled_'+str(i):'1','free_'+str(i):str(free),'rate_'+str(i):rate})
        data.update(changes);return self.c.post(self.path,data=data)
    def preview(self,**changes):
        data=dict(_csrf=self.csrf,action='preview',month='2026-09',student_ids=changes.pop('student_ids') if 'student_ids' in changes else str(self.s.id));data.update(changes);return self.c.post(self.path+'/assess',data=data)
    def token(self,response):
        self.assertEqual(response.status_code,200,response.data[:300]);match=re.search(rb'name="preview_token" value="([^"]+)"',response.data);self.assertIsNotNone(match);return html.unescape(match[1].decode())
    def apply(self,token):return self.c.post(self.path+'/assess',data=dict(_csrf=self.csrf,action='apply',preview_token=token))
    def assess(self):
        self.assertEqual(self.policy().status_code,302);self.assertEqual(self.apply(self.token(self.preview())).status_code,302);return self.Charge.query.one()
    def bill(self,month='2026-10',**changes):
        data=dict(student_id=self.s.id,month=month,due=date.fromisoformat(month+'-10'),lines=[dict(particular='Tuition Fee',amount=100000)]);data.update(changes);b=self.Bill(**data);db.session.add(b);db.session.commit();return b
    def posting_preview(self,charge,bill,client=None,csrf=None):return (client or self.c).post(self.queue,data={'_csrf':csrf or self.csrf,'action':'preview','ids':str(charge.id),'bill_'+str(charge.id):str(bill.id)})
    def posting_apply(self,token):return self.c.post(self.queue,data=dict(_csrf=self.csrf,action='apply',preview_token=token))
    def plan(self):
        P=app.extensions['student_fee_plan_model'];p=P(student_id=self.s.id,effective='2026-09',data=dict(name='Fictional plan',due_day=10,lines=[dict(particular='Tuition Fee',actual=100000,discount=0,arrears=0,net=100000)]));db.session.add(p);db.session.commit();return p
    def generation(self,token='',month='2026-10',**extra):
        return self.c.post('/workspace/student-fee-plans/generate',data=dict(_csrf=self.csrf,month=month,timing_mode='auto',student_ids=str(self.s.id),include_pending_fines='1' if token else '',fine_review_token=token,**extra))
    def generation_token(self):
        page=self.c.get('/workspace/student-fee-plans/generate');self.assertEqual(page.status_code,200)
        return html.unescape(re.search(rb'name="fine_review_token" value="([^"]+)"',page.data)[1].decode())

    def test_readonly_pages_do_not_create_policies_or_charges(self):
        for path in [self.path,self.path+'?campus=Campus+A',self.path+'/assess',self.queue]:
            page=self.c.get(path);self.assertEqual(page.status_code,200,path);ids=re.findall(rb'\bid="([^"]+)"',page.data);self.assertEqual(len(ids),len(set(ids)))
        self.assertEqual(self.Item.query.count(),0);self.assertEqual(self.Charge.query.count(),0)
    def test_monthly_free_counts_money_rounding_and_disabled_status(self):
        rule={'Absent':dict(enabled=True,free=2,rate=1001),'Late':dict(enabled=False,free=0,rate=900000)}
        self.assertEqual(attendance_calculation(rule,dict(Absent=2,Late=20))['total'],0)
        self.assertEqual(attendance_calculation(rule,dict(Absent=3))['total'],1001)
        with self.assertRaises(ValueError):attendance_calculation({'Absent':dict(enabled=True,free=0,rate=99999999900)},dict(Absent=31))
    def test_policy_csrf_scope_version_validation_and_simulator_no_writes(self):
        self.assertEqual(self.policy(_csrf='').status_code,400)
        for changes in [dict(campus='Other'),dict(free_0='-1'),dict(free_0='32'),dict(rate_0='NaN'),dict(rate_0='-1'),dict(head='Tuition Fee'),dict(action='bad')]:
            self.assertEqual(self.policy(**changes).status_code,422,changes);self.assertEqual(self.Item.query.count(),0)
        result=self.policy(action='simulate',count_0='3',count_1='3',count_2='1',count_3='2');self.assertEqual(result.status_code,200);self.assertIn(b'140.00',result.data);self.assertEqual(self.Item.query.count(),0)
        self.assertEqual(self.policy(action='simulate',count_0='31',count_1='1').status_code,422)
        self.assertEqual(self.policy().status_code,302);self.assertEqual(self.policy(version='0').status_code,422);self.assertEqual(self.Charge.query.count(),0)
    def test_counts_saved_days_since_admission_no_inferred_absences_or_sandwich(self):
        charge=self.assess();self.assertEqual(charge.amount,14000);self.assertEqual(charge.target_month,'2026-10');self.assertIsNone(charge.bill_id)
        self.assertEqual(charge.data['line']['counts'],dict(Absent=3,Late=3,Leave=1,**{'Short Leave':2}));self.assertFalse(charge.data['line']['policy']['sandwich_leave'])
        self.assertEqual(self.Bill.query.count(),0)
        self.assertEqual(self.apply(self.token(self.preview())).status_code,302);self.assertEqual(self.Charge.query.count(),1)
    def test_policy_campus_override_disabled_and_reset_fallback(self):
        self.policy();self.policy(campus='Campus A',enabled_0='',enabled_1='',enabled_2='',enabled_3='')
        self.assertIn(b'No enabled policy',self.preview().data);self.apply(self.token(self.preview()));self.assertEqual(self.Charge.query.count(),0)
        self.assertEqual(self.policy(campus='Campus A',action='reset').status_code,302);self.apply(self.token(self.preview()));self.assertEqual(self.Charge.query.one().amount,14000)
    def test_attendance_policy_and_student_changes_invalidate_review(self):
        self.policy();token=self.token(self.preview());row=self.Daily.query.filter_by(status='Late').first();row.status='Present';db.session.commit()
        self.assertEqual(self.apply(token).status_code,422);self.assertEqual(self.Charge.query.count(),0)
        token=self.token(self.preview());self.policy(rate_0='100');self.assertEqual(self.apply(token).status_code,422)
        token=self.token(self.preview());self.s.status='Left';db.session.commit();self.assertEqual(self.apply(token).status_code,422)
    def test_replay_cross_session_and_future_month_cannot_charge(self):
        self.policy();token=self.token(self.preview());other=app.test_client();other.get(self.path)
        with other.session_transaction() as sess:csrf=sess['record_csrf']
        self.assertEqual(other.post(self.path+'/assess',data=dict(_csrf=csrf,action='apply',preview_token=token)).status_code,422)
        self.assertEqual(self.apply(token+'x').status_code,422);self.assertEqual(self.apply(token).status_code,302);self.assertEqual(self.apply(token).status_code,422)
        future=self.token(self.preview(month='2099-01'));self.assertEqual(self.apply(future).status_code,422)
    def test_post_review_retains_frozen_policy_label_and_applies_once(self):
        charge=self.assess();saved=copy.deepcopy(charge.data);self.policy(rate_0='999');head=db.session.get(self.Head,'Attendance Fine');head.label='Renamed';db.session.commit()
        bill=self.bill();token=self.token(self.posting_preview(charge,bill));self.assertEqual(self.posting_apply(token).status_code,302)
        self.assertEqual(bill.total,114000);self.assertEqual(charge.bill_id,bill.id);self.assertEqual(charge.data,saved);self.assertEqual(bill.lines[-1]['display_name'],'Attendance Fine')
        self.assertEqual(self.posting_apply(token).status_code,422);self.assertEqual(bill.total,114000)
    def test_post_rejects_wrong_child_early_paid_frozen_and_stale_bill(self):
        charge=self.assess();early=self.bill('2026-09');self.assertEqual(self.posting_preview(charge,early).status_code,422)
        wrong=Student(admission_no='OTHER',name='Other pupil',status='Active');db.session.add(wrong);db.session.commit();bill=self.bill(student_id=wrong.id);self.assertEqual(self.posting_preview(charge,bill).status_code,422)
        bill=self.bill()
        for attr,val in [('paid',1),('discount',1),('frozen',True)]:
            setattr(bill,attr,val);db.session.commit();self.assertEqual(self.posting_preview(charge,bill).status_code,422);setattr(bill,attr,False if attr=='frozen' else 0);db.session.commit()
        token=self.token(self.posting_preview(charge,bill));bill.paid=1;db.session.commit();self.assertEqual(self.posting_apply(token).status_code,422);self.assertIsNone(charge.bill_id)
    def test_generator_explicit_opt_in_target_month_and_stale_queue_atomic(self):
        charge=self.assess();self.plan();token=self.generation_token()
        self.assertEqual(self.generation(token,month='2026-09').status_code,302);self.assertIsNone(charge.bill_id)
        charge.data={**charge.data,'review_note':'Changed'};db.session.commit();self.assertEqual(self.generation(token).status_code,422);self.assertEqual(self.Bill.query.filter_by(month='2026-10').count(),0)
        token=self.generation_token();self.assertEqual(self.generation(token).status_code,302);bill=self.Bill.query.filter_by(month='2026-10').one();self.assertEqual(bill.total,114000);self.assertEqual(charge.bill_id,bill.id)
        self.assertEqual(self.generation(token).status_code,302);self.assertEqual(bill.total,114000)
    def test_generator_without_fine_selection_preserves_pending_and_existing_bill(self):
        charge=self.assess();self.plan();self.assertEqual(self.generation().status_code,302);self.assertIsNone(charge.bill_id);bill=self.Bill.query.one();self.assertEqual(bill.total,100000)
        self.assertEqual(self.posting_apply(self.token(self.posting_preview(charge,bill))).status_code,302);self.assertEqual(bill.total,114000)
    def test_posted_challan_and_used_head_cannot_discard_fine_liability(self):
        charge=self.assess();bill=self.bill();self.posting_apply(self.token(self.posting_preview(charge,bill)))
        response=self.c.post('/workspace/fee-action',data=dict(_csrf=self.csrf,action='delete',ids=str(bill.id),confirm='yes'));self.assertEqual(response.status_code,422);self.assertIsNotNone(db.session.get(self.Bill,bill.id))
        self.assertEqual(self.c.post('/workspace/installment/'+str(bill.id),data=dict(_csrf=self.csrf)).status_code,422)
        head=db.session.get(self.Head,'Attendance Fine');self.assertEqual(self.c.post('/workspace/core/fees/heads',data=dict(_csrf=self.csrf,action='delete',key=head.key,version=str(head.version))).status_code,422)
    def test_late_fine_forwarding_retains_original_bill_and_cumulative_delta(self):
        self.Item.query.delete();db.session.add(self.Item(kind='late-fee-policy',scope='',name='',data=dict(mode='daily',rate=1000,grace=0,maximum=None,head='Attendance Fine',head_label='Late fee saved',next_challan=True)));db.session.commit()
        bill=self.bill('2026-09');old=copy.deepcopy(bill.lines);path='/workspace/core/fees/late-policy/assess'
        def preview(asof):return self.c.post(path,data=dict(_csrf=self.csrf,action='preview',ids=str(bill.id),asof=asof))
        def apply(token):return self.c.post(path,data=dict(_csrf=self.csrf,action='apply',preview_token=token))
        token=self.token(preview('2026-09-13'));self.assertEqual(apply(token).status_code,302);self.assertEqual(bill.lines,old);charge=self.Charge.query.one();self.assertEqual(charge.amount,3000);self.assertEqual(charge.target_month,'2026-10')
        self.assertEqual(apply(token).status_code,422);self.assertEqual(apply(self.token(preview('2026-09-13'))).status_code,302);self.assertEqual(self.Charge.query.count(),1)
        self.assertEqual(apply(self.token(preview('2026-09-14'))).status_code,302);self.assertEqual(sorted(c.amount for c in self.Charge.query.all()),[1000,3000])
        target=self.bill('2026-10');self.assertEqual(self.posting_apply(self.token(self.posting_preview(charge,target))).status_code,302);self.assertEqual(target.total,103000)
        self.assertEqual(apply(self.token(preview('2026-09-14'))).status_code,302);self.assertEqual(self.Charge.query.count(),2);self.assertEqual(bill.lines,old)
    def test_pending_fines_csrf_and_empty_invalid_selection(self):
        self.assertEqual(self.c.post(self.queue,data=dict(action='apply')).status_code,400)
        self.assertEqual(self.c.post(self.queue,data=dict(_csrf=self.csrf,action='preview')).status_code,422)
        self.assertEqual(self.preview(student_ids='x').status_code,422);self.assertEqual(self.preview(month='2026-13').status_code,422)

    def test_cancel_pending_keeps_audit_and_corrected_month_can_be_reviewed_again(self):
        charge=self.assess();original_id=charge.id;bill=self.bill();old_token=self.token(self.posting_preview(charge,bill))
        values={'_csrf':self.csrf,'cancel_id':str(charge.id),'cancel_version_'+str(charge.id):str(charge.version),'cancel_reason_'+str(charge.id):'Attendance correction','cancel_confirm_'+str(charge.id):'1'}
        self.assertEqual(self.c.post(self.queue,data=values).status_code,302);self.assertEqual(self.Charge.query.count(),0)
        audit=self.ops['audit'].query.filter_by(action='Cancel unposted fine').one();self.assertEqual(audit.data['amount'],14000);self.assertEqual(audit.data['reason'],'Attendance correction')
        self.assertEqual(self.apply(self.token(self.preview())).status_code,302);self.assertGreater(self.Charge.query.one().id,original_id)
        self.assertEqual(self.posting_apply(old_token).status_code,422);self.assertEqual(bill.total,100000)
    def test_cancel_requires_reason_confirmation_version_and_unposted_charge(self):
        charge=self.assess();cid=str(charge.id);values={'_csrf':self.csrf,'cancel_id':cid,'cancel_version_'+cid:str(charge.version),'cancel_reason_'+cid:'Correction','cancel_confirm_'+cid:'1'}
        for changes in [{'cancel_reason_'+cid:''},{'cancel_confirm_'+cid:''},{'cancel_version_'+cid:'0'}]:
            self.assertEqual(self.c.post(self.queue,data={**values,**changes}).status_code,422);self.assertEqual(self.Charge.query.count(),1)
        bill=self.bill();self.posting_apply(self.token(self.posting_preview(charge,bill)));self.assertEqual(self.c.post(self.queue,data=values).status_code,422)

    def test_concurrent_attendance_confirmation_creates_one_charge(self):
        import tempfile,threading
        from concurrent.futures import ThreadPoolExecutor
        from flask import g,request
        from sqlalchemy import create_engine,select
        with tempfile.TemporaryDirectory() as directory:
            engine=create_engine('sqlite:///'+directory+'/attendance.db',connect_args={'timeout':20})
            db.metadata.create_all(engine,tables=app.extensions['identity_helpers']['workspace_tables']())
            with app.test_request_context('/'):
                g.institute_engine=engine;db.session.remove()
                db.session.add(Student(id=1,admission_no='CONCURRENT-ATT',name='Fictional concurrent',status='Active'));db.session.flush()
                db.session.add(self.Head(key='Attendance Fine',label='Attendance Fine',timing='fine',months=[],custom=True))
                db.session.add(self.Item(kind='attendance-fine-policy',scope='',name='',data=dict(head='Attendance Fine',rules={'Absent':dict(enabled=True,free=0,rate=1000)})))
                db.session.add(self.Daily(kind='student',person_id=1,day=date(2026,9,10),status='Absent'));db.session.commit();db.session.remove()
            barrier=threading.Barrier(2)
            def bind():
                if request.endpoint=='attendance_fines.assessment':
                    g.institute_engine=engine
                    if request.form.get('action')=='apply':barrier.wait(timeout=10)
            app.before_request_funcs.setdefault(None,[]).append(bind)
            def client():
                c=app.test_client()
                with c.session_transaction() as sess:sess['record_csrf']='attendance-concurrent'
                return c
            try:
                preview=client().post(self.path+'/assess',data=dict(_csrf='attendance-concurrent',action='preview',month='2026-09',student_ids='1'));token=self.token(preview)
                def apply(_):return client().post(self.path+'/assess',data=dict(_csrf='attendance-concurrent',action='apply',preview_token=token)).status_code
                with ThreadPoolExecutor(max_workers=2) as pool:statuses=list(pool.map(apply,range(2)))
                self.assertEqual(sorted(statuses),[302,422])
                with engine.connect() as connection:rows=connection.execute(select(self.Charge.__table__.c.amount)).scalars().all()
                self.assertEqual(rows,[1000])
            finally:app.before_request_funcs[None].remove(bind);engine.dispose()

    def test_batch_posting_is_atomic_when_one_target_changes(self):
        first=self.assess();bill=self.bill();second=self.Charge(student_id=self.s.id,kind='attendance',source='attendance:manual-fixture',target_month='2026-10',amount=1000,data=copy.deepcopy(first.data));db.session.add(second);db.session.commit()
        data={'_csrf':self.csrf,'action':'preview','ids':[str(first.id),str(second.id)],'bill_'+str(first.id):str(bill.id),'bill_'+str(second.id):str(bill.id)}
        token=self.token(self.c.post(self.queue,data=data));second.amount=2000;db.session.commit()
        self.assertEqual(self.posting_apply(token).status_code,422);self.assertEqual(bill.total,100000);self.assertIsNone(first.bill_id)
        self.assertEqual(self.posting_apply(self.token(self.c.post(self.queue,data=data))).status_code,302);self.assertEqual(bill.total,116000)

    def test_batch_reads_are_bounded_and_do_not_load_photos(self):
        from sqlalchemy import event
        self.policy();ids=[str(self.s.id)]
        for i in range(24):
            p=Student(admission_no='ATT-BATCH-'+str(i),name='Batch '+str(i),class_name='One',status='Active');db.session.add(p);db.session.flush()
            db.session.add(self.rm['student'](student_id=p.id,data={'campus':'Campus A'}));db.session.add(self.Daily(kind='student',person_id=p.id,day=date(2026,9,10),status='Absent'));ids.append(str(p.id))
        db.session.commit();db.session.remove();queries=[]
        def tally(conn,cursor,statement,parameters,context,executemany):
            if statement.lstrip().lower().startswith('select'):queries.append(statement.lower())
        event.listen(db.engine,'before_cursor_execute',tally)
        try:response=self.preview(student_ids=ids)
        finally:event.remove(db.engine,'before_cursor_execute',tally)
        self.token(response);self.assertLessEqual(len(queries),12,queries);self.assertFalse(any('record_file' in q for q in queries))
