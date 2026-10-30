"""Student performance categorization and read-only cross-module aggregation."""
import os,unittest
from datetime import date
from flask import template_rendered
os.environ['DATABASE_URL']='sqlite:///:memory:'
from app import app,db,Student

class StudentOverviewTests(unittest.TestCase):
    def setUp(self):
        app.config.update(TESTING=True,SECRET_KEY='overview-tests')
        self.ctx=app.app_context();self.ctx.push();db.drop_all();db.create_all()
        self.m=app.extensions['ops_models'];self.rm=app.extensions['record_models']
        self.s=Student(admission_no='F-360',name='Fictional Performance Student',father='Fictional Guardian',class_name='One',status='Active')
        self.other=Student(admission_no='F-OTHER',name='Other Student',class_name='One',status='Active')
        db.session.add_all([self.s,self.other]);db.session.commit();self.c=app.test_client();self.c.get('/workspace/student-360')
        with self.c.session_transaction() as sess:self.csrf=sess['record_csrf']
    def tearDown(self):db.session.remove();db.drop_all();self.ctx.pop()
    def award(self,category,marks=40,total=50,day='2026-09-01',state='',student=None):
        w=self.m['workflow'](kind='awards',status='Active',data=dict(name=category or 'Old Unclassified',assessment_category=category,academic_session='2026-27',papers=[dict(subject='Math',date=day,total=total,type='Written')]))
        db.session.add(w);db.session.flush();db.session.add(self.m['score'](award_id=w.id,student_id=student or self.s.id,paper=0,obtained=marks,state=state));db.session.commit();return w
    def view(self,query='from=2026-09-01&to=2026-09-30'):
        captured=[]
        def receiver(sender,template,context,**extra):captured.append(context)
        template_rendered.connect(receiver,app)
        try:r=self.c.get(f'/workspace/student-360/{self.s.id}?'+query)
        finally:template_rendered.disconnect(receiver,app)
        return r,captured[-1] if captured else {}
    def test_four_performance_categories_weighted_marks_not_average_percentages(self):
        self.award('Weekly',40,50);self.award('Weekly',50,100,day='2026-09-08')
        for category in ['Monthly','First Term','Second Term']:self.award(category)
        r,ctx=self.view();self.assertEqual(r.status_code,200)
        self.assertEqual([x['category'] for x in ctx['performance']],['Weekly','Monthly','First Term','Second Term'])
        weekly=ctx['performance'][0];self.assertEqual(weekly['totals']['percentage'],60)
        self.assertEqual((weekly['totals']['obtained'],weekly['totals']['maximum']),(90,150))
        self.assertEqual(len(weekly['periods']),2);self.assertIn(b'Weekly',r.data);self.assertIn(b'First Term',r.data)
    def test_unclassified_absent_leave_blank_and_other_student_excluded(self):
        self.award('Weekly',None,state='A');self.award('Weekly',None,state='L');self.award('Weekly',None)
        self.award('');self.award('Monthly',50,50,student=self.other.id)
        r,ctx=self.view();self.assertEqual(r.status_code,200)
        totals=ctx['performance'][0]['totals'];self.assertIsNone(totals['percentage'])
        self.assertEqual((totals['absent'],totals['leave'],totals['unmarked']),(1,1,1));self.assertEqual(ctx['unclassified'],1)
        self.assertEqual(ctx['performance'][1]['totals']['recorded'],0)
        self.assertIn(b'/workspace/marks/',r.data)
    def test_financial_balances_and_receipt_dates_distinct_voided_excluded(self):
        b=self.m['bill'](student_id=self.s.id,month='2026-08',due=date(2026,8,10),lines=[dict(particular='Tuition',amount=100000)],paid=25000,discount=5000)
        db.session.add(b);db.session.flush()
        for voided,amount,token in [(False,25000,'valid'),(True,99900,'void')]:
            db.session.add(self.m['receipt'](student_id=self.s.id,bill_id=b.id,amount=amount,discount=5000,day=date(2026,9,5),account='Cash',token=token,voided=voided))
        db.session.commit();r,ctx=self.view();self.assertEqual(r.status_code,200)
        self.assertEqual((ctx['balance'],ctx['received'],ctx['billed']),(70000,25000,0))
        self.assertEqual(ctx['receipt_discount'],5000)
    def test_attendance_student_scope_and_linked_family(self):
        family=self.rm['family'](number='FAMILY-TEST',data={});db.session.add(family);db.session.flush()
        for student in [self.s,self.other]:db.session.add(self.rm['student'](student_id=student.id,family_id=family.id,data={}))
        for kind in ['student','staff']:db.session.add(self.m['daily'](kind=kind,person_id=self.s.id,day=date(2026,9,1),status='Present'))
        db.session.commit();r,ctx=self.view();self.assertEqual(r.status_code,200)
        self.assertEqual(ctx['counts']['Present'],1);self.assertEqual([x.id for x in ctx['siblings']],[self.other.id])
    def test_period_filters_and_invalid_ranges(self):
        self.award('Weekly',day='2026-08-30');self.award('Monthly',day='2026-09-02')
        _,ctx=self.view();self.assertEqual(len(ctx['papers']),1)
        for query in ['from=bad','from=2026-10-01&to=2026-09-01','from=2000-01-01&to=2026-10-01']:
            self.assertEqual(self.view(query)[0].status_code,422)
        self.assertEqual(self.c.get('/workspace/student-360/9999').status_code,404)
    def test_existing_award_category_save_preserves_marks_and_checks_csrf(self):
        w=self.award('');path=f'/workspace/assessment-category/{w.id}'
        self.assertEqual(self.c.post(path,data=dict(assessment_category='Weekly')).status_code,400)
        self.assertEqual(self.c.post(path,data=dict(_csrf=self.csrf,assessment_category='Bad')).status_code,422)
        self.assertEqual(self.c.post(path,data=dict(_csrf=self.csrf,assessment_category='First Term')).status_code,302)
        self.assertEqual(w.data['assessment_category'],'First Term');self.assertEqual(self.m['score'].query.one().obtained,40)
        self.assertEqual(self.c.get(f'/workspace/marks/{w.id}').status_code,200)
    def test_create_award_accepts_only_known_performance_categories(self):
        data=dict(_csrf=self.csrf,name='Monthly fixture',assessment_category='Monthly',subject='Math',exam_date='2026-09-01',test_type='Written',total='100')
        self.assertEqual(self.c.post('/workspace/examination/awards',data=data).status_code,302)
        self.assertEqual(self.m['workflow'].query.one().data['assessment_category'],'Monthly')
        data.update(name='Invalid fixture',assessment_category='Unknown');self.assertEqual(self.c.post('/workspace/examination/awards',data=data).status_code,422)
        self.assertEqual(self.m['workflow'].query.count(),1)
    def test_directory_search_pagination_and_status(self):
        self.assertIn(b'Fictional Performance Student',self.c.get('/workspace/student-360?q=F-360').data)
        self.assertNotIn(b'Fictional Performance Student',self.c.get('/workspace/student-360?q=%25').data)
        self.s.status='Inactive';db.session.commit()
        self.assertNotIn(b'Fictional Performance Student',self.c.get('/workspace/student-360?status=Active').data)
        for value in ['-1','abc']:self.assertEqual(self.c.get('/workspace/student-360?page='+value).status_code,422)
