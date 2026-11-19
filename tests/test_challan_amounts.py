"""Generated-challan adjustments: real private login and financial invariants."""
import copy,unittest,time
from datetime import date
from unittest.mock import patch
import test_messaging as fixture
from app import app,db,Student
from flask import g
from itsdangerous import URLSafeTimedSerializer
from challan_amounts import adjusted_lines

class ChallanAmountTests(unittest.TestCase):
    password=fixture.MessagingTests.password
    setUp=fixture.MessagingTests.setUp;tearDown=fixture.MessagingTests.tearDown
    def tenant(self,fn,school=None):
        g.pop("staff_principal",None)
        return fixture.MessagingTests.tenant(self,fn,school)
    csrf=fixture.MessagingTests.csrf;login=fixture.MessagingTests.login;post=fixture.MessagingTests.post
    path='/workspace/fees/add-amount'
    def bill(self,**changes):
        def seed():
            values=dict(student_id=1,month='2027-03',due=date(2027,3,10),lines=[dict(particular='Tuition Fee',amount=350000,actual=400000,plan_discount=50000)],paid=0,discount=0)
            values.update(changes);b=self.ops['bill'](**values);db.session.add(b);db.session.flush();return b.id
        return self.tenant(seed)
    def data(self,bid,**changes):
        value=dict(ids=[str(bid)] if isinstance(bid,int) else list(map(str,bid)),head='Books Payment',direction='increase',change_by='absolute',amount='200',note='Fictional notebook charge')
        value.update(changes);return value
    def preview(self,data,c=None):
        r=self.post(self.path+'/preview',data,c);self.assertEqual(r.status_code,200,r.data[:1000]);return r.json['review_token']
    def apply(self,data,token,c=None):return self.post(self.path+'/apply',{**data,'review_token':token},c)
    def saved(self,bid):
        return self.tenant(lambda:dict(lines=copy.deepcopy(db.session.get(self.ops['bill'],bid).lines),paid=db.session.get(self.ops['bill'],bid).paid,discount=db.session.get(self.ops['bill'],bid).discount,total=db.session.get(self.ops['bill'],bid).total,remaining=db.session.get(self.ops['bill'],bid).remaining))
    def test_preview_is_read_only_apply_and_retry_are_exactly_once(self):
        bid=self.bill();d=self.data(bid);before=self.saved(bid);token=self.preview(d)
        self.assertEqual(self.saved(bid),before)
        self.assertEqual(self.tenant(lambda:app.extensions['challan_amount_models']['change'].query.count()),0)
        self.assertEqual(self.apply(d,token).status_code,200)
        self.assertEqual(self.apply(d,token).json['already_saved'],True)
        self.assertEqual(self.saved(bid)['total'],370000)
        self.assertEqual(self.tenant(lambda:app.extensions['challan_amount_models']['line'].query.count()),1)
        page=self.c.get(self.path+'/'+str(bid)+'/history');self.assertEqual(page.status_code,200);self.assertIn(b'Fictional notebook charge',page.data)
        self.assertEqual(self.tenant(lambda:self.ops['audit'].query.filter_by(action='Change generated challan amount').count()),1)
    def test_paid_partial_and_discount_balances_and_receipts_retained(self):
        for paid,discount in [(100000,20000),(350000,0)]:
            bid=self.bill(paid=paid,discount=discount)
            def receipt():db.session.add(self.ops['receipt'](student_id=1,bill_id=bid,amount=paid,discount=discount,day=date(2027,3,2),account='Cash',token='fictional-'+str(bid)))
            self.tenant(receipt);d=self.data(bid);self.assertEqual(self.apply(d,self.preview(d)).status_code,200)
            saved=self.saved(bid);self.assertEqual((saved['paid'],saved['discount'],saved['remaining']),(paid,discount,370000-paid-discount))
            self.assertEqual(self.tenant(lambda:self.ops['receipt'].query.filter_by(bill_id=bid).one().amount),paid)
    def test_decrease_cannot_consume_received_amount_or_discount(self):
        bid=self.bill(paid=300000,discount=20000);d=self.data(bid,head='Tuition Fee',direction='decrease',amount='400')
        r=self.post(self.path+'/preview',d);self.assertEqual(r.status_code,422);self.assertEqual(self.saved(bid)['total'],350000)
    def test_percent_rounding_and_original_concession_basis_preserved(self):
        bid=self.bill();d=self.data(bid,head='Tuition Fee',change_by='percentage',amount='10')
        self.assertEqual(self.apply(d,self.preview(d)).status_code,200)
        line=self.saved(bid)['lines'][0];self.assertEqual((line['amount'],line['actual'],line['plan_discount']),(385000,435000,50000));self.assertEqual(line['before_manual_changes'],dict(amount=350000,actual=400000,plan_discount=50000))
        d=self.data(bid,head='Tuition Fee',direction='decrease',change_by='percentage',amount='10');self.assertEqual(self.apply(d,self.preview(d)).status_code,200);self.assertEqual(self.saved(bid)['total'],346500)
        line=dict(particular='Books Payment',amount=5);original=copy.deepcopy(line)
        changed,old,new,delta=adjusted_lines([line],dict(key='Books Payment',label='Books'),'increase','percentage',1000,'qa');self.assertEqual(delta,1);self.assertEqual(line,original)
    def test_batch_is_atomic_when_one_bill_changes_after_review(self):
        a=self.bill();b=self.bill(student_id=2);d=self.data([a,b]);token=self.preview(d)
        self.tenant(lambda:setattr(db.session.get(self.ops['bill'],b),'paid',10000))
        self.assertEqual(self.apply(d,token).status_code,409);self.assertEqual(self.saved(a)['total'],350000);self.assertEqual(self.saved(b)['total'],350000)
    def test_tampering_frozen_invalid_percent_missing_head_and_csrf(self):
        bid=self.bill();d=self.data(bid);token=self.preview(d)
        self.assertEqual(self.apply({**d,'amount':'201'},token).status_code,409)
        self.assertEqual(self.apply(d,token+'bad').status_code,400)
        self.assertEqual(self.c.post(self.path+'/preview',data=d).status_code,400)
        for change in [dict(amount='-1'),dict(amount='NaN'),dict(amount='0'),dict(amount='1.001'),dict(change_by='percentage'),dict(head='not configured'),dict(ids=['1','1']),dict(head='Tuition Fee',direction='decrease',change_by='percentage',amount='101')]:
            self.assertEqual(self.post(self.path+'/preview',{**d,**change}).status_code,422)
        self.tenant(lambda:setattr(db.session.get(self.ops['bill'],bid),'frozen',True));self.assertEqual(self.post(self.path+'/preview',d).status_code,422)
    def test_protected_fines_and_opening_arrears_not_edited(self):
        for key in ['kind','fine_charge_id','arrears_key']:
            line=dict(particular='Books Payment',amount=10000);line[key]='late_fee' if key=='kind' else '1'
            bid=self.bill(lines=[line]);self.assertEqual(self.post(self.path+'/preview',self.data(bid)).status_code,422)
    def test_expiry_requires_new_review_but_committed_retry_can_be_confirmed(self):
        bid=self.bill();d=self.data(bid);token=self.preview(d)
        signer=URLSafeTimedSerializer(app.secret_key,salt='schoolflow-challan-amount-review-v1')
        payload=signer.loads(token)
        with patch('itsdangerous.timed.TimestampSigner.get_timestamp',return_value=int(time.time())-700):old=signer.dumps(payload)
        self.assertEqual(self.apply(d,old).status_code,409)
        self.assertEqual(self.apply(d,token).status_code,200)
        with patch('challan_amounts.datetime') as clock:
            from datetime import datetime,timezone,timedelta
            clock.now.return_value=datetime.now(timezone.utc)+timedelta(hours=1)
            self.assertTrue(self.apply(d,token).json['already_saved'])
    def test_staff_needs_explicit_permission_and_current_campus(self):
        bid=self.bill();teacher=self.login('teacher1');d=self.data(bid)
        self.assertEqual(self.post(self.path+'/preview',d,teacher).status_code,403)
        def grant():
            row=db.session.get(self.Staff,1);row.data={**row.data,'permissions':{'fees.view':['North'],'fees.adjust':['North']}}
        self.tenant(grant);teacher=self.login('teacher1');token=self.preview(d,teacher)
        self.assertEqual(self.apply(d,token,teacher).status_code,200)
        self.assertEqual(teacher.get(self.path+'?from=2027-03&to=2027-03&export=csv').status_code,403)
        def move():
            row=self.rm['student'].query.filter_by(student_id=1).one();row.data={**row.data,'campus':'South'}
        self.tenant(move);self.assertIn(self.apply(d,token,teacher).status_code,(403,404));self.assertEqual(self.saved(bid)['total'],370000)
    def test_tenant_bound_review_cannot_apply_in_other_school(self):
        bid=self.bill();d=self.data(bid);token=self.preview(d)
        second=self.H['provision']('MSG-TWO','Other fictional school','owner@example.invalid',self.password).id
        self.tenant(lambda:db.session.add(Student(id=1,admission_no='O1',name='Other fictional child',class_name='One',status='Active')),second)
        self.tenant(lambda:db.session.add(self.ops['bill'](id=bid,student_id=1,month='2027-03',due=date(2027,3,10),lines=[dict(particular='Tuition Fee',amount=350000)])),second)
        other=self.login(code='MSG-TWO');self.assertEqual(self.apply(d,token,other).status_code,403);self.assertEqual(self.saved(bid)['total'],350000)
    def test_filters_export_and_escaped_history(self):
        bid=self.bill();d=self.data(bid,note='<script>alert(1)</script>');self.assertEqual(self.apply(d,self.preview(d)).status_code,200)
        self.assertIn(b'&lt;script&gt;',self.c.get(self.path+'/'+str(bid)+'/history').data)
        page=self.c.get(self.path+'?from=2027-03&to=2027-03&q=F1');self.assertEqual(page.status_code,200);self.assertIn(b'Fictional child 1',page.data)
        self.tenant(lambda:setattr(db.session.get(Student,1),'name','=formula'))
        exported=self.c.get(self.path+'?from=2027-03&to=2027-03&export=csv');self.assertEqual(exported.status_code,200);self.assertIn(b"'=formula",exported.data)
        self.assertEqual(self.c.get(self.path+'?from=2026-01&to=2027-03').status_code,422)

    def test_fee_audit_print_and_student_plan_are_unchanged(self):
        bid=self.bill()
        def plan():
            row=self.ops['workflow'](kind='fee-plans',status='Active',data={'student_id':'1','amount':'3500','particular':'Tuition Fee'});db.session.add(row);db.session.flush();return row.id
        plan_id=self.tenant(plan);d=self.data(bid);self.assertEqual(self.apply(d,self.preview(d)).status_code,200)
        self.assertEqual(self.tenant(lambda:db.session.get(self.ops['workflow'],plan_id).data['amount']),'3500')
        self.assertEqual(self.tenant(lambda:app.extensions['fee_ledger_models']['posting'].query.count()),0)
        event=self.tenant(lambda:copy.deepcopy(app.extensions['finance_audit_models']['event'].query.filter_by(bill_id=bid,kind='Amount increased').one().data))
        self.assertEqual(event['delta'],20000);self.assertEqual(event['before_amount'],350000)
        printed=self.post('/workspace/fee-action',dict(ids=[str(bid)],action='branded'));self.assertEqual(printed.status_code,200);self.assertIn(b'3,700.00',printed.data);self.assertIn(b'Books Payment',printed.data)
    def test_deleted_bill_lifetime_history_is_not_reused(self):
        bid=self.bill();d=self.data(bid);self.assertEqual(self.apply(d,self.preview(d)).status_code,200)
        self.tenant(lambda:db.session.delete(db.session.get(self.ops['bill'],bid)))
        self.bill(id=bid);page=self.c.get(self.path+'/'+str(bid)+'/history');self.assertNotIn(b'Fictional notebook charge',page.data)
        self.assertEqual(self.tenant(lambda:app.extensions['challan_amount_models']['line'].query.count()),1)
    def test_unused_review_does_not_follow_a_reused_bill_id(self):
        bid=self.bill();d=self.data(bid);token=self.preview(d)
        self.tenant(lambda:db.session.delete(db.session.get(self.ops['bill'],bid)))
        self.bill(id=bid);self.assertEqual(self.apply(d,token).status_code,409);self.assertEqual(self.saved(bid)['total'],350000)
    def test_batch_rejects_a_frozen_or_foreign_campus_row(self):
        a=self.bill();b=self.bill(student_id=2,frozen=True);d=self.data([a,b]);self.assertEqual(self.post(self.path+'/preview',d).status_code,422);self.assertEqual(self.saved(a)['total'],350000)
    def test_fee_head_changed_after_review_requires_new_preview(self):
        bid=self.bill();d=self.data(bid);token=self.preview(d)
        Head=app.extensions['fee_setup_models']['head']
        self.tenant(lambda:db.session.add(Head(key='Books Payment',label='Notebook charge',timing='manual',months=[])))
        self.assertEqual(self.apply(d,token).status_code,409);self.assertEqual(self.saved(bid)['total'],350000)
    def test_simultaneous_same_review_never_compounds(self):
        import threading
        from concurrent.futures import ThreadPoolExecutor
        bid=self.bill();d=self.data(bid);token=self.preview(d);cookie=self.c.get_cookie('session').value;csrf=self.csrf();barrier=threading.Barrier(2)
        def send(_):
            c=app.test_client();c.set_cookie('session',cookie);barrier.wait(timeout=10)
            return c.post(self.path+'/apply',data={**d,'review_token':token,'_csrf':csrf}).status_code
        # A memory SQLite StaticPool shares one DB-API connection across
        # threads. Use separate control connections, as the deployed database
        # does, so a sibling request's rollback cannot invalidate authentication.
        key=app.extensions.get('identity_bind_key');original=db.engines[key];replacement=None
        if original.dialect.name=='sqlite' and original.url.database in (None,'',':memory:'):
            import sqlite3
            from pathlib import Path
            from sqlalchemy import create_engine
            db.session.remove();filename=str(Path(self.root.name)/'concurrent-control.db')
            source=original.raw_connection();target=sqlite3.connect(filename)
            try:source.driver_connection.backup(target)
            finally:target.close();source.close()
            replacement=create_engine('sqlite:///'+filename,connect_args={'check_same_thread':False})
            db.engines[key]=replacement
        try:
            with ThreadPoolExecutor(max_workers=2) as pool:statuses=list(pool.map(send,range(2)))
        finally:
            db.session.remove()
            if replacement is not None:db.engines[key]=original;replacement.dispose()
        self.assertTrue(all(code in (200,409) for code in statuses),statuses);self.assertIn(200,statuses)
        self.assertEqual(self.saved(bid)['total'],370000);self.assertEqual(self.tenant(lambda:app.extensions['challan_amount_models']['change'].query.count()),1)

if __name__=='__main__':unittest.main()
