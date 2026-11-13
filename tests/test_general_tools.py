"""Release registry, all 37 data sources, personal layouts and truthful missing data."""
import os,unittest
from datetime import date,timedelta
from werkzeug.datastructures import MultiDict
os.environ['DATABASE_URL']='sqlite:///:memory:'
from app import app,db,Student,Employee
from widget_catalog import WIDGETS,KEYS

class GeneralToolsTests(unittest.TestCase):
    def setUp(self):
        app.config.update(TESTING=True,IDENTITY_ENFORCE_IN_TESTS=False,SECRET_KEY='fictional-widgets')
        self.ctx=app.app_context();self.ctx.push();db.drop_all();db.create_all()
        self.c=app.test_client();self.c.get('/workspace/general/widgets')
        with self.c.session_transaction() as s:self.csrf=s['record_csrf'];s['owner_id']=41
        self.rm=app.extensions['record_models'];self.ops=app.extensions['ops_models'];self.M=app.extensions['general_tools_models']
        self.today=date.today()
        for cat,values in {'campus':['North','South'],'class_name':['One'],'section':['A']}.items():
            for v in values:db.session.add(self.rm['settings'](category=cat,value=v,class_name=''))
        s=Student(admission_no='QA-1',name='Fictional Widget Pupil',class_name='One',status='Active');db.session.add(s);db.session.flush();self.sid=s.id
        db.session.add(self.rm['student'](student_id=s.id,data={'campus':'North','section':'A','admission_date':str(self.today),'birth_date':f'2010-{self.today.month:02d}-{self.today.day:02d}'}))
        db.session.commit()
    def tearDown(self):
        db.session.remove();db.drop_all();self.ctx.pop()
    def post(self,path,data):
        return self.c.post(path,data=MultiDict([('_csrf',self.csrf)]+[(k,v) for k,values in data.items() for v in (values if isinstance(values,list) else [values])]))
    def test_all_37_cards_and_sources_render(self):
        self.assertEqual(len(KEYS),37)
        page=self.c.get('/workspace/general/widgets');self.assertEqual(page.status_code,200)
        self.assertEqual(page.data.count(b'data-general-widget='),37)
        for key,_,label,_ in WIDGETS:
            import html
            self.assertIn(html.escape(label).encode(),page.data)
            self.assertEqual(self.c.get('/workspace/general/widgets/report/'+key).status_code,200,key)
        for path in ('/workspace/general/app-links','/workspace/general/widgets/library','/workspace/general/widgets/permissions'):
            self.assertEqual(self.c.get(path).status_code,200)
        self.assertEqual(self.M['preference'].query.count(),0)
    def test_registry_version_url_checks_and_real_link_only(self):
        page=self.c.get('/workspace/general/app-links')
        self.assertEqual(page.data.count(b'No native release published'),4)
        self.assertEqual(page.data.count(b'Verify test APK'),4)
        self.assertIn(b'/releases/download/clients-test-3/SchoolFlow-parents-test.apk',page.data)
        payload=dict(app='teacher',version_token='0',url='https://example.invalid/schoolflow.apk',version='1.0',size='10 MB',notes='Fictional test release')
        self.assertEqual(self.post('/workspace/general/app-links',payload).status_code,302)
        page=self.c.get('/workspace/general/app-links');self.assertIn(b'data-copy-release="https://example.invalid/schoolflow.apk"',page.data)
        self.assertEqual(self.post('/workspace/general/app-links',payload).status_code,422)
        for url in ('javascript:alert(1)','http://example.invalid/app.apk','https://name:password@example.invalid/a.apk','https://example.invalid/#secret'):
            self.assertEqual(self.post('/workspace/general/app-links',{**payload,'version_token':'1','url':url}).status_code,422)
        self.assertEqual(self.rm['file'].query.count(),0)
    def test_layout_order_default_and_account_isolation(self):
        order=list(reversed(KEYS));chosen=['birthdays','active-students']
        self.assertEqual(self.post('/workspace/general/widgets/layout',dict(version='0',action='save',order=order,selected=chosen,columns='1')).status_code,302)
        page=self.c.get('/workspace/general/widgets');self.assertEqual(page.data.count(b'data-general-widget='),2)
        self.assertLess(page.data.index(b'id="birthdays"'),page.data.index(b'id="active-students"'))
        self.assertEqual(self.post('/workspace/general/widgets/layout',dict(version='1',action='default')).status_code,302)
        self.assertEqual(self.c.get('/workspace/dashboard').location,'/workspace/general/widgets')
        fresh=app.test_client()
        with fresh.session_transaction() as s:s['owner_id']=41
        self.assertEqual(fresh.get('/workspace/general/widgets').data.count(b'data-general-widget='),2)
        with fresh.session_transaction() as s:s['owner_id']=42
        self.assertEqual(fresh.get('/workspace/general/widgets').data.count(b'data-general-widget='),37)
    def test_invalid_or_stale_layout_does_not_overwrite(self):
        for payload in [dict(version='0',action='save',order=KEYS,selected=['unknown'],columns='2'),dict(version='0',action='save',order=KEYS[:-1],selected=[],columns='2')]:
            self.assertEqual(self.post('/workspace/general/widgets/layout',payload).status_code,422)
        self.assertEqual(self.post('/workspace/general/widgets/layout',dict(version='0',action='default')).status_code,302)
        self.assertEqual(self.post('/workspace/general/widgets/layout',dict(version='0',action='simple')).status_code,422)
        self.assertEqual(self.c.post('/workspace/general/widgets/layout',data={'action':'default'}).status_code,400)
    def test_actual_counts_dates_and_missing_sms(self):
        page=self.c.get('/workspace/general/widgets/report/birthdays');self.assertIn(b'Fictional Widget Pupil',page.data)
        page=self.c.get('/workspace/general/widgets/report/sms');self.assertIn(b'SIM/provider balance and recipient delivery are unavailable',page.data)
        self.assertEqual(self.c.get('/workspace/general/widgets?period=custom&from=bad&to=2026-11-07').status_code,422)
        b=self.ops['bill'](student_id=self.sid,month=self.today.strftime('%Y-%m'),due=self.today+timedelta(days=1),lines=[{'particular':'Tuition','amount':10000}],paid=4000,discount=1000)
        db.session.add(b);db.session.flush();db.session.add(self.ops['receipt'](student_id=self.sid,bill_id=b.id,amount=4000,discount=1000,day=self.today,account='Cash',token='widget-qa'));db.session.commit()
        page=self.c.get('/workspace/general/widgets/report/paid-amount');self.assertIn(b'40.00',page.data)
        page=self.c.get('/workspace/general/widgets/report/fee-defaulters');self.assertNotIn(b'Fictional Widget Pupil',page.data)
        page=self.c.get('/workspace/general/widgets/report/unpaid-amount');self.assertIn(b'50.00',page.data)
        self.assertEqual(self.c.get('/workspace/general/widgets/report/paid-amount?export=xlsx').status_code,200)
    def test_mixed_particular_payments_are_not_invented(self):
        db.session.add(self.ops['bill'](student_id=self.sid,month=self.today.strftime('%Y-%m'),due=self.today,lines=[{'particular':'Tuition','amount':10000},{'particular':'Books','amount':2000}],paid=5000))
        db.session.commit()
        page=self.c.get('/workspace/general/widgets/report/particular-fees');self.assertIn(b'Unavailable for mixed-head bills',page.data)
    def test_permissions_optimistic_version_and_tuition_setting(self):
        self.assertEqual(self.post('/workspace/general/widgets/permissions',dict(version='0',tuition_head='missing')).status_code,422)
        data={key+'_all':'1' for key in KEYS}
        self.assertEqual(self.post('/workspace/general/widgets/permissions',{**data,'version':'0'}).status_code,302)
        self.assertEqual(self.post('/workspace/general/widgets/permissions',{**data,'version':'0'}).status_code,422)
    def test_result_exclusions_attendance_and_discounted_tuition(self):
        db.session.add(self.ops['daily'](kind='student',person_id=self.sid,day=self.today,status='Absent'))
        award=self.ops['workflow'](kind='awards',status='Active',data={'name':'Fictional Widget Exam','papers':[{'subject':'Math','total':100,'grading':'Marks','date':str(self.today)},{'subject':'English','total':100,'grading':'Marks','date':str(self.today)}]})
        db.session.add(award);db.session.flush()
        db.session.add_all([self.ops['score'](award_id=award.id,student_id=self.sid,paper=0,obtained=80,state='P'),self.ops['score'](award_id=award.id,student_id=self.sid,paper=1,obtained=0,state='A')])
        H=app.extensions['fee_setup_models']['head']
        db.session.add(H(key='tuition',label='Tuition Fee',timing='monthly'))
        db.session.add(app.extensions['student_fee_plan_model'](student_id=self.sid,effective=self.today.strftime('%Y-%m'),data={'lines':[{'particular':'tuition','actual':350000,'discount':150000}]}))
        db.session.commit()
        page=self.c.get('/workspace/general/widgets/report/class-results');self.assertIn(b'80.0',page.data)
        page=self.c.get('/workspace/general/widgets/report/absent-class');self.assertIn(b'Fictional Widget Pupil',page.data)
        page=self.c.get('/workspace/general/widgets');self.assertIn(b'2,000.00',page.data);self.assertIn(b'<svg',page.data)
    def test_posted_ledger_snapshot_net_not_cash_receipt_guess(self):
        m=app.extensions['finance_models'];j=app.extensions['ledger_models']
        from datetime import datetime,timezone
        stamp=dict(created_at=datetime.now(timezone.utc),updated_at=datetime.now(timezone.utc),created_by='QA',updated_by='QA')
        period=m['period'](**stamp,begin=self.today.replace(month=1,day=1),end=self.today.replace(month=12,day=31),closed=False)
        group=m['group'](**stamp,name='Fictional Income',account_class='Income',active=True)
        db.session.add_all([period,group]);db.session.flush()
        account=m['account'](**stamp,name='Fictional Income Account',code=1,group_id=group.id,inactive=False)
        db.session.add(account)
        asset_group=m['group'](**stamp,name='Fictional Assets',account_class='Assets',active=True)
        db.session.add(asset_group);db.session.flush()
        asset=m['account'](**stamp,name='Fictional Cash',code=2,group_id=asset_group.id,inactive=False)
        db.session.add(asset);db.session.flush()
        journal=j['journal'](day=self.today,campus='North',kind='journal',period_id=period.id,actor='QA',actor_key='owner:41',token='q'*43,fingerprint='f'*64)
        db.session.add(journal);db.session.flush()
        db.session.add(j['line'](journal_id=journal.id,account_id=account.id,debit=0,credit=10000,memo='',snapshot={'account_class':'Income'}))
        db.session.add(j['line'](journal_id=journal.id,account_id=asset.id,debit=10000,credit=0,memo='',snapshot={'account_class':'Assets'}))
        db.session.commit()
        page=self.c.get('/workspace/general/widgets/report/daily-profit');self.assertIn(b'100.00',page.data)
        group.account_class='Equity';db.session.commit()
        page=self.c.get('/workspace/general/widgets/report/daily-profit');self.assertIn(b'100.00',page.data)
        expense_group=m['group'](**stamp,name='Fictional Expense',account_class='Expense',active=True)
        db.session.add(expense_group);db.session.flush()
        expense_account=m['account'](**stamp,name='Fictional Expense Account',code=3,group_id=expense_group.id,inactive=False)
        db.session.add(expense_account);db.session.flush()
        expense_journal=j['journal'](day=self.today,campus='North',kind='journal',period_id=period.id,actor='QA',actor_key='owner:41',token='e'*43,fingerprint='e'*64)
        db.session.add(expense_journal);db.session.flush()
        db.session.add_all([j['line'](journal_id=expense_journal.id,account_id=expense_account.id,debit=2500,credit=0,memo='',snapshot={'account_class':'Expense'}),j['line'](journal_id=expense_journal.id,account_id=asset.id,debit=0,credit=2500,memo='',snapshot={'account_class':'Assets'})])
        db.session.commit()
        from flask import template_rendered
        captured=[]
        def record(sender,template,context,**extra):captured.append(context['summary']['value'])
        template_rendered.connect(record,app)
        try:
            for key in ('income-expenses','daily-profit'):
                self.assertEqual(self.c.get('/workspace/general/widgets/report/'+key).status_code,200)
        finally:template_rendered.disconnect(record,app)
        self.assertEqual(captured,[10000,7500])

    def test_demo_preferences_are_session_only_and_global_settings_cannot_change(self):
        with self.c.session_transaction() as s:s['demo']=True
        self.assertNotIn(b'Manage this release',self.c.get('/workspace/general/app-links').data)
        self.assertEqual(self.post('/workspace/general/app-links',dict(app='teacher',version_token='0',url='',version='')).status_code,403)
        self.assertEqual(self.c.get('/workspace/general/widgets/permissions').status_code,403)
        self.assertEqual(self.post('/workspace/general/widgets/layout',dict(version='0',action='default')).status_code,302)
        self.assertEqual(self.M['preference'].query.count(),0)

    def test_school_can_hide_bundled_test_release_without_rewriting_catalogue(self):
        import json
        from pathlib import Path
        before=Path('native_releases.json').read_text()
        self.assertEqual(self.post('/workspace/general/app-links',dict(app='parents',version_token='0',url='',version='',size='',notes='Hidden for this school')).status_code,302)
        page=self.c.get('/workspace/general/app-links')
        self.assertNotIn(json.loads(before)['parents']['url'].encode(),page.data)
        self.assertEqual(Path('native_releases.json').read_text(),before)

    def test_unknown_widget_404(self):
        self.assertEqual(self.c.get('/workspace/general/widgets/report/unknown').status_code,404)

if __name__=='__main__':unittest.main()
