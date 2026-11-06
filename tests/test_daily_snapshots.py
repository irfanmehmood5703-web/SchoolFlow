"""Actual observed history, immutable past dates and independent source totals."""
import unittest
from datetime import date
from flask import template_rendered
from tests import test_finance_ledger as fixture
from app import app,db,Student

class DailySnapshotTests(unittest.TestCase):
    setUp=fixture.FinanceLedgerTests.setUp
    tearDown=fixture.FinanceLedgerTests.tearDown
    account=fixture.FinanceLedgerTests.account
    def seed(self):
        s=Student(admission_no='FICTIONAL',name='Fictional pupil',class_name='One',status='Active');db.session.add(s);db.session.flush();db.session.add(app.extensions['record_models']['student'](student_id=s.id,data={'campus':'Campus A'}))
        O=app.extensions['ops_models'];db.session.add(O['bill'](student_id=s.id,month='2026-01',due=date(2026,1,1),lines=[{'amount':10000}],paid=4000,discount=1000));db.session.add(O['daily'](kind='student',person_id=s.id,day=app.extensions['ledger_helpers']['today'](),status='Late'));db.session.commit();return s
    def capture(self):return self.c.post('/workspace/finance/snapshots/capture',data={'_csrf':self.csrf})
    def load(self,**args):
        contexts=[]
        def receive(sender,template,context,**kw):contexts.append(context)
        template_rendered.connect(receive,app)
        try:
            r=self.c.get('/workspace/finance/snapshots',query_string=args);self.assertEqual(r.status_code,200,r.data);return contexts[-1],r
        finally:template_rendered.disconnect(receive,app)
    def test_empty_read_does_not_create_history_or_backfill(self):
        c,r=self.load(**{'from':'2026-01-01','to':'2026-02-01'});self.assertFalse(c['rows']);self.assertIsNone(c['first']);self.assertEqual(app.extensions['snapshot_models']['snapshot'].query.count(),0)
        self.assertNotIn(b'0.0%',r.data)
    def test_capture_totals_drills_and_unknown_new_ledger_income(self):
        self.seed();self.assertEqual(self.capture().status_code,302);c,r=self.load()
        self.assertEqual((c['totals']['strength'],c['totals']['expected'],c['totals']['collected'],c['totals']['discount'],c['totals']['outstanding']),(1,10000,4000,1000,5000));self.assertEqual(c['totals']['attendance'],100)
        self.assertIn(b'New Ledger source not connected',r.data)
        row=app.extensions['snapshot_models']['snapshot'].query.filter_by(campus='Campus A').one();self.assertIsNone(row.metrics['income'])
        for mode in ('students','classes'):
            response=self.c.get(f'/workspace/finance/snapshots/{row.id}/{mode}');self.assertEqual(response.status_code,200);self.assertIn(b'One',response.data)
    def test_today_refresh_does_not_count_baseline_twice_and_past_is_frozen(self):
        s=self.seed();self.capture();self.capture();S=app.extensions['snapshot_models']['snapshot'];row=S.query.filter_by(campus='Campus A').one();self.assertEqual((row.metrics['joined'],row.metrics['left']),(0,0));self.assertTrue(row.metrics['baseline'])
        original=row.day;row.day=date(2020,1,1);db.session.commit();s.status='Inactive';db.session.commit();self.capture()
        old=S.query.filter_by(day=date(2020,1,1),campus='Campus A').one();new=S.query.filter_by(day=original,campus='Campus A').one();self.assertEqual(old.metrics['strength'],1);self.assertEqual(new.metrics['strength'],0);self.assertEqual(new.metrics['left'],1)
    def test_transfers_are_not_admissions_or_leavers(self):
        s=self.seed();self.capture();d=app.extensions['record_models']['student'].query.filter_by(student_id=s.id).one();d.data={**d.data,'campus':'Campus B'};db.session.commit();self.capture();c,r=self.load();self.assertEqual((c['totals']['strength'],c['totals']['joined'],c['totals']['left']),(1,0,0))
    def test_newly_observed_enrolment_is_counted_once(self):
        self.seed();self.capture();s=Student(admission_no='SECOND',name='New fictional',class_name='Two',status='Active');db.session.add(s);db.session.flush();db.session.add(app.extensions['record_models']['student'](student_id=s.id,data={'campus':'Campus A'}));db.session.commit();self.capture();self.capture();c,_=self.load();self.assertEqual((c['totals']['strength'],c['totals']['joined']),(2,1))
    def test_campus_print_and_invalid_filters(self):
        self.seed();self.capture();c,r=self.load(campus='Campus B',print='1');self.assertEqual(c['totals']['strength'],0);self.assertIn(b'data-finance-print',r.data)
        for query in ['campus=Unknown','from=bad','from=2020-01-01&to=2026-01-01','from=2026-02-01&to=2026-01-01']:
            self.assertEqual(self.c.get('/workspace/finance/snapshots?'+query).status_code,422)
        self.assertEqual(self.c.post('/workspace/finance/snapshots/capture',data={'_csrf':'bad'}).status_code,400)

    def test_source_success_hook_refreshes_enabled_snapshot_and_failed_write_does_not(self):
        from flask import request
        from werkzeug.routing import Rule
        s=self.seed();self.capture();S=app.extensions['snapshot_models']['snapshot']
        s.status='Inactive';db.session.commit()
        hook=next(fn for fn in app.after_request_funcs[None] if fn.__name__=='update_after_source')
        with app.test_request_context('/fictional-source',method='POST'):
            request.url_rule=Rule('/fictional-source',endpoint='ops.fictional')
            hook(app.response_class('',status=422))
            self.assertEqual(S.query.filter_by(campus='Campus A').one().metrics['strength'],1)
            hook(app.response_class('',status=302))
            self.assertEqual(S.query.filter_by(campus='Campus A').one().metrics['strength'],0)
