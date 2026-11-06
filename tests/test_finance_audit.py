"""Historical cohort, deletion retention, financial reconciliation and access tests."""
import secrets,unittest
from datetime import date
from flask import template_rendered
from app import app,db
from tests import test_operations as ops_fixture
from tests import test_finance_reports as ledger_fixture

class FeeAuditTests(unittest.TestCase):
    setUp=ops_fixture.OperationTests.setUp
    tearDown=ops_fixture.OperationTests.tearDown
    bill=ops_fixture.OperationTests.bill
    post=ops_fixture.OperationTests.post
    def load(self,path='fees',**args):
        captured=[]
        def receive(sender,template,context,**kw):captured.append(context)
        template_rendered.connect(receive,app)
        try:
            r=self.client.get('/workspace/finance/audit/'+('challans/voided' if path=='challans' else path),query_string={'from':'2026-09-01','to':'2026-11-30',**args})
            self.assertEqual(r.status_code,200,r.data)
            return captured[-1],r
        finally:template_rendered.disconnect(receive,app)
    def test_cohort_stays_at_generation_after_promotion(self):
        detail=self.rm['student'](student_id=self.s.id,data=dict(campus='Campus A',section='A',academic_session='2026'));db.session.add(detail);db.session.commit()
        b=self.bill();self.s.class_name='Next Class';detail.data={**detail.data,'campus':'Campus B'};db.session.commit()
        c,r=self.load(class_name='Test Class',tab='students');self.assertEqual(c['count'],1);self.assertTrue(c['rows'][0]['moved']);self.assertIn(b'moved since',r.data)
        c,_=self.load(campus='Campus B');self.assertEqual(c['count'],0)
    def test_hard_delete_retains_event_and_allows_reused_bill_id(self):
        b=self.bill();bid=b.id;db.session.delete(b);db.session.commit()
        models=app.extensions['finance_audit_models'];e=models['event'].query.one();self.assertEqual((e.kind,e.data['amount']),('Generated challan deleted',100000))
        fresh=self.bill(20000);self.assertEqual(models['cohort'].query.filter_by(active=True).count(),1)
        self.assertEqual(models['cohort'].query.count(),2);self.assertEqual(e.data['amount'],100000)
        c,r=self.load('challans',**{'from':'2020-01-01','to':'2030-01-01'});self.assertEqual(c['count'],1);self.assertIn(b'Generated challan deleted',r.data)
    def test_change_and_void_capture_actual_amounts_with_rollback(self):
        b=self.bill();b.lines=[dict(particular='Tuition',amount=120000)];db.session.flush();db.session.rollback()
        Event=app.extensions['finance_audit_models']['event'];self.assertEqual(Event.query.count(),0)
        b=db.session.get(self.m['bill'],b.id);b.lines=[dict(particular='Tuition',amount=110000)];db.session.commit()
        self.assertEqual(Event.query.one().data['delta'],10000)
        token='fictional_token_abcdefghijklmn';self.assertEqual(self.post('/workspace/pay',student_id=self.s.id,bill_id=b.id,token=token,paid_date='2026-10-01',account='Cash',**{f'amount_{b.id}':'50',f'discount_{b.id}':'10'}).status_code,302)
        receipt=self.m['receipt'].query.one();self.assertEqual(self.post('/workspace/reverse-receipts',ids=str(receipt.id),confirm='yes').status_code,302)
        self.assertEqual({e.kind for e in Event.query.all()},{'Amount increased','Payment voided','Discount voided'})
        self.assertEqual(Event.query.filter_by(kind='Payment voided').one().data['receipt_amount'],5000)
    def test_legacy_cohort_is_not_falsely_classified(self):
        b=self.bill();C=app.extensions['finance_audit_models']['cohort'];db.session.query(C).delete();db.session.commit()
        c,r=self.load();self.assertEqual(c['unknown'],1);self.assertIn(b'Historical class/campus are unavailable',r.data)
        c,_=self.load(class_name='Test Class');self.assertEqual(c['count'],0)
    def test_receipts_pending_and_unknown_head_allocations(self):
        b=self.bill();b.lines=[dict(particular='Tuition',amount=60000),dict(particular='Books',amount=40000)];b.paid=5000;b.discount=1000
        db.session.add(self.m['receipt'](student_id=self.s.id,bill_id=b.id,amount=5000,discount=1000,day=date(2026,9,1),account='Cash',token='fictional-one'))
        db.session.add(self.m['workflow'](kind='staff-payment-approval',status='Pending',data={'bills':[{'id':b.id}],'form':{f'amount_{b.id}':'20'}}));db.session.commit()
        c,r=self.load();self.assertEqual((c['totals']['cleared'],c['totals']['pending'],c['totals']['collected'],c['totals']['remaining']),(5000,2000,7000,94000));self.assertEqual(c['unallocated_paid'],5000);self.assertIn(b'Allocation unavailable',r.data)
        r=self.client.get('/workspace/finance/audit/fees?from=2026-01-01&to=2026-12-31&tab=students&export=csv');self.assertEqual(r.status_code,200);self.assertIn(b'1000.00,50.00,20.00,10.00,940.00',r.data)
    def test_student_detail_ignores_current_class_filter(self):
        a=self.bill();self.s.class_name='Next Class';db.session.commit();b=self.bill(month='2026-10')
        c,_=self.load(class_name='Test Class',tab='students',sid=self.s.id);self.assertEqual(c['count'],1);self.assertEqual(len(c['drill']),2)
        self.load(tab='students',print='1');self.load('challans',print='1')
        self.assertEqual(self.client.get('/workspace/finance/audit/fees?from=bad').status_code,422)

