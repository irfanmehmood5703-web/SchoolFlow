"""Real balanced postings and independent expected report totals; fictional data."""
import os,secrets,unittest
from datetime import date
os.environ['DATABASE_URL']='sqlite:///:memory:'
from app import app,db

class FinanceLedgerTests(unittest.TestCase):
    def setUp(self):
        app.config.update(TESTING=True,IDENTITY_ENFORCE_IN_TESTS=False,SECRET_KEY='fictional-ledger-tests')
        self.ctx=app.app_context();self.ctx.push();db.drop_all();db.create_all()
        self.m=app.extensions['finance_models'];self.j=app.extensions['ledger_models'];self.c=app.test_client()
        self.c.get('/workspace/finance/ledger/entry/journal')
        with self.c.session_transaction() as s:self.csrf=s['record_csrf']
        Setting=app.extensions['record_models']['settings'];db.session.add(Setting(category='campus',value='Campus A',class_name=''));db.session.add(Setting(category='campus',value='Campus B',class_name=''));db.session.commit()
        self.c.post('/workspace/finance/periods/new',data=dict(_csrf=self.csrf,version='0',begin='2026-01-01',end='2026-12-31',closed='0'))
        self.period=self.m['period'].query.one()
        self.asset=self.account('Cash','Assets');self.expense=self.account('Stationery','Expense');self.income=self.account('School income','Income');self.equity=self.account('Capital','Equity')
    def tearDown(self):db.session.remove();db.drop_all();self.ctx.pop()
    def account(self,name,cls):
        self.c.post('/workspace/finance/groups/new',data=dict(_csrf=self.csrf,version='0',name=cls+' group',account_class=cls,active='1'))
        group=self.m['group'].query.filter_by(account_class=cls).one()
        response=self.c.post('/workspace/finance/accounts/new',data=dict(_csrf=self.csrf,version='0',name=name,group_id=str(group.id),inactive='0'));self.assertEqual(response.status_code,302)
        return self.m['account'].query.filter_by(name=name).one()
    def post(self,kind='journal',**changes):
        data=dict(_csrf=self.csrf,post_token=secrets.token_urlsafe(32),day='2026-11-01',campus='Campus A',account_id=[str(self.asset.id),str(self.income.id)],debit=['100',''],credit=['','100'],memo=['cash entry','income entry'])
        data.update(changes);return self.c.post('/workspace/finance/ledger/entry/'+kind,data=data)
    def report(self,mode='trial',**args):return self.c.get('/workspace/finance/ledger/report/'+mode,query_string={'from':'2026-11-01','to':'2026-11-30',**args})
    def context(self,mode='trial',**args):
        from flask import template_rendered
        captured=[]
        def receive(sender,template,context,**kw):captured.append(context)
        template_rendered.connect(receive,app)
        try:r=self.report(mode,**args);self.assertEqual(r.status_code,200,r.data);return captured[-1]
        finally:template_rendered.disconnect(receive,app)
    def test_all_reference_pages_render_empty_without_posting(self):
        for path in ['entry/journal','entry/expense','entry/income','report/ledger','report/inquiry','report/trial','report/profit','report/balance']:
            self.assertEqual(self.c.get('/workspace/finance/ledger/'+path).status_code,200,path)
        self.assertEqual(self.j['journal'].query.count(),0)
    def test_balanced_journal_saved_as_integer_paisa_and_exact_retry_is_idempotent(self):
        token=secrets.token_urlsafe(32);r=self.post(post_token=token,debit=['100.25',''],credit=['','100.25']);self.assertEqual(r.status_code,302)
        lines=self.j['line'].query.all();self.assertEqual(sum(l.debit for l in lines),10025);self.assertEqual(sum(l.credit for l in lines),10025)
        self.assertEqual(self.post(post_token=token,debit=['100.25',''],credit=['','100.25']).location,r.location)
        self.assertEqual(self.post(post_token=token,debit=['101',''],credit=['','101']).status_code,422)
        self.assertEqual(self.j['journal'].query.count(),1)
    def test_invalid_unbalanced_negative_nonfinite_precision_and_rows_are_atomic(self):
        for changes in [dict(credit=['','99']),dict(debit=['-1','']),dict(debit=['NaN','']),dict(debit=['100.001','']),dict(debit=['100','20'],credit=['','120']),dict(account_id=[str(self.asset.id)]),dict(account_id=['999999',str(self.income.id)]),dict(memo=['x'*1001,''])]:
            r=self.post(**changes);self.assertEqual(r.status_code,422,changes);self.assertEqual(self.j['journal'].query.count(),0)
    def test_csrf_period_campus_and_inactive_account_checks(self):
        self.assertEqual(self.post(_csrf='bad').status_code,400)
        self.assertEqual(self.post(day='2027-01-01').status_code,422)
        self.assertEqual(self.post(campus='Unknown').status_code,422)
        self.period.closed=True;db.session.commit();self.assertEqual(self.post().status_code,422)
        self.period.closed=False;self.asset.inactive=True;db.session.commit();self.assertEqual(self.post().status_code,422)
        self.assertEqual(self.j['line'].query.count(),0)
    def test_expense_income_counterposting_and_class_restrictions(self):
        r=self.post('expense',account_id=[str(self.expense.id)],amount=['25.50'],memo=['Paper'],counter_account=str(self.asset.id));self.assertEqual(r.status_code,302)
        r=self.post('income',account_id=[str(self.income.id)],amount=['100'],memo=['Other'],counter_account=str(self.asset.id));self.assertEqual(r.status_code,302)
        self.assertEqual(sum(l.debit-l.credit for l in self.j['line'].query.filter_by(account_id=self.asset.id)),7450)
        self.assertEqual(self.post('expense',account_id=[str(self.income.id)],amount=['2'],memo=['Invalid'],counter_account=str(self.asset.id)).status_code,422)
        self.assertEqual(self.post('income',account_id=[str(self.income.id)],amount=['2'],memo=['Invalid'],counter_account=str(self.expense.id)).status_code,422)
    def test_opening_running_trial_profit_and_balance_are_consistent(self):
        self.assertEqual(self.post(day='2026-10-01',account_id=[str(self.asset.id),str(self.equity.id)]).status_code,302)
        self.assertEqual(self.post().status_code,302)
        self.assertEqual(self.post('expense',account_id=[str(self.expense.id)],amount=['25'],memo=['Paper'],counter_account=str(self.asset.id)).status_code,302)
        inquiry=self.context('inquiry',account_id=str(self.asset.id));self.assertEqual((inquiry['opening'],inquiry['debit'],inquiry['credit'],inquiry['ending']),(10000,10000,2500,17500))
        trial=self.context();self.assertEqual(trial['totals']['brought_debit'],10000);self.assertEqual(trial['totals']['debit'],12500);self.assertEqual(trial['totals']['credit'],12500)
        self.assertEqual(trial['totals']['balance_debit'],trial['totals']['balance_credit'])
        profit=self.context('profit');self.assertEqual(profit['totals'],dict(income=10000,expense=2500,profit=7500))
        balance=self.context('balance');self.assertEqual(balance['totals']['assets'],17500);self.assertEqual(balance['totals']['capital'],10000);self.assertEqual(balance['totals']['equity'],17500);self.assertEqual(balance['totals']['difference'],0)
    def test_filters_are_applied_to_opening_and_movements(self):
        self.post(day='2026-10-01');self.post(campus='Campus B')
        a=self.context('inquiry',account_id=str(self.asset.id),campus='Campus A');self.assertEqual((a['opening'],a['debit'],a['ending']),(10000,0,10000))
        b=self.context('profit',campus='Campus B');self.assertEqual(b['totals']['income'],10000)
        self.assertEqual(self.report(campus='Bad').status_code,422);self.assertEqual(self.report(user='bad').status_code,422)
        self.assertEqual(self.report(**{'from':'2026-12-01','to':'2026-11-01'}).status_code,422)
    def test_posted_account_period_protection_and_historical_name_snapshot(self):
        r=self.post();self.assertEqual(r.status_code,302);self.asset.name='Renamed cash';db.session.commit()
        self.assertIn(b'Cash',self.c.get(r.location).data);self.assertNotIn(b'Renamed cash',self.c.get(r.location).data)
        for kind,row in [('accounts',self.asset),('periods',self.period)]:
            result=self.c.post(f'/workspace/finance/{kind}/{row.id}',data=dict(_csrf=self.csrf,action='delete',confirm='1',version=str(row.version)));self.assertEqual(result.status_code,422)
        self.assertEqual(self.c.post(f'/workspace/finance/periods/{self.period.id}/edit',data=dict(_csrf=self.csrf,version=str(self.period.version),begin='2026-01-02',end='2026-12-31',closed='0')).status_code,422)
    def test_retry_after_close_does_not_post_again(self):
        token=secrets.token_urlsafe(32);self.assertEqual(self.post(post_token=token).status_code,302)
        self.period.closed=True;self.asset.inactive=True;db.session.commit()
        self.assertEqual(self.post(post_token=token).status_code,302);self.assertEqual(self.j['journal'].query.count(),1)
    def test_renamed_account_is_netted_once_across_opening_and_current_period(self):
        self.post(day='2026-10-01');self.asset.name='New Cash';db.session.commit()
        self.post('expense',account_id=[str(self.expense.id)],amount=['60'],memo=['Paper'],counter_account=str(self.asset.id))
        trial=self.context();asset_rows=[r for r in trial['report_rows'] if r['snapshot']['account_class']=='Assets']
        self.assertEqual(len(asset_rows),1);self.assertEqual(asset_rows[0]['balance_debit'],4000);self.assertEqual(asset_rows[0]['balance_credit'],0)
    def test_print_and_search_do_not_change_profit_summary(self):
        self.post();report=self.context('profit',q='not present');self.assertEqual(report['display'],[]);self.assertEqual(report['totals']['profit'],10000)
        printed=self.context('profit',q='not present',print='1');self.assertEqual(len(printed['display']),1)
