"""End-to-end advance accounting with independent financial expectations."""
import io,secrets,unittest
from datetime import date,timedelta
from flask import template_rendered
from app import app,db
from tests import test_requisitions as fixture

class RequisitionPostingTests(unittest.TestCase):
    setUp=fixture.RequisitionTests.setUp
    tearDown=fixture.RequisitionTests.tearDown
    account=fixture.RequisitionTests.account
    submit=fixture.RequisitionTests.submit
    decide=fixture.RequisitionTests.decide
    def prepare(self):
        Group=app.extensions['finance_models']['group'];Account=app.extensions['finance_models']['account']
        g=Group.query.filter_by(account_class='Assets').one()
        self.c.post('/workspace/finance/accounts/new',data=dict(_csrf=self.csrf,version='0',name='Staff Advances',group_id=g.id,inactive='0'));self.advance=Account.query.filter_by(name='Staff Advances').one()
        self.payable=self.account('Payable staff','Liabilities')
        self.configure();self.submit();self.decide()
    def configure(self,**changes):
        row=app.extensions['requisition_models']['config'].query.first()
        data=dict(_csrf=self.csrf,version=str(row.version if row else 0),prefix='REQ',settle_days='15',overdue_days='30',carry_unspent='1',require_bill='1',advance_account=str(self.advance.id),pay_account=str(self.asset.id),payable_account=str(self.payable.id));data.update(changes)
        return self.c.post('/workspace/finance/requisitions/settings',data=data)
    def post(self,kind,rid=1,**changes):
        R=app.extensions['requisition_models']['request'];r=db.session.get(R,rid)
        data=dict(_csrf=self.csrf,post_token=secrets.token_urlsafe(32),version=str(r.version),day='2026-11-01',amount='20',account_id=str(self.asset.id),notes='Fictional QA',reference='QA bill');data.update(changes)
        return self.c.post(f'/workspace/finance/requisitions/{rid}/posting/{kind}',data=data,content_type='multipart/form-data')
    def bill(self,amount='15',**changes):
        data=dict(expense_account=[str(self.expense.id)],expense_amount=[amount],bill_file=(io.BytesIO(b'%PDF-1.4\nFictional bill\n%%EOF'),'fictional.pdf'));data.update(changes)
        return self.post('bill',**data)
    def b(self,rid=1,as_at=None):return app.extensions['requisition_posting']['balance'](rid,as_at)
    def net(self,account):
        lines=self.j['line'].query.filter_by(account_id=account.id).all();return sum(x.debit-x.credit for x in lines)
    def test_issue_bill_return_reconciles_and_attachment_is_retained(self):
        self.prepare();self.assertEqual(self.post('issue').status_code,302)
        self.assertEqual((self.net(self.advance),self.net(self.asset),self.net(self.expense)),(2000,-2000,0))
        self.assertEqual(self.bill().status_code,302);self.assertEqual((self.b()['held'],self.net(self.expense)),(500,1500))
        self.assertEqual(self.post('return',amount='5').status_code,302);self.assertEqual((self.b()['held'],self.net(self.advance),self.net(self.asset)),(0,0,-1500))
        models=app.extensions['requisition_models'];m=models['movement'].query.filter_by(kind='bill').one()
        response=self.c.get(f'/workspace/finance/requisitions/attachment/{m.id}');self.assertEqual(response.status_code,200);self.assertIn('attachment',response.headers['Content-Disposition']);self.assertTrue(response.data.startswith(b'%PDF-'))
        self.assertIn(b'This agrees with your books',self.c.get('/workspace/finance/requisitions/reports').data)
        for kind in ('issue','bill','return','carry','reimburse'):
            self.assertEqual(self.c.get(f'/workspace/finance/requisitions/1/posting/{kind}').status_code,200)
    def test_partial_issue_and_exact_retry_do_not_duplicate(self):
        self.prepare();token=secrets.token_urlsafe(32);r=app.extensions['requisition_models']['request'].query.one();v=str(r.version)
        self.assertEqual(self.post('issue',amount='12.50',post_token=token,version=v).status_code,302)
        self.assertEqual(self.post('issue',amount='12.50',post_token=token,version=v).status_code,302)
        self.assertEqual(self.post('issue',amount='12.51',post_token=token,version=v).status_code,422)
        self.assertEqual(self.post('issue',amount='8').status_code,422);self.assertEqual(self.post('issue',amount='7.50').status_code,302)
        self.assertEqual((self.b()['issue'],self.j['journal'].query.count()),(2000,2))
    def test_expense_uses_advance_then_payable_and_reimbursement(self):
        self.prepare();self.post('issue',amount='10');self.assertEqual(self.bill('20').status_code,302)
        self.assertEqual((self.b()['held'],self.b()['owed'],self.net(self.payable),self.net(self.expense)),(0,1000,-1000,2000))
        self.assertEqual(self.post('reimburse',amount='11').status_code,422);self.assertEqual(self.post('reimburse',amount='10').status_code,302)
        self.assertEqual((self.net(self.payable),self.net(self.asset),self.b()['owed']),(0,-2000,0))
        self.assertEqual(self.post('issue',amount='1').status_code,422)
    def test_invalid_or_missing_attachment_and_over_bill_are_atomic(self):
        self.prepare();self.post('issue')
        self.assertEqual(self.post('bill',expense_account=[str(self.expense.id)],expense_amount=['15']).status_code,422)
        self.assertEqual(self.post('bill',expense_account=[str(self.expense.id)],expense_amount=['15'],bill_file=(io.BytesIO(b'<script>bad</script>'),'bill.pdf')).status_code,422)
        self.assertEqual(self.bill('21').status_code,422)
        self.assertEqual(self.b()['held'],2000);self.assertEqual(self.j['journal'].query.count(),1)
        self.assertEqual(self.bill('20',expense_account=[str(self.income.id)]).status_code,422)
    def test_carry_preserves_person_account_and_original_age(self):
        self.prepare();self.submit(purpose='Next');self.decide(rid=2)
        self.post('issue',day='2026-10-01')
        target=db.session.get(app.extensions['requisition_models']['request'],2)
        self.assertEqual(self.post('carry',amount='8',target_id='2',target_version=str(target.version)).status_code,302)
        self.assertEqual((self.b()['held'],self.b(2)['held'],self.net(self.advance),self.j['journal'].query.count()),(1200,800,2000,1))
        self.assertEqual(self.b(2)['oldest'],date(2026,10,1))
        self.assertEqual(self.b(2,date(2026,10,31))['held'],0)
        self.assertEqual(self.post('carry',amount='13',target_id='2',target_version=str(target.version)).status_code,422)
        self.configure(carry_unspent='');self.assertEqual(self.post('carry',amount='1',target_id='2',target_version=str(target.version)).status_code,422)
    def test_stale_versions_closed_period_dates_and_account_checks(self):
        self.prepare();self.period.closed=True;db.session.commit();self.assertEqual(self.post('issue').status_code,422)
        self.period.closed=False;db.session.commit()
        for kwargs in (dict(version='0'),dict(account_id=str(self.advance.id)),dict(day='2099-01-01'),dict(account_id=str(self.expense.id))):self.assertEqual(self.post('issue',**kwargs).status_code,422)
        self.post('issue',day='2026-11-02');self.assertEqual(self.bill(day='2026-11-01').status_code,422)
        self.assertEqual(self.j['journal'].query.count(),1)
    def test_mapping_changes_and_new_requests_are_guarded_while_open(self):
        self.prepare();self.post('issue')
        self.assertEqual(self.configure(advance_account='').status_code,422)
        self.assertEqual(self.configure(block_open='1').status_code,302)
        self.assertEqual(self.submit().status_code,422)
        self.post('return');self.assertEqual(self.submit().status_code,302)
    def test_unapproved_and_csrf_cannot_post_and_system_journal_cannot_be_edited(self):
        self.prepare();self.submit(purpose='Pending')
        self.assertEqual(self.post('issue',rid=2).status_code,422);self.assertEqual(self.post('issue',_csrf='bad').status_code,400)
        self.post('issue');jid=self.j['journal'].query.one().id
        self.assertEqual(self.c.get(f'/workspace/finance/reports/journal/{jid}/edit').status_code,422)
    def test_ageing_and_reconciliation_expose_manual_discrepancy(self):
        self.prepare();self.post('issue',day='2026-10-01');captured=[]
        def receive(sender,template,context,**kw):captured.append(context)
        template_rendered.connect(receive,app)
        try:
            self.c.get('/workspace/finance/requisitions/reports?as_at=2026-11-06');self.assertEqual(captured[-1]['buckets'],[0,0,0,2000])
        finally:template_rendered.disconnect(receive,app)
        from tests.test_finance_ledger import FinanceLedgerTests
        FinanceLedgerTests.post(self,account_id=[str(self.advance.id),str(self.income.id)],debit=['1',''],credit=['','1'],memo=['Manual mismatch','Income'])
        self.assertIn(b'Reconciliation difference',self.c.get('/workspace/finance/requisitions/reports').data)
