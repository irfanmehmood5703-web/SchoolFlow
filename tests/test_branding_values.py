"""Saved-person report values, private assets, salary snapshots and safe expansion."""
import os,unittest
from datetime import date
from flask import g
from markupsafe import Markup
os.environ['DATABASE_URL']='sqlite:///:memory:'
from app import app,db,Student,Employee
from branding_values import expand_tags,missing_tags

class BrandingValueTests(unittest.TestCase):
    def setUp(self):
        app.config.update(TESTING=True,IDENTITY_ENFORCE_IN_TESTS=False,SECRET_KEY='branding-values-tests')
        self.ctx=app.app_context();self.ctx.push();db.drop_all();db.create_all()
        self.rm=app.extensions['record_models'];self.ops=app.extensions['ops_models'];self.m=app.extensions['school_settings_models'];self.b=app.extensions['branding_values']
        self.employee=Employee(employee_no='TEST-E-1',name='Fictional Employee',role='Teacher',phone='00000000000',status='Active')
        self.student=Student(admission_no='TEST-S-1',name='Fictional Pupil',father='Old father',class_name='Class A',status='Active')
        db.session.add_all([self.employee,self.student]);db.session.flush()
        self.employee_detail=self.rm['employee'](employee_id=self.employee.id,data={'campus':'Campus A','gender':'Other','father_name':'Employee Guardian','marital_status':'Married','joining_date':'2000-01-01','qualification_degree':'MA','qualification_major':'English','agreement_no':'AGR-TEST','email':'fictional@example.invalid'})
        self.student_detail=self.rm['student'](student_id=self.student.id,data={'campus':'Campus A','section':'A','academic_session':'2026-27','roll_no':'27','exam_roll_no':'900','student_cnic':'B-FORM-TEST','mother_name':'Fictional Mother'})
        db.session.add_all([self.employee_detail,self.student_detail]);db.session.add(app.extensions['institute_setup_models']['campus'](name='Campus A',city='Test City'));db.session.commit()
        self.c=app.test_client();self.c.get('/workspace/core/hrm')
        with self.c.session_transaction() as session:self.csrf=session['record_csrf']
    def tearDown(self):db.session.remove();db.drop_all();self.ctx.pop()
    def template(self,body,kind='print-template',name='Employment Letter',**parts):
        row=self.m['item'](kind=kind,name=name,scope='Campus A',data={'body':body,**parts});db.session.add(row);db.session.commit();return row
    def award(self):
        row=self.ops['workflow'](kind='awards',status='Active',data={'name':'Fictional Exam','campus':'Campus A','class_name':'Class A','academic_session':'2026-27','papers':[{'subject':'English','type':'Written','total':20},{'subject':'Math','type':'Written','total':30}]})
        db.session.add(row);db.session.commit();return row
    def test_expand_is_single_pass_and_never_trusts_record_markup(self):
        self.assertEqual(expand_tags('[emp_name] [emp_photo]',{'emp_name':'[emp_photo]'},True,{'emp_photo':'<img src="/records/files/1">'}),'[emp_photo] <img src="/records/files/1">')
        self.assertEqual(expand_tags('[emp_name]',{'emp_name':Markup('<script>bad()</script>')},True),'&lt;script&gt;bad()&lt;/script&gt;')
        self.assertEqual(missing_tags('[emp_name]',{'emp_name':'[cheque_no]'}),[])
        self.assertEqual(missing_tags('[emp_name] [cheque_no]',{'emp_name':'Known'}),['cheque_no'])
    def test_employee_letter_saved_fields_neutral_words_and_latest_approved_plan(self):
        self.template('<p>[emp_father_name]|[emp_email]|[agreement_no]|[emp_marital_status]|[he_she]|[emp_degrees]|[plan_basic_salary]|[plan_net_salary]</p>')
        for status,basic in [('Approved',100000),('Approved',200000),('Pending',900000)]:db.session.add(self.ops['workflow'](kind='salary-plans',status=status,data={'employee_id':str(self.employee.id),'basic':basic,'security_payment':10000,'security_return':0}))
        db.session.commit();page=self.c.get('/workspace/core/hrm/print-template/1?employee_id=1')
        self.assertEqual(page.status_code,200);self.assertIn(b'Employee Guardian|fictional@example.invalid|AGR-TEST|Married|they|MA',page.data);self.assertIn(b'2,000.00|1,900.00',page.data);self.assertNotIn(b'9,000.00',page.data)
    def test_photo_logo_and_qr_use_private_endpoints_without_reexpanding_name(self):
        self.employee.name='[institute_logo]'
        profile=app.extensions['institute_setup_models']['profile'](id=1,data={'name':'Fictional School'},logo=b'PNG',logo_mime='image/png')
        photo=self.rm['file'](owner_kind='employee',owner_id=1,photo=True,title='Photo',filename='photo.png',mime='image/png',content=b'PNG',sha256='test-hash')
        db.session.add_all([profile,photo]);db.session.commit()
        self.template('[emp_name] [emp_photo] [emp_qr]',header='[institute_logo]')
        page=self.c.get('/workspace/core/hrm/print-template/1?employee_id=1')
        self.assertEqual(page.status_code,200);self.assertIn(b'[institute_logo]',page.data)
        self.assertEqual(page.data.count(b'src="/workspace/core/logo"'),2) # shared heading plus document logo
        self.assertIn(f'src="/records/files/{photo.id}"'.encode(),page.data);self.assertIn(b'src="/workspace/core/hrm/employee-qr/1.svg"',page.data)
        qr=self.c.get('/workspace/core/hrm/employee-qr/1.svg');self.assertEqual(qr.status_code,200);self.assertEqual(qr.mimetype,'image/svg+xml');self.assertIn('no-store',qr.headers['Cache-Control'])
    def test_record_values_are_escaped_and_final_styles_are_resanitized(self):
        self.employee.name='<img src=x onerror=bad()>'
        self.employee_detail.data={**self.employee_detail.data,'notes':'red;position:fixed;background-image:url(https://evil.invalid/exfil)'};db.session.commit()
        self.template('<p>[emp_name]</p><span style="color:[emp_notes]">Style</span>')
        page=self.c.get('/workspace/core/hrm/print-template/1?employee_id=1')
        self.assertEqual(page.status_code,200);self.assertIn(b'&lt;img',page.data);self.assertNotIn(b'<img src=x',page.data);self.assertNotIn(b'position:fixed',page.data);self.assertNotIn(b'evil.invalid',page.data)
    def test_result_roster_includes_unmarked_students_and_uses_real_family_values(self):
        family=self.rm['family'](number='TEST-FAMILY',data={'father':'Canonical Father','phone':'00000000001','mother_name':'Canonical Mother'});db.session.add(family);db.session.flush();self.student_detail.family_id=family.id
        second=Student(admission_no='TEST-S-2',name='Unmarked Pupil',class_name='Class A',status='Active');db.session.add(second);db.session.flush();db.session.add(self.rm['student'](student_id=second.id,data={'campus':'Campus A','section':'A','academic_session':'2026-27'}))
        db.session.commit();award=self.award()
        db.session.add_all([self.ops['score'](award_id=award.id,student_id=1,paper=0,obtained=15,state=''),self.ops['score'](award_id=award.id,student_id=1,paper=1,obtained=30,state='A'),self.ops['score'](award_id=award.id,student_id=1,paper=99,obtained=999,state='')]);db.session.commit()
        self.template('[studentName]|[fatherName]|[fatherMobile]|[motherName]|[studentCnic]|[examRollNo]|[campus_city]',kind='exam-branding',name='Result Card')
        page=self.c.get('/workspace/core/exam/results/'+str(award.id))
        self.assertEqual(page.status_code,200);self.assertIn(b'Canonical Father|00000000001|Canonical Mother|B-FORM-TEST|900|Test City',page.data)
        self.assertIn(b'Unmarked Pupil',page.data);self.assertIn(b'Incomplete',page.data);self.assertIn(b'Absent',page.data);self.assertIn(b'<td>15.00</td>',page.data);self.assertNotIn(b'1,014',page.data)
    def test_salary_slip_uses_its_snapshot_instead_of_later_salary_plan(self):
        self.template('[emp_name]|[plan_basic_salary]|[earnings]|[deductions]|[attendance_deduction]|[plan_deduction_advance_salary]|[net_salary]|[salary_status]',kind='hrm-branding',name='Salary Slip Report')
        salary=self.ops['salary'](employee_id=1,month='2026-09',earnings=100000,deductions=25000,net=75000,paid=50000,detail={'basic':100000,'lecture_pay':0,'attendance':[{'status':'Absent','count':1,'amount':5000}],'advances':{'1':10000},'plan':{'basic':100000,'security_return':0,'security_payment':10000}})
        db.session.add(salary);db.session.add(self.ops['workflow'](kind='salary-plans',status='Approved',data={'employee_id':'1','basic':900000}));db.session.commit()
        page=self.c.post('/workspace/payroll',data={'_csrf':self.csrf,'month':'2026-09','action':'slip','ids':str(salary.id)})
        self.assertEqual(page.status_code,200);self.assertIn(b'Fictional Employee|1,000.00|1,000.00|250.00|50.00|100.00|750.00|Partially Paid',page.data);self.assertNotIn(b'9,000.00',page.data)
    def test_employee_qr_is_opaque_stable_and_has_an_institute_namespace(self):
        with app.test_request_context():
            g.school_identity={'scope':'school-a'};a=self.b['qr_token'](self.employee);self.assertEqual(a,self.b['qr_token'](self.employee))
            g.school_identity={'scope':'school-b'};b=self.b['qr_token'](self.employee)
        self.assertNotEqual(a,b);self.assertNotIn(self.employee.employee_no,a);self.assertNotIn(self.employee.name,a)
    def test_unavailable_tags_are_reported_without_inventing_values(self):
        self.employee.name='[cheque_no]';db.session.commit();t=self.template('[emp_name]')
        page=self.c.get('/workspace/core/hrm/print-template/1?employee_id=1');self.assertNotIn(b'These tags are unavailable',page.data)
        t.data={'body':'[emp_name] [cheque_no]'};db.session.commit()
        page=self.c.get('/workspace/core/hrm/print-template/1?employee_id=1');self.assertIn(b'These tags are unavailable',page.data);self.assertIn(b'cheque_no',page.data)

    def test_generated_salary_sms_is_opt_in_and_not_duplicated_on_replay(self):
        plan=self.ops['workflow'](kind='salary-plans',status='Approved',data={'employee_id':'1','basic':100000,'security_return':0,'security_payment':0,'rules':[]})
        template=self.m['setting'](key='hrm:sms:Campus A',data={'Generate Salary':'[emp_name]: [salary_month] [net_salary] [salary_status]'})
        db.session.add_all([plan,template]);db.session.commit()
        form={'_csrf':self.csrf,'action':'generate','month':'2026-09','employee_ids':'1','generate_sms':'1'}
        self.assertEqual(self.c.post('/workspace/payroll',data=form).status_code,302)
        message=self.ops['workflow'].query.filter_by(kind='message').one();self.assertEqual(message.status,'Provider not configured');self.assertEqual(message.data['messages'][0]['text'],'Fictional Employee: 2026-09 1,000.00 Unpaid')
        self.assertEqual(self.c.post('/workspace/payroll',data=form).status_code,302);self.assertEqual(self.ops['workflow'].query.filter_by(kind='message').count(),1)
        page=self.c.get('/workspace/message-log');self.assertIn(b'Fictional Employee: 2026-09 1,000.00 Unpaid',page.data)

    def test_custom_student_message_expands_family_values_and_reports_unavailable_tags(self):
        self.student_detail.data={**self.student_detail.data,'guardian_name':'Fictional Guardian','mother_phone':'00000000003'};db.session.commit()
        response=self.c.post('/workspace/messages',data={'_csrf':self.csrf,'student_ids':'1','message':'[studentName]|[guardianName]|[motherMobile]|[parentsAppOTP]'})
        self.assertEqual(response.status_code,302)
        message=self.ops['workflow'].query.filter_by(kind='message').one().data['messages'][0]
        self.assertEqual(message['text'],'Fictional Pupil|Fictional Guardian|00000000003|[parentsAppOTP]');self.assertEqual(message['unresolved'],['parentsAppOTP'])

    def test_custom_message_text_is_never_interpreted_as_an_internal_event(self):
        for text in ('Attendance','Salary generated','Salary paid'):
            response=self.c.post('/workspace/messages',data={'_csrf':self.csrf,'student_ids':'1','message':text})
            self.assertEqual(response.status_code,302)
        messages=self.ops['workflow'].query.filter_by(kind='message').order_by(self.ops['workflow'].id).all()
        self.assertEqual([row.data['messages'][0]['text'] for row in messages],['Attendance','Salary generated','Salary paid'])

    def test_multi_month_salary_advice_has_one_snapshot_per_selected_salary(self):
        db.session.add(self.m['setting'](key='hrm:sms:Campus A',data={'Pay Salary':'[salary_month]: [net_salary]'}))
        for month in ['2026-08','2026-09']:
            db.session.add(self.ops['salary'](employee_id=1,month=month,earnings=10000,deductions=0,net=10000,paid=0,detail={'plan':{},'attendance':[]}))
        db.session.commit();rows=self.ops['salary'].query.all()
        response=self.c.post('/workspace/payroll',data={'_csrf':self.csrf,'month':'2026-09','action':'send','ids':[str(r.id) for r in rows],'paid_date':'2026-10-01','credit':'Test credit','debit':'Test debit'})
        self.assertEqual(response.status_code,302)
        messages=self.ops['workflow'].query.filter_by(kind='message').one().data['messages']
        self.assertEqual([r['text'] for r in messages],['2026-08: 100.00','2026-09: 100.00']);self.assertEqual({r['source_salary_id'] for r in messages},{r.id for r in rows})

    def test_report_asset_paths_do_not_change_certificate_image_freeze_policy(self):
        from certificates import clean_html
        html='<img src="/workspace/core/hrm/employee-qr/1.svg"><img src="/workspace/core/logo">'
        self.assertNotIn('src=',clean_html(html))
        self.assertIn('src="/workspace/core/logo"',clean_html(html,report_assets=True))

    def test_result_campus_and_cohort_tags_retain_the_assessment_scope_after_transfer(self):
        award=self.award();db.session.add(self.ops['score'](award_id=award.id,student_id=1,paper=0,obtained=10,state=''))
        self.student.class_name='Later Class';self.student_detail.data={**self.student_detail.data,'campus':'Campus B','academic_session':'2027-28'}
        db.session.add(app.extensions['institute_setup_models']['campus'](name='Campus B',city='Later City'));db.session.commit()
        self.template('[campus_name]|[campus_city]|[className]|[SessionName]',kind='exam-branding',name='Result Card')
        page=self.c.get('/workspace/core/exam/results/'+str(award.id))
        self.assertEqual(page.status_code,200);self.assertIn(b'Campus A|Test City|Class A|2026-27',page.data);self.assertNotIn(b'Campus B|Later City',page.data)

    def test_result_render_batches_person_data_and_private_photo_metadata(self):
        from sqlalchemy import event
        for i in range(2,32):
            pupil=Student(id=i,admission_no='BATCH-'+str(i),name='Batch Pupil '+str(i),class_name='Class A',status='Active');db.session.add(pupil)
            db.session.add(self.rm['student'](student_id=i,data={'campus':'Campus A','academic_session':'2026-27'}))
        db.session.commit();award=self.award();self.template('[studentName] [campus_city] [stdPic]',kind='exam-branding',name='Result Card')
        statements=[]
        def capture(conn,cursor,statement,parameters,context,executemany):
            if statement.lstrip().upper().startswith('SELECT'):statements.append(statement)
        event.listen(db.engine,'before_cursor_execute',capture)
        try:response=self.c.get('/workspace/core/exam/results/'+str(award.id))
        finally:event.remove(db.engine,'before_cursor_execute',capture)
        self.assertEqual(response.status_code,200);self.assertIn(b'Batch Pupil 31',response.data)
        self.assertLessEqual(len(statements),25);self.assertFalse(any('record_file.content' in q for q in statements))

    def test_final_policy_remarks_are_escaped_and_shown_only_for_complete_results(self):
        policy=self.m['item'](kind='grading',name='Policy',scope='',data={'bands':[{'min':'0','max':'100','grade':'A','remarks':'Good'}],'final_remarks':'<Study well>'})
        db.session.add(policy);db.session.flush();db.session.add(self.m['item'](kind='class-grading',name='Assignment',scope='Campus A',data={'classes':['Class A'],'policy':policy.id}));db.session.commit()
        award=self.award()
        first=self.ops['score'](award_id=award.id,student_id=1,paper=0,obtained=15,state='');second=self.ops['score'](award_id=award.id,student_id=1,paper=1,obtained=20,state='')
        db.session.add_all([first,second]);db.session.commit()
        page=self.c.get('/workspace/core/exam/results/'+str(award.id));self.assertEqual(page.status_code,200);self.assertIn(b'&lt;Study well&gt;',page.data);self.assertNotIn(b'<Study well>',page.data)
        second.obtained=None;db.session.commit();self.assertNotIn(b'&lt;Study well&gt;',self.c.get('/workspace/core/exam/results/'+str(award.id)).data)
