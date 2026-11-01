"""Report calculations must reflect receipt dates and never invent allocations."""
import os,unittest
from datetime import date
os.environ['DATABASE_URL']='sqlite:///:memory:'
from app import app,db,Student,Employee

class ReportTests(unittest.TestCase):
    def setUp(self):
        app.config.update(TESTING=True,SECRET_KEY='report-test')
        self.ctx=app.app_context();self.ctx.push();db.drop_all();db.create_all();self.m=app.extensions['ops_models'];self.rm=app.extensions['record_models']
        self.s=Student(admission_no='R1',name='Fictional Pupil',father='Fictional Father',class_name='Class One',status='Active');self.empty=Student(admission_no='R2',name='No Challan Pupil',class_name='Class One',status='Active')
        self.e=Employee(employee_no='T1',name='Fictional Teacher',role='Subject Teacher',status='Active');db.session.add_all([self.s,self.empty,self.e]);db.session.flush()
        self.bill=self.m['bill'](student_id=self.s.id,month='2026-09',due=date(2026,9,10),lines=[dict(particular='Tuition',amount=100000)],paid=25000,discount=5000)
        db.session.add(self.bill);db.session.flush();db.session.add(self.m['receipt'](student_id=self.s.id,bill_id=self.bill.id,amount=25000,discount=5000,day=date(2026,10,2),account='Cash',token='fixture-receipt'))
        db.session.commit();self.c=app.test_client()
    def tearDown(self):db.session.remove();db.drop_all();self.ctx.pop()
    def get(self,path):return self.c.get('/workspace/reports/'+path)
    def test_day_wise_filters_receipt_date_not_bill_month(self):
        sep=self.get('fees/daily-fees?from=2026-09&to=2026-09&export=csv').data.decode()
        oct=self.get('fees/daily-fees?from=2026-10&to=2026-10&export=csv').data.decode()
        self.assertNotIn('250.00',sep);self.assertIn('2026-10-02,Cash,1,250.00,50.00',oct)
        self.assertNotIn('250.00',self.get('fees/daily-fees?from=2026-10&to=2026-10&account=Bank&export=csv').data.decode())
    def test_bill_month_report_and_no_challan_strength(self):
        text=self.get('fees/student-fees?from=2026-09&to=2026-09&export=csv').data.decode()
        self.assertIn('Fictional Pupil',text);self.assertIn('700.00',text);self.assertIn('No Challan Pupil',text)
        self.assertIn('0,0.00,0.00,0.00,0.00,0,0,0,0,1',text)
    def test_particular_payments_not_guessed_for_legacy_mixed_bill(self):
        self.bill.lines=[dict(particular='Tuition',amount=80000),dict(particular='Books',amount=20000)];db.session.commit()
        text=self.get('fees/class-fees?from=2026-09&to=2026-09&export=csv').data.decode()
        self.assertIn('Books',text);self.assertIn('Allocation unavailable',text)
        self.assertNotIn('250.00',text)
    def test_defaulter_reminder_has_only_outstanding_students(self):
        text=self.get('fees/fee-reminder?from=2026-09&to=2026-09').data.decode()
        self.assertIn('Fictional Pupil',text);self.assertNotIn('No Challan Pupil',text);self.assertIn('700.00',text)
        self.assertEqual(self.get('fees/defaulters?from=2026-09&to=2026-09&pending_months=2').status_code,200)
    def test_attendance_distinct_reports_and_consecutive_dates(self):
        for d in [1,2,4]:db.session.add(self.m['daily'](kind='student',person_id=self.s.id,day=date(2026,9,d),status='Absent'))
        db.session.commit()
        text=self.get('attendance/absentees?from=2026-09&to=2026-09&absence_count=2&consecutive=1&export=csv').data.decode()
        self.assertIn('3,2,',text)
        text=self.get('attendance/absentees?from=2026-09&to=2026-09&absence_count=3&consecutive=1&export=csv').data.decode();self.assertNotIn('Fictional Pupil',text)
        for view in ['combined-attendance','daily-attendance','individual-attendance','attendance-summary','attendance-sheet','staff-attendance-report']:
            self.assertEqual(self.get(f'attendance/{view}?from=2026-09&to=2026-09').status_code,200,view)
    def test_teacher_performance_excludes_absence_from_average(self):
        w=self.m['workflow'](kind='awards',status='Active',data=dict(papers=[dict(subject='Math',date='2026-09-02',type='Written',total=50,teacher=str(self.e.id))]))
        db.session.add(w);db.session.flush();db.session.add_all([self.m['score'](award_id=w.id,student_id=self.s.id,paper=0,obtained=40,state=''),self.m['score'](award_id=w.id,student_id=self.empty.id,paper=0,state='A')]);db.session.commit()
        text=self.get('teacher-performance?from=2026-09&to=2026-09&pass_mark=50&export=csv').data.decode()
        self.assertIn('Fictional Teacher,1,1,1,0,1,0,80.00%,100.00%',text)
    def test_invalid_dates_and_passmarks_rejected(self):
        for path in ['fees/fee-report?from=bad','fees/fee-report?from=2026-11&to=2026-09','teacher-performance?pass_mark=NaN','attendance/absentees?absence_count=-1']:
            self.assertEqual(self.get(path).status_code,422,path)

    def test_excel_export_uses_identical_filtered_rows_numeric_money_and_safe_strings(self):
        import io
        from openpyxl import load_workbook
        self.s.name='=HYPERLINK("https://example.invalid","unsafe")';db.session.commit()
        response=self.get('fees/student-fees?from=2026-09&to=2026-09&person_id='+str(self.s.id)+'&export=xlsx')
        self.assertEqual(response.status_code,200);self.assertIn('spreadsheetml',response.mimetype);self.assertEqual(response.headers['Cache-Control'],'no-store')
        book=load_workbook(io.BytesIO(response.data),data_only=False);sheet=book['Report'];headers=[c.value for c in sheet[1]];row=[c.value for c in sheet[2]]
        self.assertEqual(sheet.max_row,2);self.assertEqual(row[headers.index('Student')],self.s.name);self.assertEqual(sheet.cell(2,headers.index('Student')+1).data_type,'s')
        self.assertEqual(row[headers.index('Payable')],1000);self.assertEqual(row[headers.index('Remaining')],700)
        self.assertIn(('person_id',str(self.s.id)),list(book['Filters'].values));self.assertEqual(sheet.freeze_panes,'A2')
    def test_excel_attendance_has_saved_marks_and_unmarked_days(self):
        import io
        from openpyxl import load_workbook
        db.session.add(self.m['daily'](kind='student',person_id=self.s.id,day=date(2026,9,1),status='Present'));db.session.commit()
        response=self.get('attendance/attendance-sheet?from=2026-09-01&to=2026-09-02&export=xlsx');self.assertEqual(response.status_code,200)
        rows=list(load_workbook(io.BytesIO(response.data))['Report'].values);self.assertIn((self.s.id,None,self.s.name,'P','—'),rows)
    def test_individual_attendance_branding_receives_person_campus_and_saved_times(self):
        Item=app.extensions['school_settings_models']['item'];db.session.add(self.rm['employee'](employee_id=self.e.id,data={'campus':'Campus A','bank_info':'Fictional bank'}))
        db.session.add(Item(kind='hrm-branding',scope='Campus A',name='Individual Attendance Report',data=dict(header='[emp_name]|[emp_id]|[date]|[time]|[qr_status]',body='',footer='')))
        db.session.add(self.m['daily'](kind='staff',person_id=self.e.id,day=date(2026,9,1),status='Late',time_in='08:15'));db.session.commit()
        page=self.get('attendance/staff-attendance-report?from=2026-09-01&to=2026-09-01&person_id='+str(self.e.id));self.assertEqual(page.status_code,200)
        self.assertIn(b'Fictional Teacher|T1|2026-09-01|08:15|Late',page.data);self.assertNotIn(b'[emp_name]',page.data)
    def test_student_attendance_branding_uses_actual_details_not_other_pupil(self):
        Item=app.extensions['school_settings_models']['item'];db.session.add(self.rm['student'](student_id=self.s.id,data={'campus':'Campus A','roll_no':'0007','section':'A'}))
        db.session.add(Item(kind='exam-branding',scope='Campus A',name='Individual Attendance Report',data=dict(header='[studentName]|[fatherName]|[rollNo]|[sectionName]|[attendance]',body='',footer='')))
        db.session.add(self.m['daily'](kind='student',person_id=self.s.id,day=date(2026,9,1),status='Absent'));db.session.commit()
        page=self.get('attendance/individual-attendance?from=2026-09&to=2026-09&person_id='+str(self.s.id));self.assertEqual(page.status_code,200);self.assertIn(b'Fictional Pupil|Fictional Father|0007|A|Absent: 1',page.data)
