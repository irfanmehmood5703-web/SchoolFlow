"""Atomic cash-basis fee posting, reversals, permissions and report linkage."""
import secrets,unittest
from datetime import date
from app import app,db,Student
from tests import test_finance_ledger as fixture

class FeeLedgerTests(unittest.TestCase):
    setUp=fixture.FinanceLedgerTests.setUp
    tearDown=fixture.FinanceLedgerTests.tearDown
    account=fixture.FinanceLedgerTests.account
    def seed(self,amount=10000,student=None,month='2026-11'):
        M=app.extensions['record_models'];O=app.extensions['ops_models']
        if student is None:
            student=Student(admission_no=secrets.token_hex(4),name='Fictional Fee Posting',class_name='One',status='Active');db.session.add(student);db.session.flush();db.session.add(M['student'](student_id=student.id,data={'campus':'Campus A'}))
        bill=O['bill'](student_id=student.id,month=month,due=date(2026,11,10),lines=[{'particular':'Tuition Fee','amount':amount}]);db.session.add(bill);db.session.commit();return student,bill
    def config(self,**changes):
        C=app.extensions['fee_ledger_models']['config'];c=db.session.get(C,1)
        data=dict(_csrf=self.csrf,version=str(c.version if c else 0),enabled='1',income_account=str(self.income.id),discount_account=str(self.expense.id),receiving_name=['Cash in Hand'],asset_id=[str(self.asset.id)]);data.update(changes)
        return self.c.post('/workspace/finance/fee-posting',data=data)
    def pay(self,s,b,amount='80',discount='20',**changes):
        data=dict(_csrf=self.csrf,student_id=s.id,bill_id=b.id,mode='current',token=secrets.token_urlsafe(24),paid_date='2026-11-01',account='Cash in Hand',**{'amount_'+str(b.id):amount,'discount_'+str(b.id):discount});data.update(changes)
        return self.c.post('/workspace/pay',data=data)
    def net(self,account):return sum(x.debit-x.credit for x in self.j['line'].query.filter_by(account_id=account.id))
    def test_disabled_default_and_settings_validation(self):
        s,b=self.seed();self.assertEqual(self.pay(s,b).status_code,302);self.assertEqual(self.j['journal'].query.count(),0)
        self.assertEqual(self.config(income_account=str(self.asset.id)).status_code,422)
        self.assertEqual(self.config(receiving_name=['Cash in Hand','cash in hand'],asset_id=[str(self.asset.id)]*2).status_code,422)
        self.assertEqual(self.config().status_code,302)
        self.assertEqual(self.config(version='0').status_code,422)
        self.assertEqual(self.c.post('/workspace/finance/fee-posting',data={'_csrf':'bad'}).status_code,400)
        self.assertEqual(self.c.get('/workspace/finance/fee-posting').status_code,200)
        self.assertEqual(self.j['journal'].query.count(),0) # no historical backfill
    def test_receipt_discount_balanced_snapshot_and_duplicate_retry(self):
        self.config();s,b=self.seed();token=secrets.token_urlsafe(24)
        self.assertEqual(self.pay(s,b,token=token).status_code,302)
        self.assertEqual((b.paid,b.discount,self.net(self.asset),self.net(self.expense),self.net(self.income)),(8000,2000,8000,2000,-10000))
        P=app.extensions['fee_ledger_models']['posting'];link=P.query.one();self.assertEqual(link.source['amount'],8000)
        self.assertEqual(self.pay(s,b,token=token).status_code,422);self.assertEqual(P.query.count(),1);self.assertEqual(self.j['journal'].query.count(),1)
        self.assertEqual(self.c.get('/workspace/finance/reports/general?from=2026-11-01&to=2026-11-30&payment_id='+str(link.receipt_id)).status_code,200)
        self.assertEqual(self.c.get(f'/workspace/finance/reports/journal/{link.journal_id}/edit').status_code,422)
    def test_missing_mapping_retired_account_and_closed_period_roll_back_both_sides(self):
        self.config();s,b=self.seed()
        self.assertEqual(self.pay(s,b,account='Unmapped').status_code,422)
        self.period.closed=True;db.session.commit();self.assertEqual(self.pay(s,b).status_code,422)
        self.period.closed=False;self.asset.inactive=True;db.session.commit();self.assertEqual(self.pay(s,b).status_code,422)
        self.assertEqual((b.paid,b.discount),(0,0));self.assertEqual(app.extensions['ops_models']['receipt'].query.count(),0);self.assertEqual(self.j['journal'].query.count(),0)
    def test_discount_only_does_not_require_receiving_asset(self):
        self.config();s,b=self.seed();self.assertEqual(self.pay(s,b,amount='0',discount='100',account='Unmapped').status_code,302)
        self.assertEqual((self.net(self.asset),self.net(self.expense),self.net(self.income)),(0,10000,-10000))
    def test_reversal_uses_original_snapshots_even_after_disabling_and_retiring_accounts(self):
        self.config();s,b=self.seed();self.pay(s,b);P=app.extensions['fee_ledger_models']['posting'];link=P.query.one();receipt=app.extensions['ops_models']['receipt'].query.one()
        self.config(enabled='');self.asset.name='Renamed cash';self.asset.inactive=True;db.session.commit()
        self.assertEqual(self.c.post('/workspace/reverse-receipts',data={'_csrf':self.csrf,'confirm':'yes','ids':str(receipt.id)}).status_code,302)
        self.assertTrue(receipt.voided);self.assertIsNotNone(link.reversal_id);self.assertEqual((self.net(self.asset),self.net(self.expense),self.net(self.income)),(0,0,0));self.assertEqual((b.paid,b.discount),(0,0))
        snapshots=[x.snapshot['name'] for x in self.j['line'].query.filter_by(journal_id=link.reversal_id)];self.assertIn('Cash',snapshots);self.assertNotIn('Renamed cash',snapshots)
        self.assertEqual(self.c.post('/workspace/reverse-receipts',data={'_csrf':self.csrf,'confirm':'yes','ids':str(receipt.id)}).status_code,422);self.assertEqual(self.j['journal'].query.count(),2)
    def test_closed_current_period_reversal_preserves_receipt_and_challan(self):
        self.config();s,b=self.seed();self.pay(s,b);r=app.extensions['ops_models']['receipt'].query.one();self.period.closed=True;db.session.commit()
        self.assertEqual(self.c.post('/workspace/reverse-receipts',data={'_csrf':self.csrf,'confirm':'yes','ids':str(r.id)}).status_code,422)
        self.assertFalse(r.voided);self.assertEqual(b.paid,8000);self.assertEqual(self.j['journal'].query.count(),1)
    def test_direct_and_family_batches_and_atomic_rejection(self):
        self.config();s,a=self.seed();_,b=self.seed(student=s);R=app.extensions['record_models'];detail=R['student'].query.filter_by(student_id=s.id).one();detail.data={**detail.data,'family_no':'F-QA'};db.session.commit()
        data=dict(_csrf=self.csrf,number=str(s.id),lookup='sid',paid_date='2026-11-01',account='Cash in Hand',token=secrets.token_urlsafe(24),**{'amount_'+str(a.id):'50','amount_'+str(b.id):'101'})
        self.assertEqual(self.c.post('/workspace/direct-payment',data=data).status_code,422);self.assertEqual(a.paid,0);self.assertEqual(self.j['journal'].query.count(),0)
        data['amount_'+str(b.id)]='50';self.assertEqual(self.c.post('/workspace/direct-payment',data=data).status_code,302);self.assertEqual(self.j['journal'].query.count(),2)
        data.update(number='F-QA',token=secrets.token_urlsafe(24));self.assertEqual(self.c.post('/workspace/family-payment',data=data).status_code,302);self.assertEqual(self.j['journal'].query.count(),4)
        self.assertEqual(self.net(self.asset),20000)

    def test_moved_student_cannot_hide_original_posting_from_scoped_reversal(self):
        from flask import g
        from werkzeug.exceptions import Forbidden
        from werkzeug.security import generate_password_hash
        from app import Employee
        self.config();s,b=self.seed();self.pay(s,b);receipt=app.extensions['ops_models']['receipt'].query.one()
        detail=app.extensions['record_models']['student'].query.filter_by(student_id=s.id).one();detail.data={'campus':'Campus B'}
        employee=Employee(employee_no='SCOPED',name='Fictional scoped staff',role='Teacher');db.session.add(employee);db.session.flush()
        Staff=app.extensions['staff_account_model'];staff=Staff(employee_id=employee.id,username='scoped',password_hash=generate_password_hash('FictionalPassword123'),data={});db.session.add(staff);db.session.commit()
        with app.test_request_context('/'):
            g.staff_principal=staff;g.access_campuses={'Campus B'}
            with self.assertRaises(Forbidden):app.extensions['fee_ledger_helpers']['reverse'](receipt)
        db.session.rollback();self.assertIsNone(app.extensions['fee_ledger_models']['posting'].query.one().reversal_id);self.assertFalse(receipt.voided);self.assertEqual(self.net(self.asset),8000)
