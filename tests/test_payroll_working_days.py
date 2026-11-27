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

    def test_new_month_defaults_to_all_monday_through_saturday_dates_and_paid_sundays(self):
        import re
        page=self.c.get('/workspace/payroll-calendar?month=2026-09').data.decode()
        selected=re.findall(r'name="working_dates" value="([^"]+)" data-weekday="\d" checked',page)
        expected=[d.isoformat() for d in month_dates('2026-09') if d.weekday()!=6]
        self.assertEqual(selected,expected)
        self.assertEqual(self.cal.query.count(),0)
        self.calendar(self.dates)
        page=self.c.get('/workspace/payroll-calendar?month=2026-09').data.decode()
        selected=re.findall(r'name="working_dates" value="([^"]+)" data-weekday="\d" checked',page)
        self.assertEqual(selected,self.dates)

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

    def test_paid_calendar_days_keep_sundays_paid_and_personal_leave_configurable(self):
        form=dict(_csrf=self.csrf,month='2026-09',version='0',working_dates=self.dates,pay_basis='calendar_days')
        page=self.c.get('/workspace/payroll-calendar?month=2026-09').data
        self.assertIn(b'All calendar days (paid Sundays',page)
        self.assertIn(b'value="calendar_days" checked',page)
        self.assertEqual(self.c.post('/workspace/payroll-calendar',data={**form,'pay_basis':'invalid'}).status_code,422)
        self.assertEqual(self.cal.query.count(),0)
        self.assertEqual(self.c.post('/workspace/payroll-calendar',data=form).status_code,302)
        self.assertEqual(app.extensions['payroll_calendar_helpers']['pay_basis']('2026-09'),'calendar_days')
        rule=dict(type='Percent',amount=10000,frequency='Recursive',jump=0,limit=0)
        self.plan.data={**self.plan.data,'basic':3000000,'rules':[
            dict(rule,status='Absent',allowed=0),dict(rule,status='Leave',allowed=1),
            dict(rule,status='Late',allowed=0,amount=2500)]}
        for n,status in [(17,'Absent'),(18,'Leave'),(20,'Absent'),(21,'Late')]:
            db.session.add(self.m['daily'](kind='staff',person_id=self.e.id,day=date(2026,9,n),status=status))
        db.session.commit()
        self.assertEqual(self.generate(attendance_based='on').status_code,302)
        salary=self.m['salary'].query.one()
        self.assertEqual((salary.earnings,salary.deductions,salary.net),(1600000,125000,1475000))
        self.assertEqual(salary.detail['proration']['eligible_paid_days'],16)
        self.assertEqual(salary.detail['proration']['total_paid_days'],30)
        self.assertEqual(salary.detail['proration']['eligible_working_days'],12)
        self.assertEqual(salary.detail['working_calendar']['salary_divisor_days'],30)
        deductions={r['status']:r for r in salary.detail['attendance']}
        self.assertEqual(deductions['Absent']['count'],1)
        self.assertEqual(deductions['Leave']['count'],1)
        self.assertEqual(deductions['Leave']['amount'],0)
        self.assertIn(b'Paid calendar-day joining calculation',self.c.get(f'/workspace/hrm-reports/salary/{salary.id}').data)
        saved=self.cal.query.one();version=saved.version
        self.assertEqual(self.c.post('/workspace/payroll-calendar',data={**form,'version':version,'pay_basis':'working_days'}).status_code,302)
        self.assertGreater(saved.version,version)
        self.assertEqual(self.c.post('/workspace/payroll-calendar',data={**form,'version':version}).status_code,422)
        self.assertEqual(salary.detail['working_calendar']['pay_basis'],'calendar_days')
        self.assertEqual(salary.net,1475000)

    def test_paid_calendar_days_excess_leave_and_fixed_late_deduction(self):
        self.details.data={'joining_date':'2026-01-01'}
        self.plan.data={**self.plan.data,'basic':3000000,'rules':[
            dict(status='Leave',allowed=1,type='Percent',amount=10000,frequency='Recursive',jump=0,limit=0),
            dict(status='Late',allowed=0,type='Abs',amount=20000,frequency='Recursive',jump=0,limit=0)]}
        for n,status in [(17,'Leave'),(18,'Leave'),(21,'Late')]:
            db.session.add(self.m['daily'](kind='staff',person_id=self.e.id,day=date(2026,9,n),status=status))
        db.session.commit()
        form=dict(_csrf=self.csrf,month='2026-09',version='0',working_dates=self.dates,pay_basis='calendar_days')
        self.assertEqual(self.c.post('/workspace/payroll-calendar',data=form).status_code,302)
        self.assertEqual(self.generate(attendance_based='on').status_code,302)
        salary=self.m['salary'].query.one()
        self.assertEqual((salary.earnings,salary.deductions,salary.net),(3000000,120000,2880000))

    def test_paid_calendar_bonus_does_not_require_sunday_attendance(self):
        self.bonus_attendance()
        saved=self.cal.query.one()
        form=dict(_csrf=self.csrf,month='2026-09',version=saved.version,working_dates=self.dates,pay_basis='calendar_days')
        self.assertEqual(self.c.post('/workspace/payroll-calendar',data=form).status_code,302)
        self.assertEqual(self.generate().status_code,302)
        salary=self.m['salary'].query.one()
        bonus=salary.detail['all_present_bonus']
        self.assertTrue(bonus['qualified'])
        self.assertEqual(bonus['salary_divisor_days'],30)
        self.assertEqual(bonus['working_days'],22)
        self.assertEqual(bonus['amount'],80667)

    def test_fixed_30_day_rate_in_february_leap_february_and_31_day_month(self):
        self.details.data={'joining_date':'2024-01-01'}
        self.plan.data={**self.plan.data,'basic':2000000,'rules':[
            dict(status='Absent',allowed=0,type='Percent',amount=10000,frequency='Recursive',jump=0,limit=0),
            dict(status='Late',allowed=0,type='Percent',amount=2500,frequency='Recursive',jump=0,limit=0),
            dict(status='Leave',allowed=2,type='Percent',amount=10000,frequency='Recursive',jump=0,limit=0)]}
        db.session.commit()
        for month,actual in [('2024-02',29),('2026-02',28),('2026-09',30),('2026-10',31)]:
            with self.subTest(month=month):
                dates=month_dates(month)
                working=[d for d in dates if d.weekday()!=6]
                form=dict(_csrf=self.csrf,month=month,version='0',working_dates=[d.isoformat() for d in working],pay_basis='calendar_days')
                self.assertEqual(self.c.post('/workspace/payroll-calendar',data=form).status_code,302)
                page=self.c.get('/workspace/payroll-calendar?month='+month).data
                self.assertIn(b'data-fixed-salary-days="30">30</strong>',page)
                self.assertEqual(page.count(b'name="working_dates"'),actual)
                for d,status in zip(working,['Absent','Late','Leave','Leave']):
                    db.session.add(self.m['daily'](kind='staff',person_id=self.e.id,day=d,status=status))
                db.session.commit()
                self.assertEqual(self.generate(month=month,attendance_based='on').status_code,302)
                salary=self.m['salary'].query.filter_by(month=month).one()
                self.assertEqual(salary.earnings,2000000)
                self.assertEqual(salary.detail['salary_divisor_days'],30)
                self.assertEqual(len(salary.detail['working_calendar']['paid_dates']),actual)
                deductions={r['status']:r['amount'] for r in salary.detail['attendance']}
                self.assertEqual(deductions,{'Absent':66667,'Late':16667,'Leave':0})
                self.assertEqual(salary.net,1916666)

    def test_fixed_30_day_bonus_and_full_basic_across_month_lengths(self):
        self.details.data={'joining_date':'2026-01-01'}
        self.plan.data={**self.plan.data,'basic':3000000,'all_present_bonus':True}
        db.session.commit()
        for month in ['2026-02','2026-09','2026-10']:
            working=[d for d in month_dates(month) if d.weekday()!=6]
            form=dict(_csrf=self.csrf,month=month,version='0',working_dates=[d.isoformat() for d in working],pay_basis='calendar_days')
            self.assertEqual(self.c.post('/workspace/payroll-calendar',data=form).status_code,302)
            for d in working:
                db.session.add(self.m['daily'](kind='staff',person_id=self.e.id,day=d,status='Present'))
            db.session.commit()
            self.assertEqual(self.generate(month=month).status_code,302)
            salary=self.m['salary'].query.filter_by(month=month).one()
            self.assertEqual(salary.detail['all_present_bonus']['amount'],100000)
            self.assertEqual(salary.detail['all_present_bonus']['salary_divisor_days'],30)
            self.assertEqual(salary.earnings,3100000)

    def test_partial_joining_month_keeps_actual_paid_date_proration(self):
        dates=[d.isoformat() for d in month_dates('2026-10') if d.weekday()!=6]
        result=joining_pay('2026-10',date(2026,10,16),3100000,dates,'calendar_days')
        self.assertEqual(result['total_paid_days'],31)
        self.assertEqual(result['eligible_paid_days'],16)
        self.assertEqual(result['payable_basic'],1600000)

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


    def bonus_attendance(self,status=None,missing=False):
        self.calendar();self.details.data={'joining_date':'2026-01-01'}
        self.plan.data={**self.plan.data,'all_present_bonus':True,'allowances':[dict(name='Travel',amount=220000,type='Earning',bonusable=True),dict(name='Lunch',amount=100000,type='Earning',bonusable=False)]}
        for i,value in enumerate(self.dates):
            if missing and i==0:continue
            db.session.add(self.m['daily'](kind='staff',person_id=self.e.id,day=date.fromisoformat(value),status=status if i==0 and status else 'Present'))
        db.session.commit()

    def test_all_present_bonus_requires_calendar_and_complete_attendance(self):
        self.details.data={'joining_date':'2026-01-01'};self.plan.data={**self.plan.data,'all_present_bonus':True};db.session.commit()
        self.assertEqual(self.generate().status_code,422);self.assertEqual(self.m['salary'].query.count(),0)
        self.bonus_attendance(missing=True);self.assertEqual(self.generate().status_code,302)
        salary=self.m['salary'].query.one();self.assertEqual(salary.detail['all_present_bonus']['amount'],0)
        self.assertEqual(salary.detail['all_present_bonus']['missing_dates'],[self.dates[0]])

    def test_all_present_bonus_uses_only_bonusable_earnings_and_is_frozen(self):
        self.bonus_attendance();self.assertEqual(self.generate().status_code,302)
        salary=self.m['salary'].query.one();bonus=salary.detail['all_present_bonus']
        self.assertTrue(bonus['qualified']);self.assertEqual(bonus['amount'],110000);self.assertEqual(salary.earnings,2630000)
        row=self.m['daily'].query.first();row.status='Short Leave';db.session.commit()
        self.assertEqual(self.generate().status_code,302);self.assertEqual(salary.detail['all_present_bonus']['amount'],110000)

    def test_short_leave_cancels_bonus_even_without_deductions(self):
        self.bonus_attendance('Short Leave');self.assertEqual(self.generate().status_code,302)
        bonus=self.m['salary'].query.one().detail['all_present_bonus'];self.assertFalse(bonus['qualified']);self.assertEqual(bonus['amount'],0)

    def test_off_day_does_not_cancel_bonus(self):
        self.bonus_attendance('Off Day');self.assertEqual(self.generate().status_code,302)
        self.assertEqual(self.m['salary'].query.one().detail['all_present_bonus']['amount'],110000)

    def test_lecture_wise_pay_does_not_also_pay_lecture_incentive_or_monthly_bonus(self):
        self.details.data={'joining_date':'2026-01-01'}
        self.plan.data={**self.plan.data,'lecture_wise':True,'lecture_incentive':True,'incentive_per_lecture':10000,'all_present_bonus':True}
        db.session.add(self.m['workflow'](kind='lecture-register',status='Approved',data=dict(employee_id=str(self.e.id),date='2026-09-10',lectures='2',rate_override='100')))
        db.session.add(self.m['daily'](kind='staff',person_id=self.e.id,day=date(2026,9,10),status='Present',lectures=2));db.session.commit()
        self.assertEqual(self.generate().status_code,302);salary=self.m['salary'].query.one()
        self.assertEqual(salary.earnings,20000);self.assertIsNone(salary.detail['all_present_bonus'])
