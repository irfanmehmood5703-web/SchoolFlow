"""One school-wide deduction policy, applied automatically to every salary."""
import os, unittest, re
from datetime import date
os.environ['DATABASE_URL']='sqlite:///:memory:'
from app import app, db, Employee
from payroll_calendar import month_dates


class SchoolPayrollPolicyTests(unittest.TestCase):
    def setUp(self):
        app.config.update(TESTING=True,IDENTITY_ENFORCE_IN_TESTS=False,SECRET_KEY='school-policy-test')
        self.ctx=app.app_context();self.ctx.push();db.drop_all();db.create_all()
        self.ops=app.extensions['ops_models'];self.details=app.extensions['record_models']['employee']
        self.Setting=app.extensions['school_settings_models']['setting']
        self.W=self.ops['workflow'];self.Salary=self.ops['salary'];self.Daily=self.ops['daily']
        self.c=app.test_client()
        page=self.c.get('/workspace/payroll-policy')
        self.assertEqual(page.status_code,200,page.data[:500])
        with self.c.session_transaction() as s:self.csrf=s['record_csrf']
        self.employees=[self.employee('A',3000000,'Campus A'),self.employee('B',6000000,'Campus B')]
        dates=[d.isoformat() for d in month_dates('2026-09') if d.weekday()!=6]
        response=self.c.post('/workspace/payroll-calendar',data=dict(_csrf=self.csrf,month='2026-09',version='0',working_dates=dates,pay_basis='calendar_days'))
        self.assertEqual(response.status_code,302)
    def tearDown(self):
        db.session.remove();db.drop_all();self.ctx.pop()
    def employee(self,code,basic,campus):
        e=Employee(employee_no=code,name='Fictional '+code,role='Teacher' if code=='A' else 'Cleaner',status='Active')
        db.session.add(e);db.session.flush()
        db.session.add(self.details(employee_id=e.id,data={'joining_date':'2026-01-01','campus':campus}))
        # Old conflicting employee rules must never override the shared policy.
        db.session.add(self.W(kind='salary-plans',status='Approved',data=dict(employee_id=str(e.id),basic=basic,security_return=0,security_payment=0,incentive_per_lecture=0,annual_increment=0,bonus_amount=0,rules=[dict(status='Absent',type='Abs',amount=123,allowed=0)],lecture_wise=False)))
        for n,status in [(1,'Absent'),(2,'Late'),(3,'Leave'),(4,'Leave'),(5,'Leave')]:
            db.session.add(self.Daily(kind='staff',person_id=e.id,day=date(2026,9,n),status=status))
        db.session.commit();return e
    def settings_form(self,version='0',**changes):
        data=dict(_csrf=self.csrf,action='assign',version=version)
        for i in range(6):
            data.update({f'allowed_{i}':'2' if i==2 else '0',f'type_{i}':'Percent',f'deduction_{i}':('100','25','100','0','0','0')[i]})
        data.update(changes);return data
    def assign(self,**kwargs):
        return self.c.post('/workspace/payroll-policy',data=self.settings_form(**kwargs))
    def generate(self,ids,**changes):
        return self.c.post('/workspace/payroll',data=dict(_csrf=self.csrf,action='generate',month='2026-09',employee_ids=[str(i) for i in ids],**changes))
    def policy(self):
        return db.session.get(self.Setting,'hrm:payroll-deduction-policy')
    def test_all_staff_including_new_employee_use_policy_automatically(self):
        self.assertEqual(self.assign().status_code,302)
        self.assertEqual(len(self.policy().data['rules']),6)
        future=self.employee('C',4500000,'Campus C')
        page=self.c.get('/workspace/payroll?month=2026-09').get_data(as_text=True)
        self.assertIn('Assigned to all staff',page)
        self.assertNotIn('name="attendance_based"',page)
        self.assertIn('School-wide policy assigned',self.c.get('/workspace/salary-plans').get_data(as_text=True))
        self.assertNotIn('name="deduction_0"',self.c.get('/workspace/salary-plans').get_data(as_text=True))
        # Even an old client that omits the attendance_based flag cannot opt out.
        self.assertEqual(self.generate([e.id for e in self.employees]+[future.id]).status_code,302)
        saved=self.Salary.query.order_by(self.Salary.employee_id).all()
        self.assertEqual([s.deductions for s in saved],[225000,450000,337500])
        self.assertEqual([s.net for s in saved],[2775000,5550000,4162500])
        for s in saved:
            self.assertEqual(s.detail['attendance_policy'],{'scope':'school','version':1})
            self.assertEqual([r['count'] for r in s.detail['attendance'][:3]],[1,1,3])
        self.assertTrue(all(p.data['rules'][0]['amount']==123 for p in self.W.query.filter_by(kind='salary-plans').all()))
        self.assertEqual(self.assign(version='1',deduction_0='50').status_code,302)
        self.assertEqual(self.policy().version,2)
        self.assertEqual(self.generate([e.id for e in self.employees]).status_code,302)
        self.assertEqual(self.Salary.query.count(),3)
        self.assertEqual(saved[0].deductions,225000)
    def test_saved_monthly_totals_feed_shared_deductions_and_preview(self):
        from monthly_attendance import STATUSES
        self.assertEqual(self.assign().status_code,302)
        eid=self.employees[0].id
        path='/workspace/core/hrm/monthly-attendance'
        page=self.c.get(path+'?month=2026-09&view=summary').get_data(as_text=True)
        revision=re.search(fr'name="revision_{eid}" value="([a-f0-9]+)"',page).group(1)
        counts={'Absent':2,'Late':2,'Leave':3}
        form=dict(_csrf=self.csrf,view='summary',month='2026-09',page='1',employee_ids=str(eid),**{f'revision_{eid}':revision,f'lectures_{eid}':'0',f'notes_{eid}':''})
        form.update({f'count_{i}_{eid}':str(counts.get(status,0)) for i,status in enumerate(STATUSES)})
        self.assertEqual(self.c.post(path,data=form).status_code,302)
        raw=self.c.get('/workspace/payroll?month=2026-09').get_data(as_text=True)
        self.assertIn('Saved monthly attendance',raw)
        token=re.search(fr'name="preview_{eid}" value="([^"]+)"',raw).group(1)
        self.assertEqual(self.generate([eid],reviewed_preview='1',**{f'preview_{eid}':token}).status_code,302)
        saved=self.Salary.query.one()
        self.assertEqual(saved.deductions,350000)
        self.assertEqual(saved.detail['monthly_attendance']['counts']['Absent'],2)

    def test_policy_page_combines_roster_attendance_and_generate_action(self):
        e=self.employees[0]
        self.Daily.query.filter_by(person_id=e.id,day=date(2026,9,5)).one().status='Present'
        self.W.query.filter_by(kind='salary-plans').filter(self.W.data['employee_id'].as_string()==str(self.employees[1].id)).delete()
        db.session.commit()
        url='/workspace/payroll-policy?month=2026-09'
        page=self.c.get(url).get_data(as_text=True)
        def row(html,employee):
            return next(r for r in html.split('data-payroll-row') if f'aria-label="Select {employee.name}"' in r)
        self.assertIn('Save the school-wide deduction policy first',page)
        self.assertIn('No approved salary plan',page)
        ar=row(page,e);br=row(page,self.employees[1])
        self.assertIn('data-pay-status="Present"><strong>1',ar)
        self.assertIn('data-pay-status="Absent"><strong>1',ar)
        self.assertIn('data-pay-status="Late"><strong>1',ar)
        self.assertIn('data-pay-status="Leave"><strong>3',br)
        self.assertNotIn(f'name="preview_{e.id}"',page)
        self.assertEqual(self.generate([e.id],return_to='policy',reviewed_preview='1').status_code,422)
        self.assertEqual(self.c.post(url,data=self.settings_form()).status_code,302)
        page=self.c.get(url).get_data(as_text=True)
        ar=row(page,e);self.assertIn('data-pay-status="Present"><strong>1',ar)
        self.assertIn('data-base-paisa="125000"',ar)
        token=re.search(fr'name="preview_{e.id}" value="([^"]+)"',page).group(1)
        response=self.generate([e.id],return_to='policy',reviewed_preview='1',**{f'preview_{e.id}':token})
        self.assertEqual(response.status_code,302)
        self.assertIn('/workspace/payroll-policy?month=2026-09',response.location)
        self.assertTrue(response.location.endswith('#staff-payroll'))
        saved=self.Salary.query.one()
        self.assertEqual(saved.deductions,125000)
        self.assertEqual(saved.detail['attendance_counts']['Present'],1)
        self.Daily.query.filter_by(person_id=e.id,day=date(2026,9,5)).one().status='Absent'
        db.session.commit()
        ar=row(self.c.get(url).get_data(as_text=True),e)
        self.assertIn('Already generated',ar)
        self.assertIn('data-pay-status="Present"><strong>1',ar)
        self.assertNotIn(f'name="preview_{e.id}"',ar)
        self.assertEqual(self.Salary.query.count(),1)

    def test_policy_roster_monthly_edit_returns_to_same_month(self):
        from monthly_attendance import STATUSES
        e=self.employees[0]
        path='/workspace/core/hrm/monthly-attendance'
        query=f'?month=2026-09&view=summary&employee_id={e.id}&return_to=policy'
        html=self.c.get(path+query).get_data(as_text=True)
        self.assertIn('name="return_to" value="policy"',html)
        rev=re.search(fr'name="revision_{e.id}" value="([a-f0-9]+)"',html).group(1)
        fields=dict(_csrf=self.csrf,view='summary',month='2026-09',page='1',employee_id=str(e.id),employee_ids=str(e.id),return_to='policy',**{f'revision_{e.id}':rev,f'lectures_{e.id}':'0',f'notes_{e.id}':''})
        counts={'Present':4,'Absent':1,'Late':1,'Leave':3}
        fields.update({f'count_{i}_{e.id}':str(counts.get(v,0)) for i,v in enumerate(STATUSES)})
        response=self.c.post(path,data=fields)
        self.assertEqual(response.status_code,302)
        self.assertIn('/workspace/payroll-policy?month=2026-09',response.location)
        self.assertIn(f'employee_id={e.id}',response.location)
        self.assertIn('data-pay-status="Present"><strong>4',self.c.get(response.location).get_data(as_text=True))

    def test_incomplete_invalid_stale_policy_and_preview_are_rejected(self):
        self.assertEqual(self.c.post('/workspace/payroll-policy',data={'action':'assign'}).status_code,400)
        data=self.settings_form();data.pop('deduction_1')
        self.assertEqual(self.c.post('/workspace/payroll-policy',data=data).status_code,422)
        self.assertEqual(self.assign(deduction_0='101').status_code,422)
        self.assertIsNone(self.policy())
        self.assertEqual(self.assign().status_code,302)
        self.assertEqual(self.assign(deduction_0='0').status_code,422)
        raw=self.c.get('/workspace/payroll?month=2026-09').get_data(as_text=True)
        eid=self.employees[0].id
        token=re.search(fr'name="preview_{eid}" value="([^"]+)"',raw).group(1)
        self.assertEqual(self.assign(version='1',deduction_0='50').status_code,302)
        self.assertEqual(self.generate([eid],reviewed_preview='1',**{f'preview_{eid}':token}).status_code,422)
        self.assertEqual(self.Salary.query.count(),0)
        raw=self.c.get('/workspace/payroll?month=2026-09').get_data(as_text=True)
        token=re.search(fr'name="preview_{eid}" value="([^"]+)"',raw).group(1)
        self.assertEqual(self.generate([eid],reviewed_preview='1',**{f'preview_{eid}':token}).status_code,302)
        self.assertEqual(self.Salary.query.one().deductions,175000)
    def test_fixed_deduction_and_employee_editor_preserves_legacy_rules(self):
        self.assertEqual(self.assign(type_0='Abs',deduction_0='500').status_code,302)
        plan=self.W.query.filter_by(kind='salary-plans').order_by(self.W.id).first()
        # Untrusted extra per-employee rule fields cannot alter shared rules.
        response=self.c.post('/workspace/salary-plans',data=dict(_csrf=self.csrf,action='save',edit=str(plan.id),employee_id=str(self.employees[0].id),basic='35000',deduction_0='0'))
        self.assertEqual(response.status_code,302)
        self.assertEqual(plan.data['rules'][0]['amount'],123)
        self.assertEqual(self.policy().data['rules'][0]['amount'],50000)
        self.assertEqual(self.c.post('/workspace/salary-plans',data=dict(_csrf=self.csrf,action='approve',ids=str(plan.id))).status_code,302)
        self.assertEqual(self.generate([e.id for e in self.employees]).status_code,302)
        self.assertEqual([s.deductions for s in self.Salary.query.order_by(self.Salary.employee_id).all()],[195834,300000])


if __name__=='__main__':unittest.main()
