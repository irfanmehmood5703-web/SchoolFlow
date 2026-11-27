"""Roster totals are inclusive, scoped, validated and consumed exactly once by payroll."""
import os,re,unittest
from datetime import date
os.environ['DATABASE_URL']='sqlite:///:memory:'
from app import app,db,Employee
from monthly_attendance import KIND,STATUSES
from payroll_calendar import month_dates

class MonthlyStaffRosterTests(unittest.TestCase):
    def setUp(self):
        app.config.update(TESTING=True,IDENTITY_ENFORCE_IN_TESTS=False,SECRET_KEY='monthly-staff-roster-test')
        self.ctx=app.app_context();self.ctx.push();db.drop_all();db.create_all()
        self.ops=app.extensions['ops_models'];self.rm=app.extensions['record_models']
        self.W=self.ops['workflow'];self.D=self.ops['daily'];self.S=self.ops['salary']
        self.e=Employee(name='Fictional Monthly Teacher',employee_no='M1',role='Teacher',status='Active')
        self.other=Employee(name='Fictional Cleaner',employee_no='M2',role='Cleaner',status='Active')
        db.session.add_all([self.e,self.other]);db.session.flush()
        self.detail=self.rm['employee'](employee_id=self.e.id,data=dict(campus='Campus A',department='Academics',designation_group='Teaching',joining_date='2026-09-01'))
        db.session.add_all([self.detail,self.rm['employee'](employee_id=self.other.id,data=dict(campus='Campus B',department='Cleaning & Maintenance',designation_group='Support Staff',joining_date='2026-09-01')),
            self.rm['settings'](category='campus',value='Campus A',class_name=''),self.rm['settings'](category='campus',value='Campus B',class_name='')])
        self.plan=self.W(kind='salary-plans',status='Approved',data=dict(employee_id=str(self.e.id),basic=2200000,security_return=0,security_payment=0,
            incentive_per_lecture=10000,annual_increment=0,bonus_amount=0,lecture_wise=False,lecture_incentive=True,rules=[
                dict(status=s,allowed=1 if s=='Leave' else 0,type='Percent',amount=a,frequency='Recursive',jump=0,limit=0)
                for s,a in [('Absent',10000),('Late',2500),('Leave',10000)]]))
        db.session.add(self.plan)
        self.calendar=app.extensions['payroll_calendar_model'](month='2026-09',working_dates=[d.isoformat() for d in month_dates('2026-09') if d.weekday()<5])
        db.session.add(self.calendar);db.session.commit()
        self.c=app.test_client();self.path='/workspace/core/hrm/monthly-attendance'
        self.c.get(self.path)
        with self.c.session_transaction() as sess:self.csrf=sess['record_csrf']
    def tearDown(self):db.session.remove();db.drop_all();self.ctx.pop()
    def page(self,extra=''):
        return self.c.get(self.path+'?month=2026-09&view=summary'+extra)
    def params(self,employee=None,counts=None,lectures=0,notes='',extra=''):
        e=employee or self.e;page=self.page(extra)
        self.assertEqual(page.status_code,200)
        revision=re.search(rb'name="revision_'+str(e.id).encode()+rb'" value="([a-f0-9]+)"',page.data)[1].decode()
        data=dict(_csrf=self.csrf,view='summary',month='2026-09',page='1',employee_ids=str(e.id),**{'revision_'+str(e.id):revision,'lectures_'+str(e.id):str(lectures),'notes_'+str(e.id):notes})
        data.update({'count_'+str(i)+'_'+str(e.id):str((counts or {}).get(s,0)) for i,s in enumerate(STATUSES)})
        return data
    def generate(self):
        return self.c.post('/workspace/payroll',data=dict(_csrf=self.csrf,action='generate',month='2026-09',employee_ids=str(self.e.id),attendance_based='on'))
    def save(self,**kw):return self.c.post(self.path,data=self.params(**kw))
    def test_roster_default_filters_and_saved_daywise_counts(self):
        db.session.add(self.D(kind='staff',person_id=self.e.id,day=date(2026,9,1),status='Absent',time_in='08:00',lectures=2));db.session.commit()
        page=self.c.get(self.path+'?month=2026-09')
        self.assertEqual(page.status_code,200)
        for name in (b'Fictional Monthly Teacher',b'Fictional Cleaner',b'Day-wise attendance',b'Total lectures',b'Notes (internal)'):
            self.assertIn(name,page.data)
        self.assertNotIn(b'Sandwich Leave',page.data)
        self.assertIn(b'<th class="monthly-designation-group" scope="col">Designation Group</th>',page.data)
        self.assertIn(b'<td class="monthly-designation-group">Support Staff</td>',page.data)
        self.assertIn(f'name="count_1_{self.e.id}" value="1"'.encode(),page.data)
        self.assertNotIn(b'Fictional Cleaner',self.page('&campus=Campus+A').data.split(b'<tbody>')[1])
        self.assertEqual(self.W.query.filter_by(kind=KIND).count(),0)
        old=self.c.get(self.path+f'?month=2026-09&employee_id={self.e.id}').data
        self.assertIn(b'name="status_2026-09-01"',old)
    def test_inclusive_monthly_counts_precedence_and_lecture_incentive(self):
        db.session.add(self.D(kind='staff',person_id=self.e.id,day=date(2026,9,1),status='Absent',lectures=2,time_in='08:00'));db.session.commit()
        payload=self.params(counts={'Absent':2,'Leave':1,'Late':1},lectures=5,notes='Private payroll note')
        self.assertEqual(self.c.post(self.path,data=payload).status_code,302)
        row=self.W.query.filter_by(kind=KIND).one()
        self.assertEqual(row.data['counts']['Absent'],2);self.assertEqual(row.data['notes'],'Private payroll note')
        self.assertEqual(self.D.query.count(),1);self.assertEqual(self.D.query.one().time_in,'08:00')
        self.assertEqual(self.c.post(self.path,data=payload).status_code,422)
        self.assertEqual(self.generate().status_code,302)
        salary=self.S.query.one()
        self.assertEqual(salary.deductions,225000) # 2 x 100,000 plus 25,000 late; 1 allowed leave is free.
        self.assertEqual(salary.earnings,2250000)
        self.assertEqual(salary.detail['monthly_attendance']['counts']['Absent'],2)
        self.assertEqual(salary.detail['monthly_attendance']['lectures'],5)
        self.assertEqual(self.save(counts={'Absent':3,'Leave':2},lectures=5).status_code,302)
        self.assertEqual(salary.deductions,225000)
    def test_payroll_automatically_fetches_totals_and_preview_matches_saved_salary(self):
        payload=self.params(counts={'Absent':2,'Late':1,'Leave':1},lectures=5)
        payload['return_to']='payroll'
        response=self.c.post(self.path,data=payload)
        self.assertEqual(response.status_code,302)
        self.assertIn('/workspace/payroll?',response.location)
        page=self.c.get(response.location)
        self.assertEqual(page.status_code,200)
        self.assertIn(b'Saved monthly attendance',page.data)
        self.assertIn(b'Enter / update monthly attendance',page.data)
        self.assertIn(b'data-base-paisa="225000"',page.data)
        self.assertIn(b'data-base-paisa="2025000"',page.data)
        self.assertIn(b'data-pay-status="Absent"',page.data)
        self.assertEqual(self.S.query.count(),0)
        self.assertIn(b'Fictional Monthly Teacher',page.data)
        self.assertNotIn(b'Fictional Cleaner',self.c.get('/workspace/payroll?month=2026-09&campus=Campus+A').data.split(b'<tbody>')[1])
        token=re.search(rb'name="preview_'+str(self.e.id).encode()+rb'" value="([a-f0-9]+)"',page.data)[1].decode()
        data=dict(_csrf=self.csrf,month='2026-09',action='generate',employee_ids=str(self.e.id),attendance_based='on',reviewed_preview='1',**{'preview_'+str(self.e.id):token})
        self.assertEqual(self.c.post('/workspace/payroll',data=data).status_code,302)
        salary=self.S.query.one()
        self.assertEqual((salary.deductions,salary.net),(225000,2025000))
        self.assertIn(b'Already generated',self.c.get('/workspace/payroll?month=2026-09').data)

    def test_payroll_rejects_preview_when_monthly_counts_change(self):
        self.assertEqual(self.save(counts={'Absent':1,'Late':1,'Leave':1}).status_code,302)
        page=self.c.get('/workspace/payroll?month=2026-09')
        token=re.search(rb'name="preview_'+str(self.e.id).encode()+rb'" value="([a-f0-9]+)"',page.data)[1].decode()
        self.assertEqual(self.save(counts={'Absent':2,'Late':1,'Leave':1}).status_code,302)
        data=dict(_csrf=self.csrf,month='2026-09',action='generate',employee_ids=str(self.e.id),attendance_based='on',reviewed_preview='1',**{'preview_'+str(self.e.id):token})
        response=self.c.post('/workspace/payroll',data=data)
        self.assertEqual(response.status_code,422)
        self.assertIn(b'Salary preview changed',response.data)
        self.assertEqual(self.S.query.count(),0)

    def test_invalid_totals_and_stale_daily_or_calendar_require_review(self):
        db.session.add(self.D(kind='staff',person_id=self.e.id,day=date(2026,9,1),status='Absent'));db.session.commit()
        self.assertEqual(self.save(counts={'Absent':0}).status_code,422)
        self.assertEqual(self.save(counts={'Absent':23}).status_code,422)
        self.assertEqual(self.save(counts={'Absent':2},lectures=-1).status_code,422)
        self.assertEqual(self.W.query.filter_by(kind=KIND).count(),0)
        self.assertEqual(self.save(counts={'Absent':2}).status_code,302)
        self.D.query.one().status='Late';db.session.commit()
        self.assertIn(b'Review required',self.page().data)
        self.assertEqual(self.generate().status_code,422);self.assertEqual(self.S.query.count(),0)
        self.assertEqual(self.save(counts={'Absent':1,'Late':1}).status_code,302)
        self.calendar.working_dates=self.calendar.working_dates[1:];db.session.commit()
        self.assertEqual(self.generate().status_code,422)
        self.assertEqual(self.S.query.count(),0)
    def test_bulk_save_is_atomic_and_monthly_present_does_not_invent_bonus_days(self):
        from werkzeug.datastructures import MultiDict
        first=self.params(counts={'Present':22})
        second=self.params(employee=self.other,counts={'Absent':23})
        data=MultiDict(first)
        data.add('employee_ids',str(self.other.id))
        for k,v in second.items():
            if k.startswith(('revision_','count_','lectures_','notes_')):data.add(k,v)
        self.assertEqual(self.c.post(self.path,data=data).status_code,422)
        self.assertEqual(self.W.query.filter_by(kind=KIND).count(),0)
        data.setlist('count_1_'+str(self.other.id),['1'])
        self.assertEqual(self.c.post(self.path,data=data).status_code,302)
        self.assertEqual(self.W.query.filter_by(kind=KIND).count(),2)
        self.assertEqual(self.D.query.count(),0)
        self.plan.data={**self.plan.data,'all_present_bonus':True};db.session.commit()
        self.assertEqual(self.generate().status_code,302)
        self.assertFalse(self.S.query.one().detail['all_present_bonus']['qualified'])
    def test_selected_rows_filters_lock_and_joining_limits_are_enforced(self):
        data=self.params(counts={'Absent':1})
        data.update(campus='Campus B')
        self.assertEqual(self.c.post(self.path,data=data).status_code,422)
        self.detail.data={**self.detail.data,'joining_date':'2026-10-01'};db.session.commit()
        self.assertEqual(self.save(counts={'Absent':1}).status_code,422)
        self.detail.data={**self.detail.data,'joining_date':'2026-09-30'};db.session.commit()
        self.assertEqual(self.save(counts={'Absent':2}).status_code,422)
        self.assertEqual(self.c.post('/workspace/core/hrm/attendance-lock',data=dict(_csrf=self.csrf,version='0',daily='2026-09-30',monthly='')).status_code,302)
        self.assertEqual(self.save(counts={'Absent':1}).status_code,422)
        self.assertEqual(self.W.query.filter_by(kind=KIND).count(),0)
