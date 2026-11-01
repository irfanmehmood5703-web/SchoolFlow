"""Explicit group and cap math, unsaved previews and approved payroll snapshots."""
import os,unittest
from datetime import date
os.environ['DATABASE_URL']='sqlite:///:memory:'
from app import app,db,Employee
from operations import money
from payroll_rules import deduction,parse_rule
from werkzeug.datastructures import MultiDict


class PayrollRuleMathTests(unittest.TestCase):
    def rule(self,**changes):
        r=dict(status='Absent',allowed=1,type='Abs',amount=10000,frequency='Recursive',jump=0,limit=0,jump_mode='per_event',cap_mode='none',max_amount=0);r.update(changes);return r
    def test_free_days_complete_and_started_groups_have_explicit_boundaries(self):
        for count in range(8):
            self.assertEqual(deduction(self.rule(),count,2200000,22)['events'],max(0,count-1))
        for mode,expected in [('complete_groups',2),('started_groups',3)]:
            result=deduction(self.rule(jump_mode=mode,jump=2),6,2200000,22);self.assertEqual((result['extra'],result['events'],result['amount']),(5,expected,expected*10000))
        self.assertEqual(deduction(self.rule(jump_mode='complete_groups',jump=2),2,2200000,22)['amount'],0)
    def test_once_event_cap_amount_cap_and_explicit_zero_caps(self):
        self.assertEqual(deduction(self.rule(frequency='Once'),6,2200000,22)['amount'],10000)
        self.assertEqual(deduction(self.rule(cap_mode='events',limit=2),6,2200000,22)['amount'],20000)
        self.assertEqual(deduction(self.rule(cap_mode='amount',max_amount=15050),6,2200000,22)['amount'],15050)
        for cap in ('events','amount'):self.assertEqual(deduction(self.rule(cap_mode=cap),6,2200000,22)['amount'],0)
    def test_percentage_uses_working_days_rounding_and_cap_after_rounding(self):
        rule=self.rule(type='Percent',amount=2500,jump_mode='complete_groups',jump=2)
        self.assertEqual(deduction(rule,6,2200000,22)['amount'],50000)
        self.assertEqual(deduction(self.rule(type='Percent',amount=10000),2,10001,3)['amount'],3334)
        with self.assertRaises(ValueError):deduction(rule,6,2200000,0)
    def test_legacy_unknown_fields_need_review_but_simple_rules_keep_their_math(self):
        for changes in [dict(jump=2),dict(limit=3)]:
            r=self.rule(**changes);r.pop('jump_mode');r.pop('cap_mode')
            with self.assertRaises(ValueError):deduction(r,6,2200000,22)
        simple=self.rule();simple.pop('jump_mode');simple.pop('cap_mode');self.assertEqual(deduction(simple,6,2200000,22)['amount'],50000)
    def test_form_parser_rejects_ignored_group_sizes_and_ambiguous_caps(self):
        base={'allowed_0':'1','jump_0':'0','limit_0':'0','deduction_0':'100','type_0':'Abs','frequency_0':'Recursive'}
        for changes in [dict(jump_0='2'),dict(limit_0='3'),dict(jump_0='2',jump_mode_0='per_event'),dict(jump_0='0',jump_mode_0='started_groups'),dict(cap_mode_0='events',limit_0='3.5'),dict(cap_mode_0='none',limit_0='10'),dict(cap_mode_0='amount',limit_0='-1')]:
            with self.assertRaises(ValueError):parse_rule(MultiDict({**base,**changes}),0,'Absent',money)
        r=parse_rule(MultiDict({**base,'cap_mode_0':'amount','limit_0':'150.50'}),0,'Absent',money);self.assertEqual(r['max_amount'],15050)


