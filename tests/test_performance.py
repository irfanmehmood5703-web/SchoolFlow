"""Bound SQL counts, preserved filtering and public-only static caching."""
import os,re,unittest
os.environ['DATABASE_URL']='sqlite:///:memory:'
from sqlalchemy import event
from app import app,db,Student,Employee


class PerformanceTests(unittest.TestCase):
    def setUp(self):
        app.config.update(TESTING=True,IDENTITY_ENFORCE_IN_TESTS=False)
        self.ctx=app.app_context();self.ctx.push();db.drop_all();db.create_all()
        self.rm=app.extensions['record_models'];self.c=app.test_client()
    def tearDown(self):
        db.session.remove();db.drop_all();self.ctx.pop()
    def seed(self,count=120):
        db.session.add(self.rm['settings'](category='campus',value='Campus A',class_name=''))
        family=self.rm['family'](number='F-SHARED',data={'father':'Authoritative Family','phone':'000'})
        db.session.add(family);db.session.flush()
        Plan=app.extensions['student_fee_plan_model']
        for i in range(count):
            s=Student(admission_no=f'P{i:03}',name=f'Pupil {i:03}',father='Old Father',class_name='Class A',status='Active');db.session.add(s);db.session.flush()
            db.session.add(self.rm['student'](student_id=s.id,family_id=family.id,data={'campus':'Campus A','section':'A','gender':'Female'}))
            db.session.add(Plan(student_id=s.id,effective='2026-01',data={'schedule':'Earlier','lines':[]}))
            db.session.add(Plan(student_id=s.id,effective='2026-02',data={'schedule':'Latest','lines':[]}))
        db.session.commit();db.session.remove()
    def measured(self,path,limit):
        count=[0]
        def tally(*args):count[0]+=1
        db.session.remove();event.listen(db.engine,'before_cursor_execute',tally)
        try:r=self.c.get(path)
        finally:event.remove(db.engine,'before_cursor_execute',tally)
        self.assertEqual(r.status_code,200,path);self.assertLessEqual(count[0],limit,(path,count[0]));return r
    def test_bounded_queries_pagination_latest_plan_and_complete_csv(self):
        self.seed()
        r=self.measured('/records/student?campus=Campus+A&gender=Female',12)
        self.assertIn(b'120 matching records',r.data);self.assertEqual(r.data.count(b'Authoritative Family'),25)
        self.assertIn(b'Pupil 119',r.data);self.assertNotIn(b'Pupil 000',r.data)
        csv=self.c.get('/records/student/export.csv?campus=Campus+A&gender=Female')
        self.assertEqual(csv.data.count(b'Authoritative Family'),120)
        plans=self.measured('/workspace/student-fee-plans?mode=update',12)
        self.assertEqual(plans.data.count(b'Latest'),25);self.assertNotIn(b'Earlier',plans.data)
        self.assertNotIn(b'Pupil 025',plans.data)
        self.assertIn(b'Pupil 025',self.c.get('/workspace/student-fee-plans?mode=update&page=2').data)
        self.measured('/workspace/certificates?campus=Campus+A',14)
        ops=app.extensions['ops_models'];w=ops['workflow'](kind='awards',status='Active',data={'papers':[{'total':20}]});db.session.add(w);db.session.flush()
        for s in Student.query.all():db.session.add(ops['score'](award_id=w.id,student_id=s.id,paper=0,obtained=10))
        db.session.commit();self.measured('/workspace/dashboard',18)
    def test_versioned_assets_revalidate_and_private_pages_never_cache(self):
        page=self.c.get('/records/student/new')
        path=re.search(rb'href="(/static/style.css\?v=[a-f0-9]+)"',page.data).group(1).decode()
        r=self.c.get(path);self.assertIn('immutable',r.headers['Cache-Control'])
        etag=r.headers['ETag'];r.close()
        with self.c.get(path,headers={'If-None-Match':etag}) as cached:
            self.assertEqual(cached.status_code,304)
        with self.c.get('/static/style.css?v=wrong') as wrong:
            self.assertNotIn('immutable',wrong.headers['Cache-Control'])
        self.assertEqual(page.headers['Cache-Control'],'no-store');self.assertIn('app;dur=',page.headers['Server-Timing'])
    def test_main_menu_targets_skip_alias_redirects(self):
        page=self.c.get('/records/student')
        nav=page.data.split(b'<nav class="top-navigation"',1)[1].split(b'</nav>',1)[0]
        for href in re.findall(rb'href="([^"]+)"',nav):
            path=href.decode().replace('&amp;','&')
            self.assertEqual(self.c.get(path).status_code,200,path)

    def test_dashboard_keeps_receipt_dates_bill_months_voids_and_variable_paper_totals(self):
        from datetime import date
        ops=app.extensions['ops_models'];today=date.today();this=today.strftime('%Y-%m');old=f'{today.year-1}-12'
        s=Student(admission_no='FINANCE',name='Fictional Pupil',class_name='Class A',status='Active');db.session.add(s);db.session.flush()
        b=ops['bill'](student_id=s.id,month=old,due=today,lines=[{'amount':10000}],paid=2500,discount=500);db.session.add(b);db.session.flush()
        for token,amount,discount,when,voided in [('current',2000,500,today,False),('old',500,0,date(today.year-1,12,1),False),('void',9000,0,today,True)]:
            db.session.add(ops['receipt'](student_id=s.id,bill_id=b.id,amount=amount,discount=discount,day=when,account='Cash',token=token,voided=voided))
        award=ops['workflow'](kind='awards',status='Active',data={'papers':[{'total':20},{'total':50},{'total':30}]});db.session.add(award);db.session.flush()
        for index,marks in enumerate([10,50,None]):db.session.add(ops['score'](award_id=award.id,student_id=s.id,paper=index,obtained=marks))
        db.session.commit();stats=app.extensions['operation_helpers']['dashboard']()
        self.assertEqual((stats['collected'],stats['this_month'],stats['due'],stats['discount'],stats['average']),(2500,2000,7000,500,75.0))
        self.assertEqual(stats['defaulters'],1)
        self.assertTrue(all(collected==0 for _,_,collected in stats['months']))
        b.paid=9500;db.session.commit()
        self.assertEqual(app.extensions['operation_helpers']['dashboard']()['due'],0)
