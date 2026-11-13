"""Shareholder money is balanced, isolated and append-only; fictional data only."""
import secrets,unittest
from datetime import date,datetime,timezone
from tests import test_finance_partners as fixture, test_identity as identity_fixture, test_staff_access as staff_fixture
from app import app,db

class ShareholderPostingTests(unittest.TestCase):
    setUp=fixture.FinancePartnerTests.setUp
    tearDown=fixture.FinancePartnerTests.tearDown
    account=fixture.FinancePartnerTests.account
    post=fixture.FinancePartnerTests.post
    partner=fixture.FinancePartnerTests.partner
    def movement(self,kind='contribution',**changes):
        data=dict(_csrf=self.csrf,post_token=secrets.token_urlsafe(32),version='1',day='2026-11-01',campus='Campus A',amount='100',cash_account=str(self.asset.id),notes='Fictional transaction',reference='QA')
        data.update(changes);return self.c.post('/workspace/finance/shareholders/1/record/'+kind,data=data)
    def reverse(self,mid,**changes):
        data=dict(_csrf=self.csrf,post_token=secrets.token_urlsafe(32),day='2026-11-02',notes='Correct fictional transaction',reference='QA-R',confirm='1');data.update(changes)
        return self.c.post(f'/workspace/finance/shareholders/1/reverse/{mid}',data=data)
    def balance(self,account):
        return sum(l.credit-l.debit for l in self.j['line'].query.filter_by(account_id=account.id))
    def test_capital_and_profit_postings_are_balanced_and_not_expenses(self):
        self.partner();self.assertEqual(self.movement().status_code,302)
        self.assertEqual(self.movement('withdrawal',amount='25').status_code,302)
        earnings=self.account('Approved distribution','Equity')
        self.post(account_id=[str(self.asset.id),str(earnings.id)],debit=['50',''],credit=['','50'])
        self.assertEqual(self.movement('profit',amount='10',distribution_account=str(earnings.id)).status_code,302)
        self.assertEqual(self.balance(self.equity),7500);self.assertEqual(self.balance(earnings),4000)
        self.assertEqual(self.balance(self.expense),0)
        for journal in self.j['journal'].query.all():
            lines=self.j['line'].query.filter_by(journal_id=journal.id).all();self.assertEqual(sum(x.debit for x in lines),sum(x.credit for x in lines))
        self.assertEqual(self.c.get('/workspace/finance/shareholders/1/transactions?from=2026-11-01&to=2026-11-30').status_code,200)
        self.assertEqual(app.extensions['shareholder_posting_models']['movement'].query.count(),3)
    def test_reversal_is_append_only_and_prevents_withdrawn_capital_removal(self):
        self.partner();self.movement();self.movement('withdrawal',amount='30')
        original=self.j['line'].query.filter_by(journal_id=1).first();saved=(original.debit,original.credit,original.snapshot)
        self.assertEqual(self.reverse(1).status_code,422)
        self.assertEqual(self.reverse(2).status_code,302)
        self.assertEqual(self.reverse(1).status_code,302);self.assertEqual(self.balance(self.equity),0)
        self.assertEqual(self.reverse(1).status_code,422)
        self.assertEqual((original.debit,original.credit,original.snapshot),saved)
        self.assertEqual(self.j['journal'].query.count(),4)
    def test_retries_changed_payload_and_cross_partner_reversals(self):
        self.partner();token=secrets.token_urlsafe(32)
        first=self.movement(post_token=token);self.assertEqual(first.status_code,302)
        self.assertEqual(self.movement(post_token=token).location,first.location)
        self.assertEqual(self.movement(post_token=token,amount='101').status_code,422)
        reverse_token=secrets.token_urlsafe(32);r=self.reverse(1,post_token=reverse_token)
        self.assertEqual(r.status_code,302);self.assertEqual(self.reverse(1,post_token=reverse_token).location,r.location)
        self.partner(name='Other partner',account_id='',equity='10')
        self.assertEqual(self.c.get('/workspace/finance/shareholders/2/reverse/1').status_code,404)
        self.assertEqual(self.j['journal'].query.count(),2)
    def test_account_scope_balance_period_and_form_guards_are_atomic(self):
        self.partner()
        for changes in [dict(amount='0'),dict(amount='NaN'),dict(amount='-1'),dict(amount='1.001'),dict(campus='Missing'),dict(cash_account=self.expense.id),dict(version='0'),dict(day='2025-01-01')]:
            self.assertEqual(self.movement(**changes).status_code,422,changes)
        self.assertEqual(self.movement(_csrf='bad').status_code,400)
        self.assertEqual(self.movement('withdrawal').status_code,422)
        self.assertEqual(self.movement('profit',distribution_account=self.equity.id).status_code,422)
        self.period.closed=True;db.session.commit();self.assertEqual(self.movement().status_code,422)
        self.assertEqual(self.j['journal'].query.count(),0)
    def test_campus_capital_future_activity_and_former_partner_guards(self):
        self.partner(campus='Campus A')
        self.assertEqual(self.movement(campus='Campus B').status_code,422)
        self.assertEqual(self.movement(day='2026-11-05').status_code,302)
        self.assertEqual(self.movement('withdrawal',day='2026-11-01',amount='1').status_code,422)
        self.assertEqual(self.movement('withdrawal',day='2026-11-06',amount='101').status_code,422)
        p=app.extensions['shareholder_model'].query.one();p.active=False;db.session.commit()
        self.assertEqual(self.movement(day='2026-11-06',version=str(p.version)).status_code,422)
    def test_statement_exports_and_profile_history(self):
        self.partner();self.movement(reference='=FORMULA',notes='=DANGEROUS')
        r=self.c.get('/workspace/finance/shareholders/1/transactions?from=2026-11-01&to=2026-11-30&export=csv')
        self.assertEqual(r.status_code,200);self.assertIn(b"'=FORMULA",r.data)
        for path in ['transactions?print=1','history','record/withdrawal','record/profit','reverse/1']:
            self.assertEqual(self.c.get('/workspace/finance/shareholders/1/'+path).status_code,200,path)
        revision=app.extensions['shareholder_posting_models']['revision'].query.one()
        self.assertIsNone(revision.before);self.assertEqual(revision.after['equity_bp'],5000)
        self.assertEqual(self.c.post('/workspace/finance/shareholders/1/edit',data=dict(_csrf=self.csrf,version='1',post_token=secrets.token_urlsafe(32),name='Changed',equity='40',account_id=self.equity.id,campus='Campus B',active='1')).status_code,422)
    def test_profit_distribution_needs_approved_equity_and_keeps_capital_separate(self):
        self.partner();earnings=self.account('Distribution reserve','Equity')
        self.assertEqual(self.movement('profit',distribution_account=earnings.id,amount='10').status_code,422)
        self.post(account_id=[str(self.asset.id),str(earnings.id)],debit=['20',''],credit=['','20'])
        self.assertEqual(self.movement('profit',distribution_account=earnings.id,amount='10').status_code,302)
        self.assertEqual(self.balance(self.equity),0);self.assertEqual(self.balance(earnings),1000)
        self.assertEqual(self.reverse(1).status_code,302);self.assertEqual(self.balance(earnings),2000)
        self.assertEqual(self.balance(self.expense),0)

    def test_shared_distribution_pool_cannot_be_overdrawn_by_backdated_payout(self):
        self.partner();earnings=self.account('Shared distribution reserve','Equity')
        self.post(account_id=[str(self.asset.id),str(earnings.id)],debit=['100',''],credit=['','100'])
        self.assertEqual(self.movement('profit',distribution_account=earnings.id,amount='80',day='2026-11-10').status_code,302)
        self.partner(name='Second partner',account_id='',equity='10')
        data=dict(_csrf=self.csrf,post_token=secrets.token_urlsafe(32),version='1',day='2026-11-01',campus='Campus A',amount='100',cash_account=self.asset.id,distribution_account=earnings.id)
        self.assertEqual(self.c.post('/workspace/finance/shareholders/2/record/profit',data=data).status_code,422)
        self.assertEqual(self.balance(earnings),2000)

