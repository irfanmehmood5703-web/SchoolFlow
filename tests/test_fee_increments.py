"""Preview-bound batches preserve concessions, arrears and existing challans."""
import copy,html,os,re,unittest
from datetime import date
from unittest.mock import patch
os.environ['DATABASE_URL']='sqlite:///:memory:'
from app import app,db,Student

class FeeIncrementTests(unittest.TestCase):
    path='/workspace/core/fees/increments'
    def setUp(self):
        app.config.update(TESTING=True,IDENTITY_ENFORCE_IN_TESTS=False,SECRET_KEY='batch-test')
        self.ctx=app.app_context();self.ctx.push();db.drop_all();db.create_all()
        self.P=app.extensions['student_fee_plan_model'];self.rm=app.extensions['record_models'];self.ops=app.extensions['ops_models']
        self.s,self.p=self.student('ONE');self.s2,self.p2=self.student('TWO',actual=500000,discount=100000)
        self.sid=self.s.id;self.c=app.test_client();self.c.get(self.path)
        with self.c.session_transaction() as sess:self.csrf=sess['record_csrf']
    def tearDown(self):db.session.remove();db.drop_all();self.ctx.pop()
    def student(self,name,campus='Campus A',cls='One',actual=350000,discount=150000):
        s=Student(admission_no=name,name='Fictional '+name,class_name=cls,status='Active');db.session.add(s);db.session.flush()
        db.session.add(self.rm['student'](student_id=s.id,data=dict(campus=campus)))
        line=dict(particular='Tuition Fee',actual=actual,discount=discount,net=actual-discount,arrears=10000,fee_rules=dict(month_override=True,months=[4,9]))
        p=self.P(student_id=s.id,effective='2026-09',data=dict(schedule='Scope Plan',schedule_id=99,schedule_version=3,due_day=31,percentage='0',year='2026',reason='Saved concession',notes='Saved notes',lines=[line,dict(particular='Fully waived',actual=50000,discount=50000,net=0,arrears=0)]))
        db.session.add(p);db.session.commit();return s,p
    def post(self,**changes):
        data=dict(_csrf=self.csrf,action='preview',student_ids=str(self.sid),effective='2027-09',percentage='10',year='2027',note='Yearly review',campus='Campus A',class_name='One');data.update(changes)
        return self.c.post(self.path,data=data)
    def token(self,response):
        self.assertEqual(response.status_code,200,response.data[:300]);match=re.search(rb'name="preview_token" value="([^"]+)"',response.data);self.assertIsNotNone(match);return html.unescape(match[1].decode())
    def apply(self,token,**changes):return self.post(action='apply',preview_token=token,**changes)
    def test_get_filters_pagination_no_writes_unique_ids(self):
        before=self.P.query.count();r=self.c.get(self.path);self.assertEqual(r.status_code,200)
        ids=re.findall(rb'\bid="([^"]+)"',r.data);self.assertEqual(len(ids),len(set(ids)))
        self.assertNotIn(b'name="percentage" type="number" value="10"',r.data)
        self.assertIn(b'Fictional ONE',r.data);self.assertNotIn(b'Fictional TWO',self.c.get(self.path+'?q=ONE').data)
        self.assertNotIn(b'Fictional ONE',self.c.get(self.path+'?campus=Other').data)
        self.assertEqual(self.c.get(self.path+'?size=5').status_code,422);self.assertEqual(self.c.get(self.path+'?page=abc').status_code,422)
        self.assertEqual(self.P.query.count(),before);self.assertEqual(self.ops['audit'].query.count(),0)
    def test_preview_is_escaped_read_only_and_shows_net_calculation(self):
        before=copy.deepcopy(self.p.data);r=self.post(note='<script>bad()</script>');self.token(r)
        self.assertIn(b'2,000.00',r.data);self.assertIn(b'200.00',r.data);self.assertIn(b'2,200.00',r.data)
        self.assertIn(b'&lt;script&gt;',r.data);self.assertNotIn(b'<script>bad',r.data)
        self.assertEqual(self.p.data,before);self.assertEqual(self.P.query.count(),2);self.assertEqual(self.ops['audit'].query.count(),0)
    def test_apply_batch_uses_saved_net_preserves_all_metadata_and_old_bill(self):
        Bill=self.ops['bill'];bill=Bill(student_id=self.s.id,month='2026-09',due=date(2026,9,10),lines=[dict(particular='Tuition Fee',amount=200000)]);db.session.add(bill);db.session.commit()
        token=self.token(self.post(student_ids=[str(self.s.id),str(self.s2.id)]));self.assertEqual(self.apply(token,percentage='99',student_ids='999',effective='2028-09').status_code,302)
        newer=self.P.query.filter_by(student_id=self.s.id,effective='2027-09').one();line=newer.data['lines'][0]
        self.assertEqual((line['actual'],line['discount'],line['net'],line['increment'],line['arrears']),(370000,150000,220000,20000,10000))
        self.assertEqual(line['fee_rules'],self.p.data['lines'][0]['fee_rules'])
        for key in ('schedule_id','schedule_version','due_day','reason','notes'):self.assertEqual(newer.data[key],self.p.data[key])
        self.assertEqual(newer.data['lines'][1]['net'],0);self.assertEqual(bill.total,200000)
        other=self.P.query.filter_by(student_id=self.s2.id,effective='2027-09').one();self.assertEqual(other.data['lines'][0]['net'],440000)
        audit=self.ops['audit'].query.filter_by(action='Apply bulk fee increment').one();self.assertEqual(len(audit.data['changes']),2)
        self.assertEqual(audit.data['changes'][0]['after']['lines'][0]['net'],220000)
    def test_same_month_repreview_does_not_compound_and_later_month_carries_forward(self):
        self.assertEqual(self.apply(self.token(self.post(effective='2026-09'))).status_code,302)
        self.assertEqual(self.p.data['lines'][0]['net'],220000)
        token=self.token(self.post(effective='2026-09'));self.assertEqual(self.apply(token).status_code,302);self.assertEqual(self.p.data['lines'][0]['net'],220000)
        # The no-op preview remains financially harmless on replay and does not add duplicate audit entries.
        count=self.ops['audit'].query.count();self.assertEqual(self.apply(token).status_code,302);self.assertEqual(self.ops['audit'].query.count(),count)
        self.assertEqual(self.apply(self.token(self.post())).status_code,302)
        self.assertEqual(self.P.query.filter_by(student_id=self.s.id,effective='2027-09').one().data['lines'][0]['net'],242000)
    def test_same_month_percentage_replaces_previous_percentage(self):
        self.apply(self.token(self.post(effective='2026-09')))
        self.apply(self.token(self.post(effective='2026-09',percentage='20')))
        self.assertEqual((self.p.data['lines'][0]['base_actual'],self.p.data['lines'][0]['net']),(350000,240000))
    def test_stale_source_rejects_entire_batch(self):
        token=self.token(self.post(student_ids=[str(self.s.id),str(self.s2.id)]))
        self.p2.data={**self.p2.data,'notes':'Changed'};db.session.commit()
        self.assertEqual(self.apply(token).status_code,422);self.assertEqual(self.P.query.count(),2);self.assertEqual(self.ops['audit'].query.count(),0)
    def test_moved_inactive_or_renamed_student_invalidates_preview(self):
        for key,value in [('status','Inactive'),('class_name','Two'),('name','Changed Student')]:
            token=self.token(self.post());old=getattr(self.s,key);setattr(self.s,key,value);db.session.commit()
            self.assertEqual(self.apply(token).status_code,422);self.assertEqual(self.P.query.count(),2)
            setattr(self.s,key,old);db.session.commit()
        token=self.token(self.post());detail=self.rm['student'].query.filter_by(student_id=self.s.id).one();detail.data={'campus':'Campus B'};db.session.commit()
        self.assertEqual(self.apply(token).status_code,422)
    def test_newer_plan_after_preview_and_historical_target_are_rejected(self):
        self.assertEqual(self.post(effective='2026-08').status_code,422)
        token=self.token(self.post());db.session.add(self.P(student_id=self.s.id,effective='2028-01',data=copy.deepcopy(self.p.data)));db.session.commit()
        self.assertEqual(self.apply(token).status_code,422);self.assertEqual(self.P.query.count(),3)
    def test_tampered_expired_and_other_session_previews_are_rejected(self):
        token=self.token(self.post())
        self.assertEqual(self.apply(token+'bad').status_code,422)
        from itsdangerous import URLSafeTimedSerializer
        serializer=URLSafeTimedSerializer(app.config['SECRET_KEY'],salt='schoolflow-fee-increment-v1')
        payload=serializer.loads(token)
        with patch('itsdangerous.timed.TimestampSigner.get_timestamp',return_value=1000):old=serializer.dumps(payload)
        self.assertEqual(self.apply(old).status_code,422)
        other=app.test_client();other.get(self.path)
        with other.session_transaction() as sess:csrf=sess['record_csrf']
        self.assertEqual(other.post(self.path,data=dict(_csrf=csrf,action='apply',preview_token=token)).status_code,422)
        self.assertEqual(self.P.query.count(),2)
    def test_replay_after_changed_save_does_not_duplicate_or_compound(self):
        token=self.token(self.post());self.assertEqual(self.apply(token).status_code,302)
        self.assertEqual(self.apply(token).status_code,422);self.assertEqual(self.P.query.count(),3)
        self.assertEqual(self.P.query.filter_by(student_id=self.s.id,effective='2027-09').one().data['lines'][0]['net'],220000)
    def test_validation_csrf_selection_percentage_bounds_and_no_direct_apply(self):
        self.assertEqual(self.post(_csrf='').status_code,400)
        for changes in [dict(student_ids=[]),dict(student_ids=['1']*101),dict(student_ids='bad'),dict(student_ids='999'),dict(campus='Other'),dict(class_name='Two'),dict(percentage=''),dict(percentage='NaN'),dict(percentage='-1'),dict(percentage='1000000000'),dict(year='1899'),dict(effective='2027-13'),dict(note='x'*1001),dict(action='save'),dict(action='apply')]:
            self.assertEqual(self.post(**changes).status_code,422,changes)
        self.assertEqual(self.P.query.count(),2);self.assertEqual(self.ops['audit'].query.count(),0)
    def test_unassigned_student_or_overflow_makes_whole_preview_fail(self):
        s=Student(admission_no='NO-PLAN',name='No plan',status='Active');db.session.add(s);db.session.commit()
        self.assertEqual(self.post(student_ids=[str(self.s.id),str(s.id)]).status_code,422)
        self.assertEqual(self.post(percentage='999999999').status_code,422)
        self.assertEqual(self.P.query.count(),2)
    def test_half_paisa_rounds_up_and_arrears_are_not_incremented(self):
        self.p.data={**self.p.data,'lines':[dict(particular='Tiny',actual=2,discount=1,net=1,arrears=99999)]};db.session.commit()
        self.assertEqual(self.apply(self.token(self.post(percentage='50'))).status_code,302)
        line=self.P.query.filter_by(student_id=self.s.id,effective='2027-09').one().data['lines'][0]
        self.assertEqual((line['increment'],line['net'],line['arrears']),(1,2,99999))
    def test_increased_plan_flows_to_new_bill_but_retains_timing(self):
        self.assertEqual(self.apply(self.token(self.post())).status_code,302)
        Bill=self.ops['bill']
        Head=app.extensions['fee_setup_models']['head'];db.session.add(Head(key='Tuition Fee',label='Tuition',timing='monthly',months=[],custom=False));db.session.commit()
        response=self.c.post('/workspace/student-fee-plans/generate',data=dict(_csrf=self.csrf,month='2027-09',timing_mode='auto',student_ids=str(self.s.id)))
        self.assertEqual(response.status_code,302);self.assertEqual(Bill.query.one().total,220000)
        self.assertEqual(Bill.query.one().due,date(2027,9,30))
        response=self.c.post('/workspace/student-fee-plans/generate',data=dict(_csrf=self.csrf,month='2027-10',timing_mode='auto',student_ids=str(self.s.id)))
        self.assertEqual(response.status_code,302);self.assertEqual(Bill.query.count(),1)

    def test_management_and_configuration_live_in_separate_header_positions(self):
        page=self.c.get('/workspace/dashboard').data
        utility=page.split(b'<div class="workspace-utility"',1)[1].split(b'<div class="brand-row"',1)[0]
        self.assertLess(utility.index(b'Management'),utility.index(b'Configuration'))
        self.assertIn(b'class="nav-menu configuration-menu"',utility)
        for label in (b'Institute Setup',b'Fee Settings',b'Exam Settings',b'HRM Settings'):
            self.assertIn(label,utility)
        main=page.split(b'<nav class="top-navigation"',1)[1].split(b'</nav>',1)[0]
        self.assertNotIn(b'Configuration',main);self.assertNotIn(b'Core Settings',main)
        self.assertEqual(page.count(b'class="nav-menu configuration-menu"'),1)
        self.assertNotIn(b'<aside',page)

    def test_batch_selection_is_paginated_and_database_queries_are_bounded(self):
        from sqlalchemy import event
        for i in range(28):self.student('PAGE'+str(i))
        queries=[]
        def capture(conn,cursor,statement,parameters,context,executemany):
            if statement.lstrip().lower().startswith('select'):queries.append(statement)
        db.session.remove();event.listen(db.engine,'before_cursor_execute',capture)
        try:page=self.c.get(self.path)
        finally:event.remove(db.engine,'before_cursor_execute',capture)
        self.assertEqual(page.status_code,200);self.assertEqual(page.data.count(b'name="student_ids"'),25)
        self.assertLessEqual(len(queries),12,queries)
        self.assertEqual(self.c.get(self.path+'?page=2').data.count(b'name="student_ids"'),5)
        queries.clear();event.listen(db.engine,'before_cursor_execute',capture)
        try:preview=self.post(student_ids=[str(s.id) for s in Student.query.order_by(Student.id).limit(25)])
        finally:event.remove(db.engine,'before_cursor_execute',capture)
        self.token(preview);self.assertLessEqual(len(queries),12,queries)

    def test_concurrent_confirmation_saves_one_batch_without_compounding(self):
        import tempfile,threading
        from concurrent.futures import ThreadPoolExecutor
        from flask import g,request
        from sqlalchemy import create_engine,select,func
        data=copy.deepcopy(self.p.data)
        with tempfile.TemporaryDirectory() as directory:
            engine=create_engine('sqlite:///'+directory+'/increments.db',connect_args={'timeout':20})
            db.metadata.create_all(engine,tables=app.extensions['identity_helpers']['workspace_tables']())
            with app.test_request_context('/'):
                g.institute_engine=engine;db.session.remove()
                db.session.add(Student(id=1,admission_no='CONCURRENT',name='Concurrent Student',class_name='One',status='Active'));db.session.flush()
                db.session.add(self.rm['student'](student_id=1,data={'campus':'Campus A'}));db.session.add(self.P(student_id=1,effective='2026-09',data=data));db.session.commit();db.session.remove()
            barrier=threading.Barrier(2)
            def bind_test_database():
                if request.endpoint=='fee_increments.index':
                    g.institute_engine=engine
                    if request.form.get('action')=='apply':barrier.wait(timeout=10)
            app.before_request_funcs.setdefault(None,[]).append(bind_test_database)
            def client():
                c=app.test_client()
                with c.session_transaction() as sess:sess['record_csrf']='batch-concurrent-csrf'
                return c
            try:
                preview=client().post(self.path,data=dict(_csrf='batch-concurrent-csrf',action='preview',student_ids='1',effective='2027-09',percentage='10',year='2027'))
                token=self.token(preview)
                def apply(_):return client().post(self.path,data=dict(_csrf='batch-concurrent-csrf',action='apply',preview_token=token)).status_code
                with ThreadPoolExecutor(max_workers=2) as pool:statuses=list(pool.map(apply,range(2)))
                self.assertEqual(sorted(statuses),[302,422])
                with engine.connect() as connection:
                    self.assertEqual(connection.scalar(select(func.count()).select_from(self.P.__table__)),2)
                    after=connection.execute(select(self.P.__table__.c.data).where(self.P.__table__.c.effective=='2027-09')).scalar_one()
                    self.assertEqual(after['lines'][0]['net'],220000)
            finally:app.before_request_funcs[None].remove(bind_test_database);engine.dispose()
