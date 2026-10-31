"""Fee settings feed real assignments and immutable challans, with fictional data."""
import os,re,unittest
from datetime import date
os.environ['DATABASE_URL']='sqlite:///:memory:'
from app import app,db,Student

class FeeSetupTests(unittest.TestCase):
    def setUp(self):
        app.config.update(TESTING=True,IDENTITY_ENFORCE_IN_TESTS=False,SECRET_KEY='fee-settings-test')
        self.ctx=app.app_context();self.ctx.push();db.drop_all();db.create_all()
        self.rm=app.extensions['record_models'];self.m=app.extensions['fee_setup_models'];self.ops=app.extensions['ops_models'];self.P=app.extensions['student_fee_plan_model'];self.B=self.ops['bill']
        for cat,values in {'campus':['Campus A','Campus B'],'class_name':['One','Two']}.items():
            for value in values:db.session.add(self.rm['settings'](category=cat,value=value,class_name=''))
        self.s=Student(admission_no='TEST-FEES-1',name='Fictional Student',class_name='One',status='Active');db.session.add(self.s);db.session.flush();db.session.add(self.rm['student'](student_id=self.s.id,data={'campus':'Campus A'}));db.session.commit()
        self.c=app.test_client();self.c.get('/workspace/core/fees/heads')
        with self.c.session_transaction() as session:self.csrf=session['record_csrf']
    def tearDown(self):db.session.remove();db.drop_all();self.ctx.pop()
    def post(self,page,**data):
        response=self.c.post('/workspace/core/fees/'+page,data={'_csrf':self.csrf,**data})
        if response.status_code==302:self.assertEqual(self.c.get(response.location).status_code,200,response.location)
        return response
    def head(self,key='Tuition Fee',timing='monthly',**changes):
        row=db.session.get(self.m['head'],key)
        data=dict(action='save',key=key,label=key,timing=timing,version=str(row.version if row else 0));data.update(changes);return self.post('heads',**data)
    def schedule(self,**changes):
        data=dict(action='save',version='0',name='School Plan',campuses=['Campus A'],classes=['One'],due_day='31')
        keys=['Tuition Fee','Admission Fee','Annual Charges','Books Payment'];amounts=['3500','2000','1000','500'];data['head_key']=keys
        for i,key in enumerate(keys):
            head=db.session.get(self.m['head'],key);data.update({f'head_version_{i}':str(head.version if head else 0),f'amount_{i}':amounts[i],f'minimum_{i}':'',f'maximum_{i}':''})
        data.update(changes);return self.post('schedules',**data)
    def configured(self):
        self.head();self.head('Admission Fee','first');self.head('Annual Charges','months',months=['4']);self.head('Books Payment','manual')
        self.assertEqual(self.schedule(minimum_0='3000',maximum_0='4000').status_code,302)
        return self.m['schedule'].query.one()
    def assign(self,row=None,**changes):
        row=row or self.m['schedule'].query.one();latest=self.P.query.order_by(self.P.effective.desc()).first()
        data=dict(_csrf=self.csrf,origin=f'{latest.id}:{latest.version}' if latest else 'new',schedule=row.name,schedule_revision=f'{row.id}:{row.version}',effective='2026-09',percentage='10',year='2026')
        for i in range(8):data.update({f'discount_{i}':'0',f'arrears_{i}':'0'})
        data['discount_1']='1500';data.update(changes)
        return self.c.post('/workspace/student-fee-plans/1/edit',data=data)
    def generate(self,month='2026-09',**changes):
        data=dict(_csrf=self.csrf,month=month,timing_mode='auto',student_ids='1');data.update(changes)
        return self.c.post('/workspace/student-fee-plans/generate',data=data)
    def test_gets_do_not_seed_rules_and_all_settings_ids_are_unique(self):
        for path in ['/workspace/core/fees/heads','/workspace/core/fees/schedules','/workspace/core/institute','/workspace/student-fee-plans/generate']:
            page=self.c.get(path);self.assertEqual(page.status_code,200,path)
            ids=re.findall(rb'\bid="([^"]+)"',page.data);self.assertEqual(len(ids),len(set(ids)),path)
        self.assertEqual(self.m['head'].query.count(),0);self.assertEqual(self.m['schedule'].query.count(),0);self.assertEqual(self.B.query.count(),0)
    def test_heads_validate_csrf_stale_months_and_unique_names(self):
        self.assertEqual(self.c.post('/workspace/core/fees/heads',data={'action':'save'}).status_code,400)
        self.assertEqual(self.head(timing='months').status_code,422)
        self.assertEqual(self.head(timing='months',months=['13']).status_code,422)
        self.assertEqual(self.head().status_code,302)
        self.assertEqual(self.head(version='0',label='New label').status_code,422)
        self.assertEqual(self.head(label='Admission Fee').status_code,422)
        self.assertEqual(self.head(key='TUITION FEE').status_code,422)
        self.assertEqual(db.session.get(self.m['head'],'Tuition Fee').label,'Tuition Fee')
    def test_only_unused_custom_heads_can_be_deleted(self):
        self.head('Transport','manual');row=db.session.get(self.m['head'],'Transport')
        self.assertEqual(self.post('heads',action='delete',key=row.key,version=str(row.version)).status_code,302)
        self.assertEqual(self.post('heads',action='delete',key='Admission Fee',version='0').status_code,422)
        self.configured();self.assertEqual(self.post('heads',action='delete',key='Tuition Fee',version='1').status_code,422)
        self.head('Custom Test','monthly');head=db.session.get(self.m['head'],'Custom Test');db.session.add(self.B(student_id=1,month='2026-01',due=date(2026,1,10),lines=[{'particular':'Custom Test','amount':100}]));db.session.commit()
        self.assertEqual(self.post('heads',action='delete',key=head.key,version=str(head.version)).status_code,422)
    def test_amount_bounds_nan_and_missing_head_versions_roll_back_scope_batch(self):
        self.head()
        for changes in [dict(amount_0='NaN'),dict(minimum_0='3501'),dict(maximum_0='3499'),dict(minimum_0='4000',maximum_0='3000'),dict(head_version_0='0'),dict(campuses=['Unknown']),dict(due_day='32')]:
            self.assertEqual(self.schedule(campuses=['Campus A','Campus B'],**{k:v for k,v in changes.items() if k!='campuses'}).status_code,422,changes) if 'campuses' not in changes else self.assertEqual(self.schedule(**changes).status_code,422)
            self.assertEqual(self.m['schedule'].query.count(),0)
        self.assertEqual(self.schedule(minimum_0='3500',maximum_0='3500').status_code,302)
    def test_multiple_scopes_duplicate_and_independent_amounts(self):
        self.assertEqual(self.schedule(campuses=['Campus A','Campus B'],classes=['One','Two']).status_code,302)
        self.assertEqual(self.m['schedule'].query.count(),4)
        row=self.m['schedule'].query.filter_by(campus='Campus A',class_name='One').one()
        self.assertEqual(self.schedule(id=str(row.id),version=str(row.version),amount_0='4500').status_code,302)
        self.assertEqual(self.m['schedule'].query.filter_by(campus='Campus B',class_name='One').one().lines[0]['amount'],350000)
        self.assertEqual(self.schedule(id=str(row.id),version=str(row.version),action='duplicate',name='Other Plan',campuses=['Campus B'],classes=['Two']).status_code,302)
        self.assertEqual(self.m['schedule'].query.count(),5)
        self.assertIn(b'Other Plan',self.c.get('/workspace/core/institute').data)
    def test_existing_schedule_name_and_scope_stay_stable_and_stale_save_rejected(self):
        row=self.configured();old=row.version
        self.assertEqual(self.schedule(id=str(row.id),version=str(old),name='Rename in place').status_code,422)
        self.assertEqual(self.schedule(id=str(row.id),version=str(old),campuses=['Campus B']).status_code,422)
        self.assertEqual(self.schedule(id=str(row.id),version=str(old),amount_0='3600').status_code,302)
        self.assertEqual(self.schedule(id=str(row.id),version=str(old),amount_0='3700').status_code,422)
        self.assertEqual(row.lines[0]['amount'],360000)
    def test_schedule_assignment_checks_scope_and_source_revision(self):
        row=self.configured();old=f'{row.id}:{row.version}'
        self.schedule(id=str(row.id),version=str(row.version),amount_0='3600')
        self.assertEqual(self.assign(row,schedule_revision=old).status_code,422);self.assertEqual(self.P.query.count(),0)
        detail=self.rm['student'].query.one();detail.data={'campus':'Campus B'};db.session.commit()
        self.assertEqual(self.assign(row).status_code,422);self.assertEqual(self.P.query.count(),0)
    def test_automatic_rules_and_net_increment_flow_to_real_challans(self):
        row=self.configured();self.assertEqual(self.assign(row).status_code,302)
        plan=self.P.query.one();tuition=plan.data['lines'][1];self.assertEqual((tuition['actual'],tuition['net']),(370000,220000))
        self.assertEqual(self.generate().status_code,302);first=self.B.query.one();self.assertEqual(first.total,440000);self.assertEqual(first.due,date(2026,9,30))
        self.assertEqual(self.generate().status_code,302);self.assertEqual(self.B.query.count(),1)
        self.assertEqual(self.generate('2026-10').status_code,302);self.assertEqual(self.B.query.filter_by(month='2026-10').one().total,220000)
        self.assertEqual(self.generate('2027-04',particular='Books Payment').status_code,302);self.assertEqual(self.B.query.filter_by(month='2027-04').one().total,385000)
        self.assertEqual(next(x for x in first.lines if x['particular']=='Tuition Fee')['billing_rule']['timing'],'monthly')
    def test_old_plan_and_challans_keep_amounts_until_explicit_schedule_reload(self):
        row=self.configured();self.assign(row);self.generate();bill=self.B.query.one();original=bill.total
        self.schedule(id=str(row.id),version=str(row.version),amount_0='4500')
        self.assertEqual(self.assign(row).status_code,302);self.assertEqual(self.P.query.one().data['lines'][1]['net'],220000)
        self.assertEqual(self.assign(row,refresh_schedule='1').status_code,302);self.assertEqual(self.P.query.one().data['lines'][1]['net'],330000)
        self.assertEqual(bill.total,original)
    def test_empty_month_override_skips_new_fees_without_empty_bills(self):
        self.head();self.assertEqual(self.schedule(override_0='1',months_0=[],amount_1='0',amount_2='0',amount_3='0').status_code,302);self.assign(percentage='0',discount_1='0')
        self.assertEqual(self.generate().status_code,302);self.assertEqual(self.B.query.count(),0)
    def test_first_only_schedule_override_applies_even_to_a_monthly_head(self):
        self.head();self.schedule(first_0='1',amount_1='0',amount_2='0',amount_3='0');self.assign(percentage='0',discount_1='0')
        self.assertEqual(self.generate().status_code,302);self.assertEqual(self.generate('2026-10').status_code,302);self.assertEqual(self.B.query.count(),1)
    def test_manual_heads_require_selection_and_fine_policy_is_never_guessed(self):
        self.configured();self.assign();self.head('Books Payment','fine')
        self.assertEqual(self.generate(particular='Books Payment').status_code,422);self.assertEqual(self.B.query.count(),0)
        self.assertEqual(self.generate().status_code,302);self.assertEqual(self.B.query.one().total,440000)
    def test_opening_arrears_are_independent_and_claimed_once(self):
        self.configured();self.assign(arrears_1='100');self.generate(include_arrears='on');self.generate('2026-10',include_arrears='on')
        self.assertEqual(self.B.query.filter_by(month='2026-09').one().total,450000);self.assertEqual(self.B.query.filter_by(month='2026-10').one().total,220000)
        self.assertEqual(app.extensions['fee_arrears_claim_model'].query.count(),1)
    def test_preview_is_read_only_and_short_month_due_day_is_clamped(self):
        row=self.configured();before=self.ops['audit'].query.count()
        page=self.c.get(f'/workspace/core/fees/preview/{row.id}?month=2027-02&first=1')
        self.assertEqual(page.status_code,200);self.assertIn(b'2027-02-28',page.data);self.assertIn(b'5,500.00',page.data)
        self.assertEqual(self.B.query.count(),0);self.assertEqual(self.P.query.count(),0);self.assertEqual(self.ops['audit'].query.count(),before)
        self.assertEqual(self.c.get(f'/workspace/core/fees/preview/{row.id}?month=2026-13').status_code,422)
    def test_label_rename_preserves_canonical_keys_claims_and_printed_bill_snapshot(self):
        self.configured();self.assign();self.generate();first=self.B.query.one();old_total=first.total
        self.head(label='Monthly Tuition');self.generate('2026-10');second=self.B.query.filter_by(month='2026-10').one()
        self.assertEqual(second.lines[0]['particular'],'Tuition Fee');self.assertEqual(second.lines[0]['display_name'],'Monthly Tuition');self.assertEqual(first.total,old_total);self.assertEqual(next(x for x in first.lines if x['particular']=='Tuition Fee')['display_name'],'Tuition Fee')
        page=self.c.post('/workspace/fee-action',data={'_csrf':self.csrf,'action':'horizontal','ids':str(first.id)});self.assertEqual(page.status_code,200);self.assertNotIn(b'Monthly Tuition',page.data)
        page=self.c.get('/workspace/reports/fees/class-fees?from=2026-09&to=2026-10&particular=Monthly+Tuition');self.assertEqual(page.status_code,200);self.assertIn(b'Monthly Tuition',page.data)
    def test_delete_used_schedule_and_class_map_links_are_guarded(self):
        row=self.configured();Map=app.extensions['institute_setup_models']['mapping'];mapping=Map(campus='Campus A',class_name='One',data={'fee_plans':['School Plan']});db.session.add(mapping);db.session.commit()
        self.assertEqual(self.post('schedules',action='delete',id=str(row.id),version=str(row.version)).status_code,422)
        db.session.delete(mapping);db.session.commit();self.assign(row)
        self.assertEqual(self.post('schedules',action='delete',id=str(row.id),version=str(row.version)).status_code,422)
    def test_existing_bill_and_invalid_batch_do_not_create_partial_charges(self):
        row=self.configured();self.assign(row);other=Student(admission_no='NO-PLAN',name='Unassigned',status='Active');db.session.add(other);db.session.commit()
        self.assertEqual(self.generate(student_ids=['1',str(other.id)]).status_code,422);self.assertEqual(self.B.query.count(),0)
        db.session.add(self.B(student_id=1,month='2026-09',due=date(2026,9,10),lines=[{'particular':'Existing','amount':100}]));db.session.commit()
        self.assertEqual(self.generate().status_code,422);self.assertEqual(self.B.query.count(),1)
    def test_earlier_configuration_can_be_loaded_and_replaced_without_rewriting_student_data(self):
        source=self.ops['workflow'](kind='fee-plans',status='Active',data={'name':'School Plan','campus':'Campus A','class_name':'One','particular':'Tuition Fee','amount':'3500','due_day':'10'});db.session.add(source);db.session.commit()
        page=self.c.get('/workspace/core/fees/schedules?from_saved='+str(source.id));self.assertEqual(page.status_code,200);self.assertIn(b'value="3500.00"',page.data)
        self.assertEqual(self.schedule().status_code,422);self.assertEqual(source.status,'Active')
        self.assertEqual(self.schedule(replace_previous='1').status_code,302);self.assertEqual(source.status,'Inactive')
        self.assertEqual(self.c.get('/workspace/register/fee-plans').status_code,302)
        self.assertEqual(self.c.post('/workspace/register/fee-plans',data={'_csrf':self.csrf,'name':'Bypass'}).status_code,422)

    def test_concurrent_months_can_charge_first_challan_fee_only_once(self):
        import tempfile,threading
        from concurrent.futures import ThreadPoolExecutor
        from sqlalchemy import create_engine,select,func
        from flask import g,request
        with tempfile.TemporaryDirectory() as directory:
            engine=create_engine('sqlite:///'+directory+'/fees.db',connect_args={'timeout':20})
            db.metadata.create_all(engine,tables=app.extensions['identity_helpers']['workspace_tables']())
            with app.test_request_context('/'):
                g.institute_engine=engine;db.session.remove()
                db.session.add(Student(id=1,admission_no='CONCURRENT-TEST',name='Concurrent Fictional Pupil',status='Active'))
                db.session.add(self.m['head'](key='Admission Fee',label='Admission Fee',timing='first',months=[],custom=False))
                db.session.add(self.P(student_id=1,effective='2026-01',data={'schedule':'First only','due_day':10,'lines':[{'particular':'Admission Fee','actual':100000,'discount':0,'net':100000,'arrears':0}]}));db.session.commit();db.session.remove()
            barrier=threading.Barrier(2)
            def bind_test_database():
                if request.endpoint=='student_plans.generate':g.institute_engine=engine;barrier.wait(timeout=10)
            app.before_request_funcs.setdefault(None,[]).append(bind_test_database)
            def generate(month):
                client=app.test_client()
                with client.session_transaction() as session:session['record_csrf']='concurrent-csrf'
                return client.post('/workspace/student-fee-plans/generate',data={'_csrf':'concurrent-csrf','month':month,'timing_mode':'auto','student_ids':'1'}).status_code
            try:
                with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(generate,['2026-09','2026-10']))
                self.assertEqual(results,[302,302])
                with engine.connect() as connection:self.assertEqual(connection.scalar(select(func.count()).select_from(self.B.__table__)),1)
            finally:app.before_request_funcs[None].remove(bind_test_database);engine.dispose()

    def test_audit_retains_before_and_after_configuration_amounts(self):
        self.head();self.head(label='Monthly Tuition')
        head_event=self.ops['audit'].query.filter_by(action='Save fee head').order_by(self.ops['audit'].id.desc()).first()
        self.assertEqual(head_event.data['before']['label'],'Tuition Fee');self.assertEqual(head_event.data['label'],'Monthly Tuition')
        self.schedule();row=self.m['schedule'].query.one();self.schedule(id=str(row.id),version=str(row.version),amount_0='4500')
        event=self.ops['audit'].query.filter_by(action='Save fee schedule').order_by(self.ops['audit'].id.desc()).first()
        self.assertEqual(event.data['before']['lines'][0]['amount'],350000);self.assertEqual(event.data['after']['lines'][0]['amount'],450000)

    def test_reloading_a_schedule_preserves_concessions_and_requires_review_if_they_exceed_new_fee(self):
        row=self.configured();self.assign(row,arrears_1='100')
        self.schedule(id=str(row.id),version=str(row.version),amount_0='1000')
        page=self.c.get('/workspace/student-fee-plans/1/edit?refresh_schedule=1')
        self.assertEqual(page.status_code,200)
        self.assertRegex(page.data,rb'name="discount_1"[^>]*value="1500.00"');self.assertRegex(page.data,rb'name="arrears_1"[^>]*value="100.00"')
        self.assertEqual(self.assign(row,refresh_schedule='1').status_code,422);self.assertEqual(self.P.query.one().data['lines'][1]['net'],220000)
