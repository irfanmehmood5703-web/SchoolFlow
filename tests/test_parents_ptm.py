"""Family identity, one-time credentials, fee rules and real PTM workflows."""
import os,re,tempfile,unittest,html,time,io
from datetime import date
from flask import g
from cryptography.fernet import Fernet
import base64,hashlib
os.environ['DATABASE_URL']='sqlite:///:memory:'
from app import app,db,Student,Employee

class ParentsPtmTests(unittest.TestCase):
    password='Fictional-parent-test-2026'
    def setUp(self):
        self.root=tempfile.TemporaryDirectory()
        app.config.update(TESTING=True,SECRET_KEY='fictional-parents',IDENTITY_ENFORCE_IN_TESTS=True,INSTITUTE_DATABASE_DIR=self.root.name)
        self.ctx=app.app_context();self.ctx.push();db.drop_all();db.create_all()
        self.H=app.extensions['identity_helpers'];self.M=app.extensions['parent_models'];self.P=app.extensions['ptm_models'];self.rm=app.extensions['record_models'];self.ops=app.extensions['ops_models']
        self.school=self.H['provision']('PARENT-TEST','Fictional School','owner@example.invalid',self.password).id
        def seed():
            for cat,values in {'campus':['North','South'],'class_name':['One'],'section':['A'],'subject':['Math']}.items():
                for v in values:db.session.add(self.rm['settings'](category=cat,value=v,class_name=''))
            for n in (1,2):
                f=self.rm['family'](number='F'+str(n),data={'father':'Fictional Guardian '+str(n),'phone':'0300000000'+str(n)})
                db.session.add(f);db.session.flush()
                s=Student(admission_no='S'+str(n),name='Fictional Child '+str(n),class_name='One',status='Active');db.session.add(s);db.session.flush()
                db.session.add(self.rm['student'](student_id=s.id,family_id=f.id,data={'campus':'North','section':'A'}))
            e=Employee(employee_no='E1',name='Fictional Teacher',role='Teacher',status='Active');db.session.add(e);db.session.flush()
            db.session.add(self.rm['employee'](employee_id=e.id,data={'campus':'North'}))
        self.tenant(seed)
        self.c=self.owner();self.n=0
    def tearDown(self):
        db.session.remove();g.pop('institute_engine',None);db.drop_all();self.ctx.pop()
        app.config.update(IDENTITY_ENFORCE_IN_TESTS=False,INSTITUTE_DATABASE_DIR=None);self.root.cleanup()
    def tenant(self,fn,sid=None):
        with app.test_request_context('/'):
            g.institute_engine=self.H['engine'](sid or self.school);db.session.remove()
            value=fn();db.session.commit();db.session.remove()
        g.pop('institute_engine',None);return value
    def token(self,c=None,path=None):
        c=c or self.c
        if path:c.get(path)
        with c.session_transaction() as s:return s['record_csrf']
    def owner(self,code='PARENT-TEST'):
        c=app.test_client();c.get('/auth/institute')
        token=self.token(c);c.post('/auth/institute',data={'_csrf':token,'code':code})
        c.post('/auth/login',data={'_csrf':self.token(c),'email':'owner@example.invalid','password':self.password});return c
    def post(self,path,data=None,c=None):
        c=c or self.c;return c.post(path,data={'_csrf':self.token(c),**(data or {})})
    def credential(self):
        r=self.post('/workspace/general/parents/links/1',{'action':'issue'})
        self.assertEqual(r.status_code,200,r.data[:200])
        full=html.unescape(re.search(rb'<strong data-parent-credential>(.*?)</strong>',r.data)[1].decode())
        return full.split('#')[1]
    def parent(self):
        credential=self.credential();c=app.test_client();self.token(c,'/parents/PARENT-TEST/enter')
        self.assertEqual(self.post('/parents/PARENT-TEST/enter',{'credential':credential},c).status_code,302);return c
    def test_manage_students_shows_linked_family_number_in_each_row(self):
        def sibling():
            s=Student(admission_no='S3',name='Fictional Sibling',class_name='One',status='Active')
            db.session.add(s);db.session.flush()
            db.session.add(self.rm['student'](student_id=s.id,family_id=1,data={'campus':'North','section':'A','family_no':'stale'}))
        self.tenant(sibling)
        page=self.c.get('/records/student')
        self.assertEqual(page.status_code,200)
        self.assertIn(b'Family No.</th>',page.data)
        for name,family in [('Fictional Child 1','F1'),('Fictional Child 2','F2'),('Fictional Sibling','F1')]:
            row=next(r for r in re.findall(rb'<tr>.*?</tr>',page.data,re.S) if name.encode() in r)
            self.assertIn(('<td class="family-number">'+family+'</td>').encode(),row)
        filtered=self.c.get('/records/student?q=F1')
        self.assertIn(b'Fictional Sibling',filtered.data)
        self.assertNotIn(b'Fictional Child 2',filtered.data)
        employees=self.c.get('/records/employee')
        self.assertEqual(employees.status_code,200)
        self.assertNotIn(b'Family No.</th>',employees.data)
    def test_all_reference_parent_and_ptm_tabs_render(self):
        paths=['/workspace/general/parents','/workspace/general/parents/links','/workspace/general/parents/otp','/workspace/general/parents/otp?tab=contact','/workspace/general/parents/otp?tab=not-installed','/workspace/general/parents/otp?tab=activity','/workspace/general/parents/privileges','/workspace/general/parents/privileges?tab=students','/workspace/general/parents/privileges?tab=students&student=1','/workspace/general/ptm/events','/workspace/general/ptm/events?new=1','/workspace/general/ptm/create','/workspace/general/ptm/meetings','/workspace/general/ptm/reports']
        for path in paths:
            r=self.c.get(path);self.assertEqual(r.status_code,200,path)
    def test_first_use_link_binds_family_and_cannot_replay_or_reach_admin(self):
        credential=self.credential();p=app.test_client();self.token(p,'/parents/PARENT-TEST/enter')
        self.assertEqual(self.post('/parents/PARENT-TEST/enter',{'credential':credential},p).status_code,302)
        page=p.get('/parents/PARENT-TEST');self.assertIn(b'Fictional Child 1',page.data);self.assertNotIn(b'Fictional Child 2',page.data)
        self.assertEqual(p.get('/parents/PARENT-TEST/students/2/fees').status_code,404)
        self.assertEqual(p.get('/workspace/general/parents').status_code,302)
        other=app.test_client();self.token(other,'/parents/PARENT-TEST/enter')
        self.assertNotEqual(self.post('/parents/PARENT-TEST/enter',{'credential':credential},other).status_code,302)
        self.assertEqual(self.tenant(lambda:self.M['account'].query.one().family_id),1)
    def test_cancel_replace_and_expiry_invalidate_links(self):
        old=self.credential();new=self.credential();p=app.test_client();self.token(p,'/parents/PARENT-TEST/enter')
        self.assertNotEqual(self.post('/parents/PARENT-TEST/enter',{'credential':old},p).status_code,302)
        self.post('/workspace/general/parents/links/1',{'action':'cancel'})
        self.assertNotEqual(self.post('/parents/PARENT-TEST/enter',{'credential':new},p).status_code,302)
        exp=self.credential()
        def expire():self.M['challenge'].query.filter_by(id=exp.split('.')[0]).one().expires=time.time()-1
        self.tenant(expire);self.assertNotEqual(self.post('/parents/PARENT-TEST/enter',{'credential':exp},p).status_code,302)
    def request_otp(self,phone='03000000001'):
        p=app.test_client();self.token(p,'/parents/PARENT-TEST/login')
        r=self.post('/parents/PARENT-TEST/login',{'action':'request','phone':phone},p)
        self.assertEqual(r.status_code,200)
        cid=re.search(rb'name="challenge" value="([^"]+)"',r.data)[1].decode()
        return p,cid
    def test_otp_encrypted_audited_one_use_and_activity_export_no_codes(self):
        p,cid=self.request_otp()
        page=self.c.get('/workspace/general/parents/otp')
        code=re.search(rb'<strong>([0-9]{6})</strong>',page.data)[1].decode()
        encrypted=self.tenant(lambda:self.M['challenge'].query.one().encrypted)
        self.assertNotIn(code.encode(),encrypted)
        self.assertTrue(self.tenant(lambda:self.ops['audit'].query.filter_by(action='View live parent OTP').count()))
        self.assertEqual(self.post('/parents/PARENT-TEST/login',{'action':'verify','challenge':cid,'otp':code},p).status_code,302)
        self.assertIn(b'Fictional Child 1',p.get('/parents/PARENT-TEST').data)
        self.assertIn(b'Active',self.c.get('/workspace/general/parents').data)
        export=self.c.get('/workspace/general/parents?export=xlsx');self.assertEqual(export.status_code,200)
        from openpyxl import load_workbook
        cells=str(list(load_workbook(io.BytesIO(export.data)).active.values))
        self.assertNotIn(code,cells)
    def test_bad_otp_attempts_lock_and_unknown_contact_is_generic(self):
        p,cid=self.request_otp()
        self.assertEqual(self.tenant(lambda:self.M['challenge'].query.count()),1)
        _,unknown=self.request_otp('03000000009')
        self.assertEqual(self.tenant(lambda:self.M['challenge'].query.count()),1)
        self.assertNotEqual(unknown,cid)
        for _ in range(5):self.post('/parents/PARENT-TEST/login',{'action':'verify','challenge':cid,'otp':'invalid'},p)
        def real_code():
            row=self.M['challenge'].query.one();key=base64.urlsafe_b64encode(hashlib.sha256(app.config['SECRET_KEY'].encode()+b'parent-code-encryption-v1').digest());return Fernet(key).decrypt(row.encrypted).decode()
        code=self.tenant(real_code)
        self.assertNotEqual(self.post('/parents/PARENT-TEST/login',{'action':'verify','challenge':cid,'otp':code},p).status_code,302)
    def test_school_shared_code_is_opt_in_reusable_and_phone_scoped(self):
        path='/workspace/general/parents/login-settings'
        login='/parents/PARENT-TEST/login'
        code='58312694'
        self.assertEqual(self.c.get(path).status_code,200)
        self.assertIn(b'Request a login code',app.test_client().get(login).data)
        payload={'version':'0','action':'enable','login_code':code,'confirm_code':code}
        self.assertEqual(self.post(path,payload).status_code,422)
        self.assertEqual(self.post(path,{**payload,'acknowledge':'yes'}).status_code,302)
        cfg=self.tenant(lambda:self.M['policy'].query.one().data)
        self.assertNotIn(code,str(cfg))
        login_page=app.test_client().get(login).data
        self.assertIn(b'School login code',login_page)
        self.assertIn(b'aria-controls="parent-login-code"',login_page)
        self.assertIn(b'aria-label="Show code"',login_page)
        self.assertIn(b'password-visibility.js',login_page)
        self.assertNotIn(b'Request a login code',app.test_client().get(login).data)
        def sign(number,pin=code):
            p=app.test_client();self.token(p,login)
            result=self.post(login,{'action':'shared','phone':number,'login_code':pin},p)
            return p,result
        p,r=sign('03000000001');self.assertEqual(r.status_code,302)
        self.assertIn(b'Fictional Child 1',p.get('/parents/PARENT-TEST').data)
        self.assertNotIn(b'Fictional Child 2',p.get('/parents/PARENT-TEST').data)
        self.assertEqual(p.get('/parents/PARENT-TEST/students/2/fees').status_code,404)
        q,r=sign('03000000002');self.assertEqual(r.status_code,302)
        self.assertIn(b'Fictional Child 2',q.get('/parents/PARENT-TEST').data)
        self.assertEqual(sign('03000000001')[1].status_code,302)
        self.assertEqual(sign('03000000001','12345678')[1].status_code,200)
        self.assertEqual(sign('03000000009')[1].status_code,200)
        self.assertEqual(self.tenant(lambda:self.M['challenge'].query.count()),0)
        self.assertEqual(self.post('/workspace/general/parents/privileges',{'version':'1','action':'rules'}).status_code,302)
        self.assertIn(b'School login code',app.test_client().get(login).data)
        self.assertEqual(self.post(path,{'version':'2','action':'disable'}).status_code,302)
        self.assertEqual(p.get('/parents/PARENT-TEST').status_code,302)
        self.assertIn(b'Request a login code',app.test_client().get(login).data)
    def test_shared_login_after_moving_siblings_ignores_empty_historical_families(self):
        code='58312694'
        path='/workspace/general/parents/login-settings'
        self.assertEqual(self.post(path,{'version':'0','action':'enable','login_code':code,'confirm_code':code,'acknowledge':'yes'}).status_code,302)
        def regroup():
            F=self.rm['family'];D=self.rm['student']
            old=db.session.get(F,2);old.data={**old.data,'phone':'03000000001'}
            D.query.filter_by(student_id=2).one().family_id=1
            for n in (3,4):
                f=F(number='F'+str(n),data={'phone':'03000000001'});db.session.add(f)
                s=Student(admission_no='S'+str(n),name='Fictional Child '+str(n),class_name='One',status='Active');db.session.add(s);db.session.flush()
                db.session.add(D(student_id=s.id,family_id=1,data={'campus':'North','section':'A'}))
            f=F(number='F5',data={'phone':'03000000005'});db.session.add(f);db.session.flush()
            s=Student(admission_no='S5',name='Fictional Child 5',class_name='One',status='Active');db.session.add(s);db.session.flush()
            db.session.add(D(student_id=s.id,family_id=f.id,data={'campus':'North','section':'A'}))
        self.tenant(regroup)
        p=app.test_client();login='/parents/PARENT-TEST/login';self.token(p,login)
        self.assertEqual(self.post(login,{'action':'shared','phone':'0300-0000001','login_code':code},p).status_code,302)
        page=p.get('/parents/PARENT-TEST')
        self.assertEqual(page.status_code,200)
        for n in (1,2,3,4):self.assertIn(('Fictional Child '+str(n)).encode(),page.data)
        self.assertNotIn(b'Fictional Child 5',page.data)
        self.assertEqual(p.get('/parents/PARENT-TEST/students/5/fees').status_code,404)
        self.assertEqual(self.tenant(lambda:self.rm['family'].query.count()),5)

    def test_school_shared_code_rejects_ambiguous_registered_number(self):
        path='/workspace/general/parents/login-settings'
        code='58312694'
        self.assertEqual(self.post(path,{'version':'0','action':'enable','login_code':code,'confirm_code':code,'acknowledge':'yes'}).status_code,302)
        def duplicate():
            family=db.session.get(self.rm['family'],2)
            family.data={**family.data,'phone':'03000000001'}
        self.tenant(duplicate)
        p=app.test_client();login='/parents/PARENT-TEST/login';self.token(p,login)
        self.assertEqual(self.post(login,{'action':'shared','phone':'03000000001','login_code':code},p).status_code,200)
        self.assertEqual(p.get('/parents/PARENT-TEST').status_code,302)
    def test_otp_request_rate_limit(self):
        p=app.test_client();self.token(p,'/parents/PARENT-TEST/login')
        for _ in range(5):self.assertEqual(self.post('/parents/PARENT-TEST/login',{'action':'request','phone':'03000000001'},p).status_code,200)
        limited=self.post('/parents/PARENT-TEST/login',{'action':'request','phone':'03000000001'},p)
        self.assertEqual(limited.status_code,429)
        self.assertIn(b'Too many login attempts',limited.data)
        self.assertIn(b'Fictional School',limited.data)
        self.assertIn(b'Back to Login',limited.data)
        self.assertIn(b'Pakistan time',limited.data)
        self.assertTrue(0<int(limited.headers['Retry-After'])<=3600)
        self.assertIn('no-store',limited.headers['Cache-Control'])
        again=self.post('/parents/PARENT-TEST/login',{'action':'request','phone':'03000000001'},p)
        self.assertEqual(again.status_code,429)
        self.assertLessEqual(int(again.headers['Retry-After']),int(limited.headers['Retry-After']))
        self.assertEqual(p.get('/parents/PARENT-TEST/login').status_code,200)
    def test_parent_csrf_and_cross_institute_tokens(self):
        credential=self.credential()
        other_school=self.H['provision']('OTHER-SCHOOL','Other Fictional School','owner@example.invalid',self.password).id
        p=app.test_client();self.token(p,'/parents/OTHER-SCHOOL/enter')
        self.assertNotEqual(self.post('/parents/OTHER-SCHOOL/enter',{'credential':credential},p).status_code,302)
        self.assertEqual(p.post('/parents/PARENT-TEST/enter',data={'credential':credential}).status_code,400)
    def seed_debt(self):
        def seed():
            for month in ('2026-01','2026-02','2026-03'):
                db.session.add(self.ops['bill'](student_id=1,month=month,due=date(2026,1,10),lines=[{'particular':'Tuition','amount':10000}]))
        self.tenant(seed)
    def test_rules_enforced_on_parent_routes_and_nonblockable_features(self):
        self.seed_debt()
        self.assertEqual(self.post('/workspace/general/parents/privileges',{'version':'0','action':'rules','diary_3':'block','notice_3':'warn'}).status_code,302)
        p=self.parent()
        self.assertEqual(p.get('/parents/PARENT-TEST/students/1/diary').status_code,403)
        self.assertIn(b'Fees are pending',p.get('/parents/PARENT-TEST/students/1/notice').data)
        for feature in ('fees','pickup','help'):self.assertEqual(p.get('/parents/PARENT-TEST/students/1/'+feature).status_code,200)
        self.assertEqual(self.post('/workspace/general/parents/privileges',{'version':'1','action':'rules','fees_3':'block'}).status_code,422)
        self.assertEqual(self.post('/workspace/general/parents/privileges',{'version':'0','action':'rules'}).status_code,422)
    def test_highest_configured_rule_persists_after_allow_removes_a_higher_band(self):
        self.seed_debt()
        self.assertEqual(self.post('/workspace/general/parents/privileges',{'version':'0','action':'rules','diary_1':'block','notice_1':'warn','notice_2':'block'}).status_code,302)
        p=self.parent()
        self.assertEqual(p.get('/parents/PARENT-TEST/students/1/diary').status_code,403)
        self.assertEqual(p.get('/parents/PARENT-TEST/students/1/notice').status_code,403)
        self.assertEqual(self.post('/workspace/general/parents/privileges',{'version':'1','action':'rules','diary_1':'block','notice_1':'warn','notice_2':'allow'}).status_code,302)
        response=p.get('/parents/PARENT-TEST/students/1/notice')
        self.assertEqual(response.status_code,200)
        self.assertIn(b'Fees are pending',response.data)

    def test_override_notes_are_staff_only_clear_and_expire(self):
        self.seed_debt();self.post('/workspace/general/parents/privileges',{'version':'0','action':'rules','diary_3':'block'})
        self.assertEqual(self.post('/workspace/general/parents/privileges',{'version':'1','action':'student','student_id':'1','diary_mode':'allow','diary_note':'Private staff note'}).status_code,302)
        p=self.parent();r=p.get('/parents/PARENT-TEST/students/1/diary');self.assertEqual(r.status_code,200);self.assertNotIn(b'Private staff note',r.data)
        def expire():
            cfg=self.M['policy'].query.one();cfg.data={**cfg.data,'overrides':{'1':{'diary':{'mode':'allow','until':'2000-01-01'}}}}
        self.tenant(expire);self.assertEqual(p.get('/parents/PARENT-TEST/students/1/diary').status_code,403)
    def test_revoke_signs_out_existing_parent_session(self):
        p=self.parent()
        self.assertEqual(p.get('/parents/PARENT-TEST').status_code,200)
        self.assertEqual(self.post('/workspace/general/parents/links/1',{'action':'revoke'}).status_code,302)
        self.assertEqual(p.get('/parents/PARENT-TEST').status_code,302)
    def test_notice_targets_attachments_and_real_view_counts(self):
        from datetime import timedelta
        from werkzeug.datastructures import MultiDict
        day=date.today()
        payload=MultiDict([('_csrf',self.token()),('submission','n'*43),('title','Parent-visible notice'),('description','Fictional notice contents'),('starts',str(day)),('ends',str(day+timedelta(days=1))),('campus','North'),('classes','One'),('attachments',(io.BytesIO(b'%PDF-1.4\\nfictional'),'parent.pdf'))])
        self.assertEqual(self.c.post('/workspace/general/notices',data=payload).status_code,302)
        p=self.parent()
        page=p.get('/parents/PARENT-TEST/students/1/notice')
        self.assertIn(b'Parent-visible notice',page.data)
        path=re.search(rb'href="([^"]+/notices/[^"]+)"',page.data)[1].decode()
        self.assertEqual(p.get(path).status_code,200)
        self.assertEqual(p.get(path.replace('/students/1/','/students/2/')).status_code,404)
        p.get('/parents/PARENT-TEST/students/1/notice')
        self.assertEqual(self.tenant(lambda:self.M['seen'].query.count()),1)
        self.assertIn(b'1 profiles',self.c.get('/workspace/general/notices').data)
        def expire():
            row=app.extensions['student_extras_models']['entry'].query.one()
            row.starts=day-timedelta(days=2);row.ends=day-timedelta(days=1)
        self.tenant(expire)
        self.assertNotIn(b'Parent-visible notice',p.get('/parents/PARENT-TEST/students/1/notice').data)
        self.assertEqual(p.get(path).status_code,404)
    def test_export_column_checkboxes_preserve_selection(self):
        page=self.c.get('/workspace/general/parents?columns=SID&columns=Student')
        self.assertEqual(page.status_code,200)
        self.assertIn(b'type="checkbox" name="columns" value="SID" checked',page.data)
        self.assertIn(b'type="checkbox" name="columns" value="Student" checked',page.data)
        self.assertNotIn(b'type="checkbox" name="columns" value="Campus" checked',page.data)
        self.assertNotIn(b'<select name="columns"',page.data)

    def test_filters_and_selected_export_columns_are_validated(self):
        self.assertEqual(self.c.get('/workspace/general/parents?from=invalid').status_code,422)
        self.assertEqual(self.c.get('/workspace/general/parents?campus=Unknown').status_code,422)
        response=self.c.get('/workspace/general/parents?export=xlsx&columns=SID&columns=Student')
        from openpyxl import load_workbook
        self.assertEqual(list(load_workbook(io.BytesIO(response.data)).active.values)[0],('SID','Student'))

    def test_invitation_saves_intent_and_never_claims_delivery(self):
        self.assertEqual(self.post('/workspace/general/parents/invitation',{'students':['1'],'message':'Fictional invitation','father':'1','app':'1'}).status_code,302)
        self.assertEqual(self.tenant(lambda:self.rm['communication'].query.one().status),'Provider not configured')
    def event(self):
        self.n+=1
        r=self.post('/workspace/general/ptm/events',{'title':'Fictional Term Event','starts':'2026-11-07','ends':'2026-11-09','campus':'North','submission':str(self.n).zfill(43)})
        self.assertEqual(r.status_code,302);return self.tenant(lambda:self.P['event'].query.order_by(self.P['event'].id.desc()).first().id)
    def meeting(self,event,**changes):
        self.n+=1
        data=dict(event_id=str(event),student_id='1',employee_id='1',day='2026-11-07',time='09:00',submission=str(self.n).zfill(43));data.update(changes)
        return self.post('/workspace/general/ptm/create',data)
    def test_ptm_event_meeting_conflicts_attendance_report_and_export(self):
        event=self.event();self.assertEqual(self.meeting(event).status_code,302)
        self.assertEqual(self.meeting(event,student_id='2').status_code,409)
        self.assertEqual(self.post('/workspace/general/ptm/meetings/1',{'version':'1','status':'Attended','feedback':'Fictional feedback'}).status_code,302)
        page=self.c.get('/workspace/general/ptm/reports?event_id='+str(event));self.assertIn(b'Fictional feedback',page.data)
        self.assertEqual(self.c.get('/workspace/general/ptm/reports?export=xlsx').status_code,200)
        self.assertEqual(self.post('/workspace/general/ptm/meetings/1',{'version':'1','status':'Absent'}).status_code,422)
    def test_ptm_date_validation_and_cancel_releases_slot(self):
        event=self.event();self.assertEqual(self.meeting(event,day='2026-12-01').status_code,422)
        self.assertEqual(self.meeting(event).status_code,302)
        self.assertEqual(self.post('/workspace/general/ptm/meetings/1',{'version':'1','status':'Cancelled'}).status_code,302)
        self.assertEqual(self.meeting(event,student_id='2').status_code,302)
        self.assertEqual(self.post('/workspace/general/ptm/meetings/1',{'version':'2','status':'Scheduled'}).status_code,409)

if __name__=='__main__':unittest.main()
