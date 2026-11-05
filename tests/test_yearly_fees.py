"""Year catalog and cohort percentages are configuration, not financial writes."""
import os,unittest
os.environ['DATABASE_URL']='sqlite:///:memory:'
from app import app,db

class YearlyFeeTests(unittest.TestCase):
    path='/workspace/core/fees/yearly-increment'
    def setUp(self):
        app.config.update(TESTING=True,IDENTITY_ENFORCE_IN_TESTS=False)
        self.ctx=app.app_context();self.ctx.push();db.drop_all();db.create_all();self.m=app.extensions['school_settings_models'];self.rm=app.extensions['record_models']
        for cat,values in {'campus':['Campus A','Campus B'],'class_name':['One','Two']}.items():
            for value in values:db.session.add(self.rm['settings'](category=cat,value=value,class_name=''))
        db.session.commit();self.c=app.test_client();self.c.get(self.path)
        with self.c.session_transaction() as s:self.csrf=s['record_csrf']
    def tearDown(self):db.session.remove();db.drop_all();self.ctx.pop()
    def post(self,**values):return self.c.post(self.path,data={'_csrf':self.csrf,**values})
    def setup_policy(self):
        self.assertEqual(self.post(action='add-year',year='2027',version='0').status_code,302)
        self.assertEqual(self.post(action='add-plan',campus='Campus A',cohort_class='One').status_code,302)
        return self.m['item'].query.filter_by(kind='yearly-fee-cohort').one()
    def test_read_only_pages_and_exactly_six_built_configuration_entries(self):
        page=self.c.get(self.path);self.assertEqual(page.status_code,200)
        for key in ['roll-series','late-automation','yearly-increment']:self.assertIn(('data-core-key="'+key+'"').encode(),page.data)
        self.assertEqual(self.m['setting'].query.count(),0);self.assertEqual(self.m['item'].query.count(),0)
    def test_add_year_cohort_rate_and_review_link_save_no_money(self):
        row=self.setup_policy();self.assertEqual(self.post(action='save',id=str(row.id),version='1',year='2027',percentage='10').status_code,302)
        page=self.c.get(self.path+'?campus=Campus+A');self.assertEqual(page.status_code,200);self.assertIn(b'percentage=10',page.data)
        preview=self.c.get('/workspace/core/fees/increments?campus=Campus+A&class_name=One&year=2027&percentage=10');self.assertEqual(preview.status_code,200);self.assertIn(b'value="2027"',preview.data)
        self.assertEqual(app.extensions['student_fee_plan_model'].query.count(),0);self.assertEqual(app.extensions['ops_models']['bill'].query.count(),0)
    def test_zero_blank_stale_and_invalid_rates_preserve_other_years(self):
        row=self.setup_policy();self.assertEqual(self.post(action='save',id=str(row.id),version='1',year='2027',percentage='0').status_code,302);self.assertEqual(row.data['years'],{'2027':'0'})
        self.assertEqual(self.post(action='save',id=str(row.id),version='1',year='2027',percentage='30').status_code,422)
        for value in ['NaN','-1','1000000000']:
            self.assertEqual(self.post(action='save',id=str(row.id),version=str(row.version),year='2027',percentage=value).status_code,422)
        self.assertEqual(row.data['years'],{'2027':'0'})
        self.assertEqual(self.post(action='save',id=str(row.id),version=str(row.version),year='2027',percentage='').status_code,302);self.assertEqual(row.data['years'],{})
    def test_duplicate_year_cohort_and_invalid_ranges_rejected(self):
        self.setup_policy();self.assertEqual(self.post(action='add-year',year='2027',version='1').status_code,422);self.assertEqual(self.post(action='add-plan',campus='Campus A',cohort_class='One').status_code,422)
        for query in ['from_year=2028&to_year=2027','from_year=2000&to_year=2030','from_year=x','campus=Unknown']:
            self.assertEqual(self.c.get(self.path+'?'+query).status_code,422)
        self.assertEqual(self.post(action='add-year',year='1900',version='1').status_code,302);self.assertEqual(self.c.get(self.path).status_code,200)
        self.assertEqual(self.c.post(self.path,data={'action':'add-year','year':'2028'}).status_code,400)
    def test_campus_class_choices_follow_saved_class_map(self):
        Map=app.extensions['institute_setup_models']['mapping'];db.session.add(Map(campus='Campus A',class_name='One',active=True,data={}));db.session.commit()
        self.assertEqual(self.post(action='add-plan',campus='Campus A',cohort_class='Two').status_code,422)
        self.assertEqual(self.post(action='add-plan',campus='Campus B',cohort_class='Two').status_code,302)