class ShareholderIsolationTests(unittest.TestCase):
    setUp=identity_fixture.IdentityTests.setUp
    tearDown=identity_fixture.IdentityTests.tearDown
    csrf=identity_fixture.IdentityTests.csrf
    login=identity_fixture.IdentityTests.login
    seed=identity_fixture.IdentityTests.seed
    def test_other_school_cannot_read_or_post_to_partner_id(self):
        self.login();token=self.csrf();data=dict(_csrf=token,version='0',post_token=secrets.token_urlsafe(32),name='Private A Partner',equity='50',account_id='',active='1')
        self.assertEqual(self.client.post('/workspace/finance/shareholders/new',data=data).status_code,302)
        self.assertEqual(self.client.get('/workspace/finance/shareholders/1/history').status_code,200)
        self.login('TEST-B');token=self.csrf()
        for path in ['history','transactions','record/contribution','reverse/1']:
            self.assertEqual(self.client.get('/workspace/finance/shareholders/1/'+path).status_code,404,path)
        self.assertEqual(self.client.post('/workspace/finance/shareholders/1/record/contribution',data=dict(_csrf=token)).status_code,404)

    def test_private_school_capital_posts_and_survives_fresh_sign_in(self):
        from flask import g
        self.login()
        with app.test_request_context('/'):
            g.institute_engine=app.extensions['identity_helpers']['engine'](self.a);db.session.remove()
            F=app.extensions['finance_models'];stamp=dict(created_at=datetime.now(timezone.utc),updated_at=datetime.now(timezone.utc),created_by='QA',updated_by='QA')
            ga=F['group'](name='Assets',account_class='Assets',active=True,**stamp);ge=F['group'](name='Equity',account_class='Equity',active=True,**stamp);db.session.add_all([ga,ge]);db.session.flush()
            cash=F['account'](name='QA cash',code=1001,group_id=ga.id,inactive=False,**stamp);equity=F['account'](name='QA capital',code=3001,group_id=ge.id,inactive=False,**stamp);db.session.add_all([cash,equity]);db.session.add(F['period'](begin=date(2026,1,1),end=date(2026,12,31),closed=False,**stamp));db.session.commit();cash_id=cash.id;equity_id=equity.id;db.session.remove()
        g.pop('institute_engine',None)
        token=self.csrf();self.assertEqual(self.client.post('/workspace/finance/shareholders/new',data=dict(_csrf=token,version='0',post_token=secrets.token_urlsafe(32),name='Private capital owner',equity='50',account_id=equity_id,campus='Campus Only School A',active='1')).status_code,302)
        data=dict(_csrf=token,version='1',post_token=secrets.token_urlsafe(32),day='2026-11-01',campus='Campus Only School A',cash_account=cash_id,amount='100')
        self.assertEqual(self.client.post('/workspace/finance/shareholders/1/record/contribution',data=data).status_code,302)
        data.update(post_token=secrets.token_urlsafe(32),amount='20');self.assertEqual(self.client.post('/workspace/finance/shareholders/1/record/withdrawal',data=data).status_code,302)
        self.login();page=self.client.get('/workspace/finance/shareholders/1/transactions?from=2026-11-01&to=2026-11-30');self.assertEqual(page.status_code,200);self.assertIn(b'Capital withdrawal',page.data)
        with app.test_request_context('/'):
            g.institute_engine=app.extensions['identity_helpers']['engine'](self.a);db.session.remove()
            Line=app.extensions['ledger_models']['line'];self.assertEqual(sum(x.credit-x.debit for x in Line.query.filter_by(account_id=equity_id)),8000);db.session.remove()
        g.pop('institute_engine',None)

