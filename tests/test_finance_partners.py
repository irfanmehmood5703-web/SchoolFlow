"""Cash reconciliation, scoped shareholder calculations and write guards."""
import secrets,unittest
from flask import template_rendered
from tests import test_finance_ledger as fixture
from app import app,db

class FinancePartnerTests(unittest.TestCase):
    setUp=fixture.FinanceLedgerTests.setUp
    tearDown=fixture.FinanceLedgerTests.tearDown
    account=fixture.FinanceLedgerTests.account
    post=fixture.FinanceLedgerTests.post
    def load(self,path='cash-report',**args):
        contexts=[]
        def receive(sender,template,context,**kw):contexts.append(context)
        template_rendered.connect(receive,app)
        try:
            r=self.c.get('/workspace/finance/'+path,query_string={'from':'2026-11-01','to':'2026-11-30',**args});self.assertEqual(r.status_code,200,r.data);return contexts[-1],r
        finally:template_rendered.disconnect(receive,app)
    def partner(self,**changes):
        data=dict(_csrf=self.csrf,post_token=secrets.token_urlsafe(32),version='0',name='Fictional partner',equity='50',account_id=str(self.equity.id),campus='',cnic='fictional',contact='Test contact',email='partner@example.invalid',since='2026-01-01',active='1',notes='Fictional QA');data.update(changes)
        return self.c.post('/workspace/finance/shareholders/new',data=data)
    def seed(self):
        self.post(day='2026-10-01',account_id=[str(self.asset.id),str(self.equity.id)])
        self.post('income',account_id=[str(self.income.id)],amount=['50'],memo=['Fee'],counter_account=str(self.asset.id))
        self.post('expense',account_id=[str(self.expense.id)],amount=['20'],memo=['Paper'],counter_account=str(self.asset.id))
    def test_empty_reports_forms_and_all_tabs_render(self):
        for tab in ('Assets','Liabilities','Equity','Expense','Income'):
            context,r=self.load(tab=tab);self.assertEqual(context['totals']['balance'],0);self.assertIn(b'No Records Found',r.data)
        self.load('shareholders');self.load('shareholders/new')
        self.assertEqual(app.extensions['shareholder_model'].query.count(),0)
    def test_cash_brought_forward_movement_and_rollups_do_not_double_count(self):
        self.seed();c,_=self.load()
        self.assertEqual(c['totals'],dict(brought_debit=10000,brought_credit=10000,debit=7000,credit=7000,balance=0))
        row=next(r for r in c['rows'] if r['id']==self.asset.id);self.assertEqual(row['balance'],13000)
        self.assertEqual(c['rollups'][('Assets',None)]['balance'],13000)
    def test_cash_account_campus_and_user_filters(self):
        self.seed();c,_=self.load(account_id=str(self.asset.id));self.assertEqual(len(c['rows']),1);self.assertEqual(c['totals']['balance'],13000)
        c,_=self.load(campus='Campus B');self.assertEqual(c['rows'],[])
        self.assertEqual(self.c.get('/workspace/finance/cash-report?account_id=9999').status_code,422)
        c,_=self.load(user='demo');self.assertEqual(c['totals']['debit'],7000)
        for q in ['user=unknown','tab=Invalid','size=1','page=0','from=2026-12-01&to=2026-11-01']:
            self.assertEqual(self.c.get('/workspace/finance/cash-report?'+q).status_code,422)
    def test_cash_search_and_print_preserve_all_loaded_accounts(self):
        self.seed();c,_=self.load(q='missing');self.assertEqual(c['display'],[]);self.assertEqual(c['totals']['debit'],7000)
        c,r=self.load(q='missing',print='1',tab='Expense');self.assertEqual(len(c['display']),4);self.assertIn(b'All account classes',r.data)
    def test_shareholder_capital_profit_share_and_transactions_use_real_journals(self):
        self.seed();before=self.j['journal'].query.count();self.assertEqual(self.partner().status_code,302)
        c,r=self.load('shareholders');self.assertEqual((c['income'],c['expense'],c['capital_total']),(5000,2000,10000));self.assertEqual(c['rows'][0]['share'],1500)
        self.assertEqual(self.j['journal'].query.count(),before)
        self.load('shareholders/1/transactions',**{'from':'2026-10-01'});self.load('shareholders/1/edit');self.load('shareholders',print='1')
    def test_unlinked_partner_and_former_filter_do_not_invent_capital(self):
        self.seed();self.partner(account_id='',active='0')
        c,_=self.load('shareholders');self.assertEqual(c['rows'],[])
        c,r=self.load('shareholders',former='1');self.assertIsNone(c['rows'][0]['capital']);self.assertEqual(c['rows'][0]['share'],0);self.assertIn(b'Not linked yet',r.data)
    def test_equity_validation_and_overlapping_allocation(self):
        self.assertEqual(self.partner(equity='60',account_id='').status_code,302)
        self.assertEqual(self.partner(name='Too much',equity='41',campus='Campus A',account_id='').status_code,422)
        self.assertEqual(self.partner(name='Campus A partner',equity='40',campus='Campus A',account_id='').status_code,302)
        self.assertEqual(self.partner(name='Campus B partner',equity='40',campus='Campus B',account_id='').status_code,302)
        for equity in ['NaN','Infinity','-1','100.01','1.001','']:
            self.assertEqual(self.partner(equity=equity,active='0',account_id='').status_code,422)
        self.assertEqual(self.partner(account_id=str(self.asset.id),active='0').status_code,422)
        self.assertEqual(self.partner(campus='Unknown',active='0',account_id='').status_code,422)
    def test_duplicate_capital_link_and_account_deletion_are_blocked(self):
        self.partner(equity='10')
        self.assertEqual(self.partner(name='Other owner',equity='10').status_code,422)
        r=self.c.post(f'/workspace/finance/accounts/{self.equity.id}',data=dict(_csrf=self.csrf,action='delete',confirm='1',version=str(self.equity.version)));self.assertEqual(r.status_code,422)
        self.assertIsNotNone(db.session.get(self.m['account'],self.equity.id))
    def test_exact_create_retry_csrf_and_changed_payload(self):
        token=secrets.token_urlsafe(32);self.assertEqual(self.partner(post_token=token).status_code,302)
        self.assertEqual(self.partner(post_token=token).status_code,302)
        self.assertEqual(self.partner(post_token=token,name='Changed').status_code,422)
        self.assertEqual(app.extensions['shareholder_model'].query.count(),1)
        self.assertEqual(self.partner(_csrf='bad').status_code,400)
    def test_partner_since_and_campus_limit_estimated_share(self):
        self.post(day='2026-11-01');self.post(day='2026-11-10');self.post(day='2026-11-10',campus='Campus B')
        self.partner(account_id='',campus='Campus A',since='2026-11-05')
        c,_=self.load('shareholders');self.assertEqual(c['rows'][0]['share'],5000)
    def test_edit_version_and_linked_posting_protection(self):
        self.seed();self.partner();P=app.extensions['shareholder_model'];p=P.query.one()
        data=dict(_csrf=self.csrf,post_token=secrets.token_urlsafe(32),version='0',name=p.name,equity='40',account_id=str(self.equity.id),active='1')
        path='/workspace/finance/shareholders/1/edit';self.assertEqual(self.c.post(path,data=data).status_code,422)
        data['version']=str(p.version);data['account_id']='';self.assertEqual(self.c.post(path,data=data).status_code,422)
        data['account_id']=str(self.equity.id);data['campus']='Campus B';self.assertEqual(self.c.post(path,data=data).status_code,422)
        data['campus']='';self.assertEqual(self.c.post(path,data=data).status_code,302)
        self.assertEqual(P.query.one().equity_bp,4000)
