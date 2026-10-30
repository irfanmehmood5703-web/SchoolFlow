"""Payroll eligibility and reports over saved salary snapshots."""
import os,unittest
from datetime import date
os.environ['DATABASE_URL']='sqlite:///:memory:'
from app import app,db,Employee

class HrmReportTests(unittest.TestCase):
    def setUp(self):
        app.config.update(TESTING=True,SECRET_KEY='hrm-test');self.ctx=app.app_context();self.ctx.push();db.drop_all();db.create_all()
        self.m=app.extensions['ops_models'];self.rm=app.extensions['record_models']
        self.e=Employee(employee_no='TEST-HRM',name='Fictional HRM Teacher',role='Teacher',status='Active');db.session.add(self.e);db.session.flush()
        self.detail=self.rm['employee'](employee_id=self.e.id,data=dict(joining_date='2026-01-01',campus='Demo Campus'));db.session.add(self.detail)
        self.plan=self.m['workflow'](kind='salary-plans',status='Approved',data=dict(employee_id=str(self.e.id),basic=1000000,security_payment=0,security_return=0,incentive_per_lecture=0,annual_increment=0,bonus_amount=0,rules=[],lecture_wise=False))
        db.session.add(self.plan);db.session.commit();self.c=app.test_client();self.c.get('/workspace/dashboard')
        with self.c.session_transaction() as sess:self.csrf=sess['record_csrf']
    def tearDown(self):db.session.remove();db.drop_all();self.ctx.pop()
    def generate(self,**changes):
        return self.c.post('/workspace/payroll',data=dict(_csrf=self.csrf,action='generate',month='2026-09',employee_ids=str(self.e.id),**changes))
    def report(self,view='salary-report',query=''):
        return self.c.get('/workspace/hrm-reports/'+view+'?from=2026-09&to=2026-10'+query)
    def test_joining_date_missing_future_midmonth_rejected(self):
        for joining in ['', '2026-10-01','2026-09-15']:
            self.detail.data={**self.detail.data,'joining_date':joining};db.session.commit()
            self.assertEqual(self.generate().status_code,422,joining);self.assertEqual(self.m['salary'].query.count(),0)
        self.detail.data={**self.detail.data,'joining_date':'2026-09-01'};db.session.commit()
        self.assertEqual(self.generate().status_code,302);self.assertEqual(self.m['salary'].query.one().detail['joining_date'],'2026-09-01')
    def test_missing_plan_in_batch_does_not_generate_partial_payroll(self):
        other=Employee(employee_no='NO-PLAN',name='No Plan',status='Active');db.session.add(other);db.session.commit()
        r=self.c.post('/workspace/payroll',data=dict(_csrf=self.csrf,action='generate',month='2026-09',employee_ids=[str(self.e.id),str(other.id)]))
        self.assertEqual(r.status_code,422);self.assertEqual(self.m['salary'].query.count(),0)
    def lecture_setup(self):
        self.plan.data={**self.plan.data,'lecture_wise':True,'include_plan_earnings':False}
        self.entry=self.m['workflow'](kind='lecture-register',status='Approved',data=dict(employee_id=str(self.e.id),date='2026-09-20',lectures='3',class_name='One',section='A',subject='Math',rate_override='150'))
        db.session.add(self.entry);db.session.commit()
    def test_lecture_report_uses_saved_details_even_after_source_change(self):
        self.lecture_setup();self.assertEqual(self.generate().status_code,302)
        salary=self.m['salary'].query.one();self.assertEqual(salary.net,45000)
        self.entry.data={**self.entry.data,'lectures':'99','rate_override':'999'};db.session.commit()
        csv=self.report('lecture-report','&export=csv').data.decode();self.assertIn('3,450.00,450.00,0.00,450.00,Unpaid',csv)
        detail=self.c.get(f'/workspace/hrm-reports/salary/{salary.id}');self.assertEqual(detail.status_code,200)
        self.assertIn(b'450.00',detail.data);self.assertNotIn(b'99,999',detail.data)
    def test_lecture_joining_midmonth_only_actual_postjoining_lectures(self):
        self.lecture_setup();self.detail.data={**self.detail.data,'joining_date':'2026-09-15'};db.session.commit()
        self.entry.data={**self.entry.data,'date':'2026-09-10'};db.session.commit()
        self.assertEqual(self.generate().status_code,422);self.assertEqual(self.m['salary'].query.count(),0)
        self.entry.data={**self.entry.data,'date':'2026-09-20'};db.session.commit();self.assertEqual(self.generate().status_code,302)
    def test_employee_totals_status_campus_filters_and_csv_safety(self):
        self.generate();sep=self.m['salary'].query.one()
        oct=self.m['salary'](employee_id=self.e.id,month='2026-10',earnings=1100000,deductions=100000,net=1000000,paid=1000000,detail=dict(basic=1100000));db.session.add(oct);db.session.commit()
        text=self.report(query='&export=csv').data.decode();self.assertIn('2,21000.00,1000.00,20000.00,10000.00,10000.00',text)
        self.assertNotIn(self.e.name,self.report(query='&campus=Other&export=csv').data.decode())
        unpaid=self.report(query='&status=Unpaid&export=csv').data.decode();self.assertIn('1,10000.00,0.00,10000.00,0.00,10000.00',unpaid)
        self.e.name='=Unsafe CSV Name';db.session.commit();self.assertIn("'=Unsafe CSV Name",self.report(query='&export=csv').data.decode())
    def test_legacy_lecture_count_not_invented_and_invalid_filters(self):
        self.generate();salary=self.m['salary'].query.one();salary.detail={**salary.detail,'plan':{'lecture_wise':True},'lecture_pay':1000000};salary.detail={k:v for k,v in salary.detail.items() if k!='lecture_details'};db.session.commit()
        self.assertIn(b'Not captured',self.report('lecture-report').data)
        self.assertEqual(self.c.get(f'/workspace/hrm-reports/salary/{salary.id}').status_code,200)
        for suffix in ['&status=Invalid','&employee_id=bad','&status=Invalid','&employee_id=9999']:
            self.assertEqual(self.report(query=suffix).status_code,422,suffix)
        self.assertEqual(self.c.get('/workspace/hrm-reports/salary-report?from=bad').status_code,422)
        self.assertEqual(self.c.get('/workspace/hrm-reports/salary-report?from=2026-10&to=2026-09').status_code,422)
        self.assertEqual(self.c.get('/workspace/hrm-reports/salary/9999').status_code,404)