class PayrollRuleWorkflowTests(unittest.TestCase):
    def setUp(self):
        app.config.update(TESTING=True,IDENTITY_ENFORCE_IN_TESTS=False,SECRET_KEY='payroll-rules-test');self.ctx=app.app_context();self.ctx.push();db.drop_all();db.create_all()
        self.ops=app.extensions['ops_models'];self.rm=app.extensions['record_models'];self.e=Employee(employee_no='RULE-1',name='Fictional rule teacher',role='Teacher',status='Active');db.session.add(self.e);db.session.flush();db.session.add(self.rm['employee'](employee_id=self.e.id,data={'joining_date':'2026-01-01'}));db.session.commit()
        self.c=app.test_client();self.c.get('/workspace/salary-plans')
        with self.c.session_transaction() as s:self.csrf=s['record_csrf']
    def tearDown(self):db.session.remove();db.drop_all();self.ctx.pop()
    def form(self,**changes):
        data={'_csrf':self.csrf,'employee_id':str(self.e.id),'basic':'10000','allowed_0':'1','jump_0':'2','limit_0':'150.50','type_0':'Abs','deduction_0':'100','frequency_0':'Recursive','jump_mode_0':'started_groups','cap_mode_0':'amount','preview_count_0':'6','preview_working_days':'22'};data.update(changes);return data
    def test_preview_saves_nothing_and_actual_approved_payroll_uses_the_rule(self):
        response=self.c.post('/workspace/salary-plans',data=self.form(action='preview'));self.assertEqual(response.status_code,200);self.assertIn(b'150.50',response.data);self.assertIn(b'Unsaved attendance deduction preview',response.data)
        self.assertEqual(self.ops['workflow'].query.count(),0);self.assertEqual(self.ops['salary'].query.count(),0);self.assertEqual(self.ops['audit'].query.count(),0)
        self.assertEqual(self.c.post('/workspace/salary-plans',data=self.form(action='save')).status_code,302);plan=self.ops['workflow'].query.one();self.assertEqual(plan.status,'Pending');self.assertEqual(plan.data['rules'][0]['max_amount'],15050)
        self.c.post('/workspace/salary-plans',data={'_csrf':self.csrf,'action':'approve','ids':str(plan.id)})
        for day in range(1,7):db.session.add(self.ops['daily'](kind='staff',person_id=self.e.id,day=date(2026,9,day),status='Absent'))
        db.session.commit();response=self.c.post('/workspace/payroll',data={'_csrf':self.csrf,'action':'generate','month':'2026-09','employee_ids':str(self.e.id),'attendance_based':'on'});self.assertEqual(response.status_code,302)
        salary=self.ops['salary'].query.one();self.assertEqual((salary.deductions,salary.net),(15050,984950));self.assertEqual(salary.detail['attendance'][0]['events'],3)
        plan.data={**plan.data,'rules':[]};db.session.commit();self.assertEqual(salary.detail['attendance'][0]['amount'],15050)
    def test_percentage_preview_requires_explicit_working_days_and_save_remains_pending(self):
        data=self.form(action='preview',type_0='Percent',deduction_0='25',preview_working_days='0')
        self.assertEqual(self.c.post('/workspace/salary-plans',data=data).status_code,422);self.assertEqual(self.ops['workflow'].query.count(),0)
        data['preview_working_days']='22';self.assertEqual(self.c.post('/workspace/salary-plans',data=data).status_code,200)
        data['action']='save';self.assertEqual(self.c.post('/workspace/salary-plans',data=data).status_code,302);self.assertEqual(self.ops['workflow'].query.one().status,'Pending')
    def test_invalid_rule_and_impossible_trial_counts_do_not_save_a_plan(self):
        for changes in [dict(jump_mode_0=''),dict(cap_mode_0=''),dict(preview_count_0='32'),dict(preview_count_0='23')]:
            self.assertEqual(self.c.post('/workspace/salary-plans',data=self.form(action='preview',**changes)).status_code,422)
        self.assertEqual(self.ops['workflow'].query.count(),0)