class LedgerAdditionTests(unittest.TestCase):
    setUp=ledger_fixture.FinanceReportsTests.setUp
    tearDown=ledger_fixture.FinanceReportsTests.tearDown
    account=ledger_fixture.FinanceReportsTests.account
    post=ledger_fixture.FinanceReportsTests.post
    void=ledger_fixture.FinanceReportsTests.void
    correction=ledger_fixture.FinanceReportsTests.correction
    def test_narration_retry_and_correction_history(self):
        token=secrets.token_urlsafe(32);r=self.post(narration='Fictional entry',post_token=token);self.assertEqual(r.status_code,302)
        self.assertEqual(self.post(narration='Changed entry',post_token=token).status_code,422)
        j=self.j['journal'].query.one();self.assertEqual(j.note.narration,'Fictional entry');self.assertIn(b'Fictional entry',self.c.get(r.location).data)
        self.assertEqual(self.correction(j.id,narration='Corrected header').status_code,302);self.assertEqual(j.note.narration,'Fictional entry')
        self.assertEqual(self.j['note'].query.count(),2)
    def test_voided_report_excludes_live_and_reversal_lines(self):
        self.post();self.post();ids=[r.id for r in self.j['journal'].query.all()];self.void([ids[0]])
        r=self.c.get('/workspace/finance/reports/voided?from=2026-01-01&to=2026-12-31');self.assertEqual(r.status_code,200);self.assertIn(b'Showing 2 / 2 line items',r.data)
        self.assertIn(b'Voided Transactions',r.data);self.assertIn(b'/voided?',r.data)
        r=self.c.get('/workspace/finance/ledger/setup');self.assertEqual(r.status_code,200);self.assertIn(b'every journal balances',r.data)
    def test_period_name_round_trip(self):
        r=self.c.post('/workspace/finance/periods/new',data=dict(_csrf=self.csrf,version='0',name='FY 2027',begin='2027-01-01',end='2027-12-31',closed='0'));self.assertEqual(r.status_code,302)
        self.assertIn(b'FY 2027',self.c.get('/workspace/finance/periods').data)