class ShareholderStaffTests(unittest.TestCase):
    setUp=staff_fixture.StaffAccessTests.setUp
    tearDown=staff_fixture.StaffAccessTests.tearDown
    csrf=staff_fixture.StaffAccessTests.csrf
    login=staff_fixture.StaffAccessTests.login
    token=staff_fixture.StaffAccessTests.token
    tenant=staff_fixture.StaffAccessTests.tenant
    password=staff_fixture.StaffAccessTests.password
    def test_staff_need_create_delete_export_and_cash_permissions(self):
        def seed():
            F=app.extensions['finance_models'];P=app.extensions['shareholder_model'];stamp=dict(created_at=datetime.now(timezone.utc),updated_at=datetime.now(timezone.utc),created_by='QA',updated_by='QA')
            ga=F['group'](name='Assets',account_class='Assets',active=True,**stamp);ge=F['group'](name='Equity',account_class='Equity',active=True,**stamp);db.session.add_all([ga,ge]);db.session.flush()
            a=F['account'](name='Allowed cash',code=1001,group_id=ga.id,inactive=False,**stamp);e=F['account'](name='Capital',code=3001,group_id=ge.id,inactive=False,**stamp);db.session.add_all([a,e]);db.session.flush();self.aid=a.id
            db.session.add(F['period'](begin=date(2026,1,1),end=date(2026,12,31),closed=False,**stamp))
            db.session.add(P(name='Fictional Partner',equity_bp=5000,account_id=e.id,campus='Campus A',active=True,token=secrets.token_urlsafe(32),created_at=datetime.now(timezone.utc),updated_at=datetime.now(timezone.utc),created_by='Fixture',updated_by='Fixture',created_key='fixture'))
        self.tenant(seed)
        def grant(create=False,delete=False,cash=False,two=False):
            def change():
                p=db.session.get(self.Staff,self.sid);permissions={'finance.view':['Campus A','Campus B']}
                if create:permissions['finance.create']=['Campus A','Campus B']
                if delete:permissions['finance.delete']=['Campus A','Campus B']
                p.data={**p.data,'permissions':permissions,'accounts':['Allowed cash'] if cash else [],'two_step':two}
            self.tenant(change);self.login()
        grant()
        self.assertEqual(self.c.get('/workspace/finance/shareholders/1/record/contribution').status_code,200)
        data=dict(_csrf=self.token(),post_token=secrets.token_urlsafe(32),version='1',day='2026-11-01',campus='Campus A',amount='100',cash_account=self.aid)
        path='/workspace/finance/shareholders/1/record/contribution'
        self.assertEqual(self.c.post(path,data=data).status_code,403)
        self.assertEqual(self.c.get('/workspace/finance/shareholders/1/transactions?export=csv').status_code,403)
        grant(create=True);data['_csrf']=self.token();self.assertEqual(self.c.post(path,data=data).status_code,403)
        grant(create=True,cash=True);data['_csrf']=self.token();self.assertEqual(self.c.post(path,data=data).status_code,302)
        reverse=dict(_csrf=self.token(),post_token=secrets.token_urlsafe(32),day='2026-11-02',confirm='1',notes='Permission check')
        self.assertEqual(self.c.post('/workspace/finance/shareholders/1/reverse/1',data=reverse).status_code,403)
        grant(create=True,delete=True,cash=True,two=True);reverse['_csrf']=self.token()
        self.assertEqual(self.c.post('/workspace/finance/shareholders/1/reverse/1',data=reverse).status_code,403)

if __name__=='__main__':unittest.main()
