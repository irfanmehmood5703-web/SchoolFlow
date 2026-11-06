"""Finance master validation, snapshots, reserved codes and reference guards."""
import os,unittest
os.environ['DATABASE_URL']='sqlite:///:memory:'
from app import app,db

class FinanceSetupTests(unittest.TestCase):
    def setUp(self):
        app.config.update(TESTING=True,IDENTITY_ENFORCE_IN_TESTS=False,SECRET_KEY='fictional-finance-test')
        self.ctx=app.app_context();self.ctx.push();db.drop_all();db.create_all()
        self.m=app.extensions['finance_models'];self.c=app.test_client();self.c.get('/workspace/finance/groups')
        with self.c.session_transaction() as session:self.token=session['record_csrf']
    def tearDown(self):db.session.remove();db.drop_all();self.ctx.pop()
    def post(self,path,**data):return self.c.post('/workspace/finance/'+path,data={'_csrf':self.token,**data})
    def group(self,name='Current Assets',cls='Assets'):
        r=self.post('groups/new',name=name,account_class=cls,active='1',version='0');self.assertEqual(r.status_code,302,r.data)
        return self.m['group'].query.filter_by(name=name).one()
    def account(self,group,name='Cash',**changes):
        data=dict(name=name,group_id=str(group.id),inactive='0',version='0');data.update(changes)
        r=self.post('accounts/new',**data);self.assertEqual(r.status_code,302,r.data)
        return self.m['account'].query.filter_by(name=name).one()
    def test_empty_lists_and_forms_do_not_seed_and_menus_route(self):
        for path in ['periods','groups','accounts','periods/new','groups/new','accounts/new','chart-of-accounts']:
            r=self.c.get('/workspace/finance/'+path);self.assertEqual(r.status_code,200,path)
        self.assertEqual(self.m['group'].query.count(),0)
        for key,endpoint in [('periods','periods'),('groups','groups'),('accounts','accounts')]:
            self.assertIn(('/workspace/finance/'+endpoint).encode(),self.c.get('/workspace/finance/ledger/setup').data)
    def test_period_dates_overlap_stale_close_and_delete(self):
        self.assertEqual(self.post('periods/new',begin='2026-12-31',end='2026-01-01',closed='0',version='0').status_code,422)
        self.assertEqual(self.post('periods/new',begin='2026-01-01',end='2026-12-31',closed='0',version='0').status_code,302)
        row=self.m['period'].query.one();self.assertTrue(row.created_by)
        self.assertEqual(self.post('periods/new',begin='2026-12-31',end='2027-12-31',closed='0',version='0').status_code,422)
        self.assertEqual(self.post(f'periods/{row.id}/edit',begin='2026-01-01',end='2026-12-31',closed='1',version='0').status_code,422)
        self.assertEqual(self.post(f'periods/{row.id}/edit',begin='2026-01-01',end='2026-12-31',closed='1',version=str(row.version)).status_code,302)
        self.assertTrue(row.closed)
        self.assertEqual(self.post(f'periods/{row.id}/edit',begin='2026-01-02',end='2026-12-31',closed='1',version=str(row.version)).status_code,422)
        self.assertEqual(self.post(f'periods/{row.id}',action='delete',confirm='0',version=str(row.version)).status_code,422)
        self.assertEqual(self.post(f'periods/{row.id}',action='delete',confirm='1',version=str(row.version)).status_code,302)
    def test_standard_groups_are_explicit_idempotent_and_no_accounts_created(self):
        self.assertEqual(self.post('groups/initialize').status_code,302)
        self.assertEqual(self.post('groups/initialize').status_code,302)
        self.assertEqual(self.m['group'].query.count(),11);self.assertEqual(self.m['account'].query.count(),0)
    def test_duplicate_names_invalid_classes_and_csrf_are_rejected(self):
        self.assertEqual(self.c.post('/workspace/finance/groups/new',data={'name':'No token'}).status_code,400)
        self.group()
        self.assertEqual(self.post('groups/new',name='current assets',account_class='Assets',active='1',version='0').status_code,422)
        self.assertEqual(self.post('groups/new',name='Bogus',account_class='Invalid',active='1',version='0').status_code,422)
        self.assertEqual(self.post('accounts/new',name='Bogus',group_id='9999999999999999999999999',inactive='0',version='0').status_code,422)
    def test_codes_are_server_owned_unique_and_skip_reserved_ranges(self):
        for name,cls,minimum in [('Current Assets','Assets',1000),('Custom Liabilities','Liabilities',2100),('Custom Income','Income',4100),('Custom Equity','Equity',3000),('Custom Expense','Expense',5000)]:
            group=self.group(name,cls);one=self.account(group,name+' A',code='4000');two=self.account(group,name+' B',code='2000')
            self.assertEqual(one.code,minimum);self.assertEqual(two.code,minimum+1)
            self.assertFalse(2000<=one.code<=2099 or 4000<=one.code<=4099)
    def test_references_group_class_and_inactive_selection_are_protected(self):
        group=self.group();account=self.account(group)
        self.assertEqual(self.post(f'groups/{group.id}',action='delete',confirm='1',version=str(group.version)).status_code,422)
        self.assertEqual(self.post(f'groups/{group.id}/edit',name=group.name,account_class='Income',active='1',version=str(group.version)).status_code,422)
        self.assertEqual(self.post(f'groups/{group.id}/edit',name=group.name,account_class='Assets',active='0',version=str(group.version)).status_code,302)
        self.assertEqual(self.post('accounts/new',name='Other',group_id=str(group.id),inactive='0',version='0').status_code,422)
        self.assertEqual(self.post(f'accounts/{account.id}/edit',name='Cash renamed',group_id=str(group.id),inactive='1',version=str(account.version)).status_code,302)
        self.assertEqual(account.code,1000);self.assertTrue(account.inactive)
    def test_list_filters_sort_pagination_chart_and_print(self):
        g=self.group();a=self.account(g,'Named cash')
        self.assertIn(b'Named cash',self.c.get('/workspace/finance/accounts?name=Named&account_class=Assets&sort=code').data)
        self.assertNotIn(b'Named cash',self.c.get('/workspace/finance/accounts?account_class=Income').data)
        self.assertEqual(self.c.get('/workspace/finance/accounts?sort=bad').status_code,422)
        self.assertEqual(self.c.get('/workspace/finance/accounts?size=100000').status_code,422)
        chart=self.c.get('/workspace/finance/chart-of-accounts?print=1');self.assertEqual(chart.status_code,200)
        self.assertIn(b'Named cash',chart.data);self.assertIn(b'data-finance-print',chart.data)
        self.assertNotIn(b'data-finance-print',self.c.get('/workspace/finance/chart-of-accounts').data)
    def test_stale_group_and_account_saves_and_audit_history(self):
        g=self.group();a=self.account(g);old=a.version
        self.assertEqual(self.post(f'accounts/{a.id}/edit',name='Cash Two',group_id=str(g.id),inactive='0',version=str(old)).status_code,302)
        self.assertEqual(self.post(f'accounts/{a.id}/edit',name='Cash Three',group_id=str(g.id),inactive='0',version=str(old)).status_code,422)
        self.assertEqual(a.name,'Cash Two')
        audit=app.extensions['ops_models']['audit'].query.filter_by(action='Save Finance accounts').order_by(app.extensions['ops_models']['audit'].id.desc()).first()
        self.assertEqual(audit.data['before']['name'],'Cash');self.assertEqual(audit.data['after']['name'],'Cash Two')
