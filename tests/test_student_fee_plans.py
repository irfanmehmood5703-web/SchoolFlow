"""Dated fee assignments, monetary bounds and billing integration, fictional data only."""
import os,unittest
from datetime import date
os.environ['DATABASE_URL']='sqlite:///:memory:'
from app import app,db,Student

class StudentFeePlanTests(unittest.TestCase):
    def setUp(self):
        app.config.update(TESTING=True,SECRET_KEY='fee-plan-test')
        self.ctx=app.app_context();self.ctx.push();db.drop_all();db.create_all()
        self.m=app.extensions['ops_models']; self.P=app.extensions['student_fee_plan_model']; self.rm=app.extensions['record_models']
        self.s=Student(admission_no='FICTIONAL-1',name='Fictional Student',father='Fictional Guardian',class_name='One',status='Active')
        db.session.add(self.s);db.session.flush();db.session.add(self.rm['student'](student_id=self.s.id,data={'campus':'Test Campus'}))
        for particular,amount in [('Admission Fee','2000'),('Tuition Fee','3500'),('Registration Fee','1500')]:
            db.session.add(self.m['workflow'](kind='fee-plans',status='Active',data=dict(name='Test Schedule',campus='Test Campus',class_name='One',particular=particular,amount=amount,due_day='10')))
        db.session.commit();self.c=app.test_client();self.c.get('/workspace/dashboard')
        with self.c.session_transaction() as session:self.csrf=session['record_csrf']
    def tearDown(self):db.session.remove();db.drop_all();self.ctx.pop()
    def post(self,path,**data):return self.c.post('/workspace/student-fee-plans'+path,data={'_csrf':self.csrf,**data})
    def form(self,**changes):
        latest=self.P.query.order_by(self.P.effective.desc()).first()
        data=dict(schedule='Test Schedule',origin=f'{latest.id}:{latest.version}' if latest else 'new',effective='2026-09',year='2026',percentage='0',reason='Test concession',notes='Fictional fixture')
        for i in range(8):data.update({f'discount_{i}':'0',f'arrears_{i}':'0'})
        data.update(discount_0='2000',discount_1='2400',discount_7='1500');data.update(changes);return data
    def save(self,**changes):return self.post(f'/{self.s.id}/edit',**self.form(**changes))
    def generate(self,month='2026-09',**changes):
        data=dict(month=month,due=month+'-10',student_ids=str(self.s.id),particular='Tuition Fee',include_arrears='on');data.update(changes)
        return self.post('/generate',**data)
    def test_create_update_view_and_zero_rows(self):
        self.assertIn(b'Fictional Student',self.c.get('/workspace/student-fee-plans').data)
        self.assertEqual(self.save().status_code,302)
        p=self.P.query.one();self.assertEqual(sum(x['actual'] for x in p.data['lines']),700000)
        self.assertEqual(sum(x['discount'] for x in p.data['lines']),590000)
        self.assertEqual(sum(x['net'] for x in p.data['lines']),110000)
        page=self.c.get(f'/workspace/student-fee-plans/{self.s.id}');self.assertEqual(page.status_code,200)
        for text in [b'Annual Charges',b'Parent',b'Principal Signature',b'1,100.00']:self.assertIn(text,page.data)
        self.assertNotIn(b'Fictional Student',self.c.get('/workspace/student-fee-plans').data)
        self.assertIn(b'Fictional Student',self.c.get('/workspace/student-fee-plans?mode=update').data)
        self.assertEqual(self.c.get(f'/workspace/student-fee-plans/{self.s.id}/edit').status_code,200)
    def test_money_bounds_nan_and_unconfirmed_percentage(self):
        for changes in [dict(discount_1='3500.01'),dict(discount_1='NaN'),dict(arrears_1='-1'),dict(percentage='-1'),dict(year='abc'),dict(effective='2026-13')]:
            self.assertEqual(self.save(**changes).status_code,422,changes);self.assertEqual(self.P.query.count(),0)
    def test_actual_cannot_be_overridden_and_incomplete_rows_rejected(self):
        data=self.form();data.pop('discount_1')
        self.assertEqual(self.post(f'/{self.s.id}/edit',**data).status_code,422)
        self.assertEqual(self.save(actual_1='1',net_1='1').status_code,302)
        self.assertEqual(self.P.query.one().data['lines'][1]['actual'],350000)
    def test_stale_save_rejected_and_change_audited(self):
        data=self.form();self.assertEqual(self.post(f'/{self.s.id}/edit',**data).status_code,302)
        self.assertEqual(self.post(f'/{self.s.id}/edit',**data).status_code,422)
        stale=self.form();self.assertEqual(self.save(discount_1='2300').status_code,302)
        self.assertEqual(self.post(f'/{self.s.id}/edit',**stale).status_code,422)
        audit=self.m['audit'].query.filter_by(action='Save student fee plan').order_by(self.m['audit'].id.desc()).first()
        self.assertEqual(audit.data['before']['lines'][1]['net'],110000);self.assertEqual(audit.data['after']['lines'][1]['net'],120000)
    def test_dated_plan_billing_snapshot_and_once_only_arrears(self):
        self.save(arrears_1='100');self.save(effective='2026-11',discount_1='2000')
        self.assertEqual(self.generate().status_code,302);bill=self.m['bill'].query.one();self.assertEqual(bill.total,120000)
        self.assertEqual(self.generate().status_code,302);self.assertEqual(self.m['bill'].query.count(),1)
        self.assertEqual(self.generate('2026-10').status_code,302)
        self.assertEqual(self.m['bill'].query.filter_by(month='2026-10').one().total,110000)
        self.assertEqual(self.generate('2026-11').status_code,302)
        self.assertEqual(self.m['bill'].query.filter_by(month='2026-11').one().total,150000)
        self.save(effective='2026-11',discount_1='1900');self.assertEqual(bill.total,120000)
        self.assertEqual(self.save(effective='2026-08').status_code,422)
    def test_atomic_batch_invalid_student_plan(self):
        self.save();other=Student(admission_no='EMPTY',name='No Plan',status='Active');db.session.add(other);db.session.commit()
        self.assertEqual(self.generate(student_ids=[str(self.s.id),str(other.id)]).status_code,422)
        self.assertEqual(self.m['bill'].query.count(),0)
    def test_pre_effective_plan_and_existing_bill_guard(self):
        self.save();self.assertEqual(self.generate('2026-08').status_code,422)
        db.session.add(self.m['bill'](student_id=self.s.id,month='2026-09',due=date(2026,9,10),lines=[dict(particular='Legacy',amount=500)]));db.session.commit()
        self.assertEqual(self.generate().status_code,422);self.assertEqual(self.m['bill'].query.count(),1)
    def test_old_generator_cannot_bypass_student_discounts(self):
        self.save();master=self.m['workflow'].query.filter_by(kind='fee-plans').first()
        r=self.c.post('/workspace/generate-challans',data=dict(_csrf=self.csrf,plan_id=master.id,month='2026-09',student_ids=str(self.s.id)))
        self.assertEqual(r.status_code,422);self.assertEqual(self.m['bill'].query.count(),0)
    def test_csrf_missing_and_cross_student_view(self):
        self.assertEqual(self.c.post(f'/workspace/student-fee-plans/{self.s.id}/edit',data=self.form()).status_code,400)
        self.save();other=Student(admission_no='OTHER',name='Other Pupil',status='Active');db.session.add(other);db.session.commit()
        self.assertEqual(self.c.get(f'/workspace/student-fee-plans/{other.id}?plan_id={self.P.query.one().id}').status_code,404)
    def test_scoped_schedules_and_all_pages_render(self):
        master=self.m['workflow'].query.first();master.data={**master.data,'campus':'Different Campus'};db.session.commit()
        r=self.save(discount_0='0');self.assertEqual(r.status_code,302)
        self.assertEqual(self.P.query.one().data['lines'][0]['actual'],0)
        for path in ['', '?mode=update', '/generate',f'/{self.s.id}/edit']:
            self.assertEqual(self.c.get('/workspace/student-fee-plans'+path).status_code,200,path)

    def test_increment_uses_discounted_fee_and_same_period_does_not_compound(self):
        self.assertEqual(self.save(percentage='10',discount_1='1500').status_code,302)
        line=self.P.query.one().data['lines'][1]
        self.assertEqual((line['base_actual'],line['discount'],line['base_net'],line['increment'],line['actual'],line['net']),(350000,150000,200000,20000,370000,220000))
        self.assertEqual(self.save(percentage='10',discount_1='1500').status_code,302)
        self.assertEqual(self.P.query.one().data['lines'][1]['net'],220000)
        self.generate();bill=self.m['bill'].query.one();self.assertEqual(bill.total,220000)
        self.assertEqual(self.save(effective='2027-09',percentage='10',discount_1='1500').status_code,302)
        future=self.P.query.filter_by(effective='2027-09').one();self.assertEqual(future.data['lines'][1]['net'],242000)
        self.assertEqual(bill.total,220000)
    def test_increment_rounding_and_excludes_arrears(self):
        self.save(percentage='50',discount_1='3499.99',arrears_1='100')
        line=self.P.query.one().data['lines'][1];self.assertEqual((line['net'],line['increment'],line['arrears']),(2,1,10000))
