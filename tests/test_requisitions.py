"""Request authorisation, tenant scoping and deliberate New Ledger posting gate."""
import secrets,unittest
from flask import template_rendered
from tests import test_finance_ledger as fixture
from app import app,db

class RequisitionTests(unittest.TestCase):
    setUp=fixture.FinanceLedgerTests.setUp
    tearDown=fixture.FinanceLedgerTests.tearDown
    account=fixture.FinanceLedgerTests.account
    def submit(self,**changes):
        data=dict(_csrf=self.csrf,post_token=secrets.token_urlsafe(32),campus='Campus A',category='Procurement / Supplies',needed='2026-11-20',purpose='Fictional supplies',item=['Paper','Pens'],qty=['2','1.5'],unit_price=['10.25','2.00']);data.update(changes)
        return self.c.post('/workspace/finance/requisitions/mine',data=data)
    def decide(self,rid=1,**changes):
        data=dict(_csrf=self.csrf,post_token=secrets.token_urlsafe(32),version='1',decision='Approved',approved='20',remarks='Fictional decision');data.update(changes)
        return self.c.post(f'/workspace/finance/requisitions/{rid}/decide',data=data)
    def test_pages_and_forms_render_without_fabricated_activity(self):
        for mode in ['mine','approvals','settings','issue','settle','reports','reports?tab=register']:
            response=self.c.get('/workspace/finance/requisitions/'+mode);self.assertEqual(response.status_code,200,response.data)
        self.assertEqual(self.j['journal'].query.count(),0)
    def test_server_computes_decimal_lines_and_estimate_and_number(self):
        r=self.submit(amount=['999999'],estimated='1');self.assertEqual(r.status_code,302,r.data)
        model=app.extensions['requisition_models']['request'];row=model.query.one()
        self.assertEqual(row.estimated,2350);self.assertEqual([i['amount'] for i in row.items],[2050,300]);self.assertEqual(row.number,'REQ-000001');self.assertEqual(row.status,'Awaiting approval')
        self.assertEqual(self.c.get(r.location).status_code,200)
    def test_new_retries_are_exact_and_actor_bound(self):
        token=secrets.token_urlsafe(32);r=self.submit(post_token=token)
        self.assertEqual(self.submit(post_token=token).location,r.location);self.assertEqual(self.submit(post_token=token,purpose='Changed').status_code,422)
        self.assertEqual(app.extensions['requisition_models']['request'].query.count(),1)
    def test_bad_items_precision_scope_and_status_are_atomic(self):
        for change in [dict(qty=['1e0','1']),dict(unit_price=['1e2','2']),dict(qty=['NaN','1']),dict(qty=['1.0001','1']),dict(qty=['0','1']),dict(unit_price=['1.001','2']),dict(unit_price=['-1','2']),dict(item=['']),dict(purpose=''),dict(campus='Unknown'),dict(category='Invented')]:
            self.assertEqual(self.submit(**change).status_code,422,change)
        self.assertEqual(app.extensions['requisition_models']['request'].query.count(),0)
        self.assertEqual(self.c.get('/workspace/finance/requisitions/mine?status=Invalid').status_code,422)
    def test_partial_approval_is_versioned_idempotent_and_does_not_post_money(self):
        self.submit();token=secrets.token_urlsafe(32);r=self.decide(post_token=token);self.assertEqual(r.status_code,302)
        self.assertEqual(self.decide(post_token=token).status_code,302)
        self.assertEqual(self.decide(post_token=token,approved='19').status_code,422)
        row=app.extensions['requisition_models']['request'].query.one();self.assertEqual((row.status,row.approved,row.version),('Approved',2000,2))
        self.assertEqual(self.j['journal'].query.count(),0)
        self.assertIn(b'20.00',self.c.get('/workspace/finance/requisitions/issue').data)
    def test_invalid_decision_and_stale_versions_do_not_mutate(self):
        self.submit()
        for change in [dict(approved='24'),dict(approved='0'),dict(version='0'),dict(decision='Paid'),dict(decision='Rejected',remarks='')]:self.assertEqual(self.decide(**change).status_code,422,change)
        self.assertEqual(app.extensions['requisition_models']['request'].query.one().status,'Awaiting approval')
    def test_cancel_is_owned_pending_only_and_rejection_records_reason(self):
        self.submit();self.submit(purpose='Second')
        data=dict(_csrf=self.csrf,version='1')
        self.assertEqual(self.c.post('/workspace/finance/requisitions/1/cancel',data=data).status_code,302)
        self.assertEqual(self.decide(rid=1).status_code,422)
        self.assertEqual(self.decide(rid=2,decision='Rejected',remarks='Not needed').status_code,302)
        self.assertEqual(self.c.post('/workspace/finance/requisitions/2/cancel',data=data).status_code,422)
    def test_wrong_account_class_and_obsolete_forms_cannot_post(self):
        form=dict(_csrf=self.csrf,version='0',prefix='REQ',settle_days='15',overdue_days='30',advance_account=str(self.expense.id))
        self.assertEqual(self.c.post('/workspace/finance/requisitions/settings',data=form).status_code,422)
        self.submit();self.decide()
        for action in ['issue','settle']:
            r=self.c.post('/workspace/finance/requisitions/1/'+action,data=dict(_csrf=self.csrf,amount='20',account_id=str(self.asset.id)));self.assertEqual(r.status_code,422);self.assertIn(b'current Issue Payment',r.data)
        self.assertEqual(self.j['journal'].query.count(),0)
    def test_rules_prefix_saved_with_version_and_invalid_days_rejected(self):
        form=dict(_csrf=self.csrf,version='0',prefix='isf',settle_days='10',overdue_days='20',block_open='1',carry_unspent='1',require_bill='1')
        self.assertEqual(self.c.post('/workspace/finance/requisitions/settings',data=form).status_code,302)
        row=app.extensions['requisition_models']['config'].query.one();self.assertEqual(row.data['prefix'],'ISF');self.assertTrue(row.data['require_bill'])
        self.assertEqual(self.c.post('/workspace/finance/requisitions/settings',data=form).status_code,422)
        form.update(version=str(row.version),settle_days='40');self.assertEqual(self.c.post('/workspace/finance/requisitions/settings',data=form).status_code,422)
        self.submit();self.assertEqual(app.extensions['requisition_models']['request'].query.one().number,'ISF-000001')
    def test_csrf_and_report_reconciliation_do_not_claim_books_link(self):
        self.assertEqual(self.submit(_csrf='bad').status_code,400)
        page=self.c.get('/workspace/finance/requisitions/reports');self.assertIn(b'Book reconciliation is unavailable',page.data)
        self.assertNotIn(b'agrees with your books',page.data)
