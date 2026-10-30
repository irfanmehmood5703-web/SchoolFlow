"""Workflow integration tests use fictional people and isolated in-memory storage."""
import os,re,unittest
from datetime import date
os.environ['DATABASE_URL']='sqlite:///:memory:'
from app import app,db,Student,Employee
from operations import money
from module_catalog import MENUS

class OperationTests(unittest.TestCase):
    def setUp(self):
        app.config.update(TESTING=True,SECRET_KEY='test-secret')
        self.ctx=app.app_context();self.ctx.push();db.drop_all();db.create_all()
        self.m=app.extensions['ops_models'];self.rm=app.extensions['record_models']
        self.s=Student(admission_no='TEST-01',name='Test Pupil',father='Test Guardian',class_name='Test Class',status='Active')
        self.e=Employee(employee_no='TEST-E01',name='Test Teacher',role='Teacher',status='Active')
        db.session.add_all([self.s,self.e]);db.session.flush();db.session.add(self.rm['employee'](employee_id=self.e.id,data={'joining_date':'2000-01-01'}));db.session.commit()
        self.client=app.test_client();self.client.get('/workspace/dashboard')
        with self.client.session_transaction() as sess:self.csrf=sess['record_csrf']
    def tearDown(self):db.session.remove();db.drop_all();self.ctx.pop()
    def post(self,path,**data):return self.client.post(path,data=dict(_csrf=self.csrf,**data))
    def bill(self,amount=100000,month='2026-09'):
        b=self.m['bill'](student_id=self.s.id,month=month,due=date(2026,9,10),lines=[dict(particular='Tuition Fee',amount=amount)])
        db.session.add(b);db.session.commit();return b
    def plan(self,**changes):
        data=dict(employee_id=str(self.e.id),basic=1000000,security_return=0,security_payment=0,incentive_per_lecture=0,annual_increment=0,bonus_amount=0,rules=[dict(status='Absent',allowed=0,type='Abs',amount=10000,frequency='Recursive',jump=0,limit=0)])
        data.update(changes);p=self.m['workflow'](kind='salary-plans',status='Approved',data=data);db.session.add(p);db.session.commit();return p
    def test_all_menu_entries_render_and_keep_order(self):
        self.assertEqual([len([x for _,items in g for x in items]) for g in MENUS.values()],[21,15,22])
        for groups in MENUS.values():
            for _,items in groups:
                for _,key in items:
                    r=self.client.get('/workspace/'+key,follow_redirects=True)
                    self.assertEqual(r.status_code,200,key)
        self.assertNotIn(b'<aside',self.client.get('/workspace/dashboard').data)
    def test_payment_discount_duplicate_guard_overpayment_and_reversal(self):
        b=self.bill();token='testtoken_abcdefghijklmnop'
        args=dict(student_id=self.s.id,bill_id=b.id,token=token,paid_date='2026-10-01',account='Cash',action='save',**{f'amount_{b.id}':'400',f'discount_{b.id}':'100'})
        self.assertEqual(self.post('/workspace/pay',**args).status_code,302)
        self.assertEqual((b.paid,b.discount,b.remaining),(40000,10000,50000))
        self.assertEqual(self.post('/workspace/pay',**args).status_code,422)
        args.update(token='newtoken_abcdefghijklmnop',**{f'amount_{b.id}':'501'})
        self.assertEqual(self.post('/workspace/pay',**args).status_code,422)
        self.assertEqual(b.remaining,50000)
        r=self.m['receipt'].query.one();self.assertEqual(self.post('/workspace/reverse-receipts',ids=str(r.id),confirm='yes').status_code,302)
        self.assertEqual(b.remaining,100000);self.assertTrue(r.voided)
    def test_atomic_multi_challan_payment(self):
        a=self.bill();b=self.bill(20000)
        r=self.post('/workspace/pay',student_id=self.s.id,mode='all',token='atomic_token_abcdefghijkl',paid_date='2026-10-01',account='Cash',**{f'amount_{a.id}':'10',f'amount_{b.id}':'201'})
        self.assertEqual(r.status_code,422);self.assertEqual(a.paid,0);self.assertEqual(self.m['receipt'].query.count(),0)
    def test_installment_preserves_combined_debt(self):
        b=self.bill();r=self.post(f'/workspace/installment/{b.id}',month='2026-11',due='2026-11-10',amount_0='300')
        self.assertEqual(r.status_code,302);self.assertEqual(sum(x.total for x in self.m['bill'].query.all()),100000)
        self.assertEqual(b.total,70000)
    def test_generate_challan_idempotent(self):
        p=self.m['workflow'](kind='fee-plans',status='Active',data=dict(name='Test plan',amount='1000',particular='Tuition',due_day='10'))
        db.session.add(p);db.session.commit()
        for _ in range(2):self.assertEqual(self.post('/workspace/generate-challans',plan_id=p.id,month='2026-09',student_ids=str(self.s.id)).status_code,302)
        self.assertEqual(self.m['bill'].query.count(),1)
    def test_attendance_upsert_invalid_rollback(self):
        for status in ['Present','Absent']:
            self.assertEqual(self.post('/workspace/attendance/student',day='2026-09-01',**{f'status_{self.s.id}':status}).status_code,302)
        self.assertEqual(self.m['daily'].query.count(),1);self.assertEqual(self.m['daily'].query.one().status,'Absent')
        self.assertEqual(self.post('/workspace/attendance/student',day='2026-09-01',**{f'status_{self.s.id}':'Invalid'}).status_code,422)
        self.assertEqual(self.m['daily'].query.one().status,'Absent')
    def test_award_marks_bounds_and_absence(self):
        r=self.post('/workspace/examination/awards',name='Test term',subject=['Math','Science'],exam_date=['2026-09-01','2026-09-02'],test_type=['Written','Oral'],total=['50','50'],teacher=[str(self.e.id),str(self.e.id)])
        self.assertEqual(r.status_code,302);p=self.m['workflow'].query.filter_by(kind='awards').one()
        self.assertEqual(self.post(f'/workspace/marks/{p.id}',**{f'mark_{self.s.id}_0':'51'}).status_code,422)
        self.assertEqual(self.m['score'].query.count(),0)
        self.assertEqual(self.post(f'/workspace/marks/{p.id}',**{f'mark_{self.s.id}_0':'45',f'state_{self.s.id}_1':'A'}).status_code,302)
        self.assertEqual(self.m['score'].query.count(),2)
        self.assertEqual(self.client.get(f'/workspace/marks/{p.id}').status_code,200)
    def test_salary_generation_duplicate_and_snapshot_pay_unpay(self):
        p=self.plan();db.session.add(self.m['daily'](kind='staff',person_id=self.e.id,day=date(2026,9,5),status='Absent'));db.session.commit()
        args=dict(month='2026-09',action='generate',employee_ids=str(self.e.id),attendance_based='on')
        for _ in range(2):self.assertEqual(self.post('/workspace/payroll',**args).status_code,302)
        s=self.m['salary'].query.one();self.assertEqual(s.net,990000)
        p.data={**p.data,'basic':2000000};db.session.commit();self.assertEqual(s.detail['basic'],1000000)
        self.assertEqual(self.post('/workspace/payroll',month='2026-09',action='pay',ids=str(s.id),paid_date='2026-10-01',credit='Cash',debit='Salary Expense').status_code,302)
        self.assertEqual(s.paid,s.net)
        self.assertEqual(self.post('/workspace/payroll',month='2026-09',action='delete',ids=str(s.id),confirm='yes').status_code,422)
        self.assertEqual(self.post('/workspace/payroll',month='2026-09',action='unpay',ids=str(s.id)).status_code,302);self.assertEqual(s.paid,0)
        for layout in ['slip','signature','report','bank']:
            self.assertEqual(self.post('/workspace/payroll',month='2026-09',action=layout,ids=str(s.id)).status_code,200)
    def test_unverified_rules_do_not_generate_invented_payroll(self):
        self.plan(sandwich_leave=True)
        self.assertEqual(self.post('/workspace/payroll',month='2026-09',action='generate',employee_ids=str(self.e.id)).status_code,422)
        self.assertEqual(self.m['salary'].query.count(),0)
    def test_lecture_import_dedup_approval_and_payment(self):
        self.plan(lecture_wise=True)
        db.session.add(self.m['workflow'](kind='lecture-rates',status='Active',data=dict(employee_id=str(self.e.id),starts='2026-09',status='Active',amount='500',class_name='',section='',subject='')))
        db.session.add(self.m['daily'](kind='staff',person_id=self.e.id,day=date(2026,9,2),status='Present',lectures=2));db.session.commit()
        for _ in range(2):self.assertEqual(self.post('/workspace/lecture-import',month='2026-09').status_code,302)
        entry=self.m['workflow'].query.filter_by(kind='lecture-register').one();self.assertEqual(entry.status,'Pending')
        self.post('/workspace/register/lecture-register',action='approve',ids=str(entry.id))
        self.assertEqual(self.post('/workspace/payroll',month='2026-09',action='generate',employee_ids=str(self.e.id)).status_code,302)
        self.assertEqual(self.m['salary'].query.one().net,100000)
    def test_csrf_messages_api_and_money(self):
        self.assertEqual(self.client.post('/workspace/payroll',data={}).status_code,400)
        self.assertEqual(self.client.get('/api/v1/summary').status_code,503)
        self.assertEqual(money('0.105'),11)
        for v in ['NaN','-1','Infinity','1e100']:
            with self.assertRaises(ValueError):money(v)
        self.assertEqual(self.post('/workspace/messages',student_ids=str(self.s.id),message='Test notice').status_code,302)
        self.assertEqual(self.m['workflow'].query.filter_by(kind='message').one().status,'Provider not configured')
    def test_family_history_print_and_batch(self):
        family=self.rm['family'](number='F-TEST',data={});db.session.add(family);db.session.flush();db.session.add(self.rm['student'](student_id=self.s.id,family_id=family.id,data={}));db.session.commit();b=self.bill()
        for path in ['/workspace/history?detail=1','/workspace/history?family_view=1','/workspace/history?family=F-TEST&detail=1','/workspace/family-payment?number=F-TEST']:
            self.assertEqual(self.client.get(path).status_code,200,path)
        for layout in ['horizontal','vertical','family']:
            self.assertEqual(self.post('/workspace/fee-action',action=layout,ids=str(b.id)).status_code,200)
        self.assertEqual(self.post('/workspace/family-payment',number='F-TEST',paid_date='2026-10-01',account='Cash',token='family_token_abcdefghijkl',**{f'amount_{b.id}':'100'}).status_code,302)
        self.assertEqual(b.paid,10000)

if __name__=='__main__':unittest.main()
