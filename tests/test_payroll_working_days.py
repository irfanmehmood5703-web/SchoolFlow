"""School-confirmed working-day proration and optional manual salary increases."""
import os,unittest,json,tempfile,stat
from datetime import date
from pathlib import Path
from werkzeug.security import check_password_hash
os.environ['DATABASE_URL']='sqlite:///:memory:'
from app import app,db,Employee
from payroll_calendar import month_dates,joining_pay


class WorkingPayrollTests(unittest.TestCase):
    def setUp(self):
        app.config.update(TESTING=True,SECRET_KEY='working-pay-test',IDENTITY_ENFORCE_IN_TESTS=False)
        self.ctx=app.app_context();self.ctx.push();db.drop_all();db.create_all()
        self.m=app.extensions['ops_models'];self.rm=app.extensions['record_models'];self.cal=app.extensions['payroll_calendar_model']
        self.e=Employee(employee_no='WORK-1',name='Fictional Working Teacher',status='Active');db.session.add(self.e);db.session.flush()
        self.details=self.rm['employee'](employee_id=self.e.id,data={'joining_date':'2026-09-15'})
        self.plan=self.m['workflow'](kind='salary-plans',status='Approved',data=dict(employee_id=str(self.e.id),basic=2200000,security_return=0,security_payment=0,incentive_per_lecture=0,annual_increment=0,bonus_amount=0,lecture_wise=False,rules=[],apply_manual_increments=False))
        db.session.add_all([self.details,self.plan]);db.session.commit()
        self.c=app.test_client();self.c.get('/workspace/payroll-calendar?month=2026-09')
        with self.c.session_transaction() as sess:self.csrf=sess['record_csrf']
        self.dates=[d.isoformat() for d in month_dates('2026-09') if d.weekday()<5]

    def tearDown(self):db.session.remove();db.drop_all();self.ctx.pop()
    def calendar(self,dates=None):
        row=self.cal(month='2026-09',working_dates=dates or self.dates);db.session.add(row);db.session.commit();return row
    def generate(self,**changes):
        data=dict(_csrf=self.csrf,action='generate',month='2026-09',employee_ids=str(self.e.id));data.update(changes)
        return self.c.post('/workspace/payroll',data=data)
    def increment(self,amount='2200',effective='2026-09',status='Approved',employee=None):
        row=self.m['workflow'](kind='increments',status=status,data=dict(employee_id=str(employee or self.e.id),amount=amount,effective=effective,reason='Manual test increase'))
        db.session.add(row);db.session.commit();return row

    def test_calendar_save_csrf_invalid_dates_and_stale_version(self):
        self.assertEqual(self.cal.query.count(),0)
        self.assertEqual(self.c.post('/workspace/payroll-calendar',data={'month':'2026-09'}).status_code,400)
        for dates in [[],['2026-10-01'],['2026-09-01','2026-09-01']]:
            self.assertEqual(self.c.post('/workspace/payroll-calendar',data=dict(_csrf=self.csrf,month='2026-09',version='0',working_dates=dates)).status_code,422)
        data=dict(_csrf=self.csrf,month='2026-09',version='0',working_dates=self.dates)
        self.assertEqual(self.c.post('/workspace/payroll-calendar',data=data).status_code,302)
        self.assertEqual(self.cal.query.one().working_dates,self.dates)
        self.assertEqual(self.c.post('/workspace/payroll-calendar',data=data).status_code,422)
        self.assertEqual(self.c.get('/workspace/payroll-calendar?month=bad').status_code,422)

    def test_working_day_formula_weekend_holiday_zero_days_and_rounding(self):
        result=joining_pay('2026-09',date(2026,9,15),2200000,self.dates)
        self.assertEqual((result['total_working_days'],result['eligible_working_days'],result['payable_basic']),(22,12,1200000))
        without_holiday=[d for d in self.dates if d!='2026-09-16']
        result=joining_pay('2026-09',date(2026,9,15),2100001,without_holiday)
        self.assertEqual((result['total_working_days'],result['eligible_working_days'],result['payable_basic']),(21,11,1100001))
        self.assertEqual(joining_pay('2026-09',date(2026,9,26),2200000,self.dates)['payable_basic'],300000)
        self.assertEqual(joining_pay('2026-09',date(2026,9,30),100,self.dates[:10])['payable_basic'],0)

    def test_midmonth_requires_calendar_then_generates_immutable_snapshot(self):
        self.assertEqual(self.generate().status_code,422);self.assertEqual(self.m['salary'].query.count(),0)
        calendar=self.calendar();self.assertEqual(self.generate().status_code,302)
        salary=self.m['salary'].query.one();self.assertEqual(salary.net,1200000)
        self.assertEqual(salary.detail['proration']['eligible_working_days'],12)
        calendar.working_dates=self.dates[:5];self.plan.data={**self.plan.data,'basic':9999999};db.session.commit()
        self.generate();self.assertEqual(self.m['salary'].query.count(),1);self.assertEqual(salary.net,1200000)
        self.assertEqual(len(salary.detail['working_calendar']['working_dates']),22)
        page=self.c.get(f'/workspace/hrm-reports/salary/{salary.id}');self.assertIn(b'Working-day joining calculation',page.data)

    def test_attendance_deductions_ignore_prejoining_and_nonworking_dates(self):
        self.calendar();self.plan.data={**self.plan.data,'rules':[dict(status='Absent',allowed=0,type='Percent',amount=10000,frequency='Recursive',jump=0,limit=0)]}
        for n in [2,17,19]:db.session.add(self.m['daily'](kind='staff',person_id=self.e.id,day=date(2026,9,n),status='Absent'))
        db.session.commit();self.assertEqual(self.generate(attendance_based='on').status_code,302)
        salary=self.m['salary'].query.one();self.assertEqual((salary.earnings,salary.deductions,salary.net),(1200000,100000,1100000))
        self.assertEqual(salary.detail['attendance'][0]['count'],1)

    def test_manual_increment_is_optional_selected_approved_and_effective(self):
        self.calendar();self.increment('1000','2026-06');self.increment('1200','2026-09')
        self.increment('5000','2026-10');self.increment('7000',status='Pending');self.increment('9000',employee=999)
        self.plan.data={**self.plan.data,'apply_manual_increments':True};db.session.commit()
        self.assertEqual(self.generate().status_code,302)
        salary=self.m['salary'].query.one()
        self.assertEqual(salary.detail['monthly_basic'],2420000);self.assertEqual(salary.net,1320000)
        self.assertEqual(len(salary.detail['manual_increments']),2)
        self.assertEqual(self.plan.data['basic'],2200000)
        self.assertEqual(self.generate().status_code,302);self.assertEqual(self.m['salary'].query.count(),1)

    def test_increment_does_not_apply_when_employee_plan_option_is_off(self):
        self.calendar();self.increment()
        self.assertEqual(self.generate().status_code,302)
        salary=self.m['salary'].query.one();self.assertEqual(salary.net,1200000);self.assertEqual(salary.detail['manual_increments'],[])

    def test_increment_is_not_compounded_and_used_source_cannot_be_cancelled(self):
        self.details.data={'joining_date':'2026-01-01'};self.plan.data={**self.plan.data,'apply_manual_increments':True};db.session.commit()
        inc=self.increment()
        self.assertEqual(self.generate().status_code,302)
        self.assertEqual(self.generate(month='2026-08').status_code,302)
        salaries={s.month:s for s in self.m['salary'].query.all()}
        self.assertEqual(salaries['2026-08'].net,2200000);self.assertEqual(salaries['2026-09'].net,2420000)
        response=self.c.post('/workspace/register/increments',data=dict(_csrf=self.csrf,action='reject',ids=str(inc.id)))
        self.assertEqual(response.status_code,422);self.assertEqual(inc.status,'Approved')

    def test_increment_form_requires_positive_amount_and_approval(self):
        data=dict(_csrf=self.csrf,employee_id=str(self.e.id),effective='2026-09',reason='Test',amount='0',increment_token='working_increment_test_token')
        self.assertEqual(self.c.post('/workspace/register/increments',data=data).status_code,422)
        data['amount']='1750.50';self.assertEqual(self.c.post('/workspace/register/increments',data=data).status_code,302)
        self.assertEqual(self.c.post('/workspace/register/increments',data=data).status_code,302)
        inc=self.m['workflow'].query.filter_by(kind='increments').one();self.assertEqual(inc.status,'Pending')
        self.assertEqual(self.c.post('/workspace/register/increments',data=dict(_csrf=self.csrf,action='approve',ids=str(inc.id))).status_code,302)
        self.assertEqual(inc.status,'Approved')

    def test_salary_plan_saves_optional_increment_flag_without_fixed_amount(self):
        response=self.c.post('/workspace/salary-plans',data=dict(_csrf=self.csrf,employee_id=str(self.e.id),basic='22000',apply_manual_increments='on'))
        self.assertEqual(response.status_code,302)
        latest=self.m['workflow'].query.filter_by(kind='salary-plans').order_by(self.m['workflow'].id.desc()).first()
        self.assertTrue(latest.data['apply_manual_increments']);self.assertEqual(latest.data['annual_increment'],0)
        self.assertEqual(latest.status,'Pending')
        page=self.c.get('/workspace/salary-plans').data
        self.assertIn(b'Apply approved manual salary increments',page);self.assertNotIn(b'Annual Increment Amount',page)

    def test_calendar_missing_for_later_employee_rolls_back_whole_batch(self):
        other=Employee(employee_no='WORK-2',name='Second test employee',status='Active');db.session.add(other);db.session.flush()
        db.session.add(self.rm['employee'](employee_id=other.id,data={'joining_date':'2026-01-01'}))
        db.session.add(self.m['workflow'](kind='salary-plans',status='Approved',data={**self.plan.data,'employee_id':str(other.id)}));db.session.commit()
        self.assertEqual(self.generate(employee_ids=[str(other.id),str(self.e.id)]).status_code,422)
        self.assertEqual(self.m['salary'].query.count(),0)

    def test_vendor_generated_client_credentials_are_private_and_do_not_create_mailbox(self):
        with tempfile.TemporaryDirectory() as directory:
            app.config['INSTITUTE_DATABASE_DIR']=directory
            path=Path(directory)/'client-credentials.json'
            result=app.test_cli_runner().invoke(args=['institute-create-generated','--code','CLIENT-123','--name','Fictional Client School','--credentials-file',str(path)])
            self.assertEqual(result.exit_code,0,result.output)
            data=json.loads(path.read_text());self.assertEqual(data['school_name'],'Fictional Client School')
            self.assertFalse(data['mailbox_created']);self.assertTrue(len(data['password'])>=24)
            self.assertEqual(stat.S_IMODE(path.stat().st_mode),0o600)
            self.assertNotIn(data['password'],result.output)
            owner=app.extensions['identity_models']['owner'].query.one()
            self.assertTrue(check_password_hash(owner.password_hash,data['password']))
            retry=app.test_cli_runner().invoke(args=['institute-create-generated','--code','CLIENT-456','--name','Other Test','--credentials-file',str(path)])
            self.assertNotEqual(retry.exit_code,0)
            app.config['INSTITUTE_DATABASE_DIR']=None


if __name__=='__main__':unittest.main()
