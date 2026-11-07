"""Report reconciliation and append-only corrections using fictional journals."""
import secrets,unittest
from flask import template_rendered
from tests import test_finance_ledger as fixture
from app import app,db

class FinanceReportsTests(unittest.TestCase):
    setUp=fixture.FinanceLedgerTests.setUp
    tearDown=fixture.FinanceLedgerTests.tearDown
    account=fixture.FinanceLedgerTests.account
    post=fixture.FinanceLedgerTests.post
    def load(self,mode,**args):
        captured=[]
        def receive(sender,template,context,**kw):captured.append(context)
        template_rendered.connect(receive,app)
        try:
            r=self.c.get('/workspace/finance/reports/'+mode,query_string={'from':'2026-11-01','to':'2026-11-30',**args})
            self.assertEqual(r.status_code,200,r.data)
            return captured[-1],r
        finally:template_rendered.disconnect(receive,app)
    def correction(self,jid,**changes):
        data=dict(_csrf=self.csrf,action_token=secrets.token_urlsafe(32),day='2026-11-02',campus='Campus A',account_id=[str(self.asset.id),str(self.income.id)],debit=['70',''],credit=['','70'],memo=['correct cash','correct income']);data.update(changes)
        return self.c.post(f'/workspace/finance/reports/journal/{jid}/edit',data=data)
    def void(self,ids,**changes):
        data=dict(_csrf=self.csrf,action_token=secrets.token_urlsafe(32),journal_ids=[str(i) for i in ids],confirm='1');data.update(changes)
        return self.c.post('/workspace/finance/reports/journal/void',data=data)
    def test_three_pages_filters_print_and_empty_daily_state(self):
        for mode in ['journals','general','daily']:
            context,r=self.load(mode);self.assertIn(b'Campus A',r.data)
        self.assertFalse(context['generated'])
        for mode in ['journals','general','daily']:self.load(mode,print='1')
        self.assertEqual(self.j['journal'].query.count(),0)
    def test_inquiry_detail_and_general_line_filters(self):
        self.post();jid=self.j['journal'].query.one().id
        context,r=self.load('journals',trans_id=str(jid),amount='100');self.assertEqual(context['total'],1);self.assertEqual(len(context['details'][jid]),2)
        self.assertIn(b'View transaction',r.data)
        c,_=self.load('general');self.assertEqual(c['total'],2);self.assertEqual([n for _,_,n in c['rows']],[1,2])
        c,_=self.load('general',side='cr',account_name='School income',line_item='2',memo='income entry');self.assertEqual(c['total'],1)
        c,_=self.load('general',payment_id='12');self.assertEqual(c['total'],0)
    def test_correction_preserves_original_and_nets_replacement_once(self):
        self.post();original=self.j['journal'].query.one();jid=original.id;token=secrets.token_urlsafe(32)
        get=self.c.get(f'/workspace/finance/reports/journal/{jid}/edit');self.assertEqual(get.status_code,200);self.assertIn(b'value="100.00"',get.data)
        response=self.correction(jid,action_token=token);self.assertEqual(response.status_code,302,response.data)
        self.assertEqual(self.j['journal'].query.count(),3);self.assertEqual(db.session.get(self.j['journal'],jid).day.isoformat(),'2026-11-01')
        self.assertEqual(self.correction(jid,action_token=token).location,response.location)
        self.assertEqual(self.correction(jid,action_token=token,debit=['80','']).status_code,422)
        context,_=self.load('daily',generate='1');self.assertEqual((context['total_income'],context['closing_total']),(7000,7000))
        c,_=self.load('journals');self.assertEqual(c['total'],1)
        c,r=self.load('journals',state='corrected');self.assertEqual(c['total'],1);self.assertIn(b'Corrected',r.data)
        self.assertEqual(self.correction(jid).status_code,422)
    def test_bulk_void_is_atomic_and_exact_retry_safe(self):
        self.post();jid=self.j['journal'].query.one().id;token=secrets.token_urlsafe(32)
        self.assertEqual(self.void([jid],confirm='0').status_code,422);self.assertEqual(self.j['journal'].query.count(),1)
        self.assertEqual(self.void([jid],action_token=token).status_code,302)
        self.assertEqual(self.void([jid],action_token=token).status_code,302);self.assertEqual(self.j['journal'].query.count(),2)
        c,_=self.load('daily',generate='1');self.assertEqual((c['total_income'],c['closing_total']),(0,0))
        c,_=self.load('journals');self.assertEqual(c['total'],0)
        c,_=self.load('journals',state='voided');self.assertEqual(c['total'],1)
        self.assertEqual(self.correction(jid).status_code,422)
    def test_closed_period_and_invalid_correction_preserve_all_entries(self):
        self.post();jid=self.j['journal'].query.one().id
        self.assertEqual(self.correction(jid,credit=['','1']).status_code,422)
        self.assertEqual(self.correction(jid,day='2027-01-01').status_code,422)
        self.period.closed=True;db.session.commit()
        self.assertEqual(self.void([jid]).status_code,422);self.assertEqual(self.correction(jid).status_code,422)
        self.assertEqual(self.j['journal'].query.count(),1)
    def test_mixed_bulk_rollback(self):
        self.post();self.post();ids=[j.id for j in self.j['journal'].query.order_by(self.j['journal'].id)]
        self.void([ids[0]]);before=self.j['journal'].query.count()
        self.assertEqual(self.void(ids).status_code,422);self.assertEqual(self.j['journal'].query.count(),before)
        self.assertEqual(app.extensions['journal_change_models']['change'].query.count(),1)
    def test_daily_independent_opening_income_expense_and_tabs(self):
        self.post(day='2026-10-01',account_id=[str(self.asset.id),str(self.equity.id)])
        self.post('income',account_id=[str(self.income.id)],amount=['17'],memo=['Fee'],counter_account=str(self.asset.id))
        self.post('expense',account_id=[str(self.expense.id)],amount=['1.50'],memo=['Trash'],counter_account=str(self.asset.id))
        c,_=self.load('daily',generate='1');self.assertEqual((c['opening_total'],c['closing_total'],c['total_income'],c['total_expense']),(10000,11550,1700,150));self.assertEqual(c['received'],{self.asset.id:1700})
        for tab in ['combine','balance','income','expense']:
            c,r=self.load('daily',tab=tab,generate='1',print='1');self.assertEqual(c['total_income'],1700)
            self.assertEqual(b'<h3>Income Statement</h3>' in r.data,tab in ['combine','income']);self.assertEqual(b'<h3>Expense Statement</h3>' in r.data,tab in ['combine','expense'])
    def test_mixed_journal_does_not_invent_receiving_account(self):
        self.post(account_id=[str(self.asset.id),str(self.expense.id),str(self.income.id)],debit=['80','20',''],credit=['','','100'],memo=['Cash','Cost','Income'])
        c,_=self.load('daily',generate='1');self.assertEqual(c['received'],{});self.assertEqual(c['unallocated'],10000)
    def test_page_order_and_print_are_complete(self):
        for i in range(26):self.post()
        c,_=self.load('journals',size='25');self.assertEqual(c['total'],26);self.assertEqual([j.id for j,_ in c['rows']],list(range(26,1,-1)))
        c,_=self.load('journals',size='25',page='2');self.assertEqual([j.id for j,_ in c['rows']],[1])
        c,_=self.load('journals',size='25',print='1');self.assertEqual(len(c['rows']),26)
        c,_=self.load('general',size='25',page='2');self.assertEqual(c['total'],52);self.assertEqual(len(c['rows']),25)
    def test_csrf_and_audit_date_filters(self):
        self.post();jid=self.j['journal'].query.one().id
        self.assertEqual(self.void([jid],_csrf='bad').status_code,400)
        c,_=self.load('journals',created_at='2020-01-01');self.assertEqual(c['total'],0)
        for mode in ['general','journals']:
            self.assertEqual(self.c.get('/workspace/finance/reports/'+mode,query_string={'created_at':'bad'}).status_code,422)

    def test_expense_and_income_correction_prefills_counter_and_reconciles(self):
        for kind,account in [('expense',self.expense),('income',self.income)]:
            response=self.post(kind,account_id=[str(account.id)],amount=['12.34'],memo=['Original row'],counter_account=str(self.asset.id))
            self.assertEqual(response.status_code,302);jid=int(response.location.rsplit('/',1)[1])
            page=self.c.get(f'/workspace/finance/reports/journal/{jid}/edit');self.assertEqual(page.status_code,200)
            self.assertIn(b'value="12.34"',page.data);self.assertIn(b'Original row',page.data)
            response=self.correction(jid,account_id=[str(account.id)],amount=['10.25'],memo=['Corrected row'],counter_account=str(self.asset.id))
            self.assertEqual(response.status_code,302,response.data)
        c,_=self.load('daily',generate='1');self.assertEqual((c['total_income'],c['total_expense'],c['closing_total']),(1025,1025,0))
