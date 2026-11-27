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
        path='fees/daily-fees?group_by=account&export=csv'
        sep=self.get(path+'&from=2026-09&to=2026-09').data.decode()
        oct=self.get(path+'&from=2026-10&to=2026-10').data.decode()
        self.assertNotIn('2026-10-02,Cash,1,250,50',sep)
        self.assertIn('2026-10-02,Cash,1,250,50',oct)
        self.assertNotIn('2026-10-02,Cash,1,250,50',self.get(path+'&from=2026-10&to=2026-10&account=Bank').data.decode())

    def test_daily_collection_shows_student_totals_and_receiving_details(self):
        import csv
        from io import BytesIO, StringIO
        from openpyxl import load_workbook

        second = Student(admission_no='R3', name='Second Pupil', class_name='Class Two', status='Active')
        db.session.add(second)
        db.session.flush()
        db.session.add(self.rm['student'](student_id=self.s.id, data={
            'family_no':'F-42','campus':'Campus A','roll_no':'0007','section':'A'}))
        second_bill = self.m['bill'](student_id=second.id,month='2026-10',due=date(2026,10,10),
                                     lines=[dict(particular='Tuition',amount=100000)],paid=50000)
        db.session.add(second_bill)
        db.session.flush()
        for bill, amount, day, account, token, voided in (
            (self.bill, 15000, 2, 'Bank', 'second-installment', False),
            (second_bill, 50000, 2, 'Cash', 'other-student', False),
            (second_bill, 99000, 2, 'Cash', 'reversed-payment', True),
            (self.bill, 10000, 3, 'Cash', 'next-day', False),
        ):
            db.session.add(self.m['receipt'](student_id=bill.student_id,bill_id=bill.id,amount=amount,
                day=date(2026,10,day),account=account,token=token,voided=voided))
        db.session.commit()

        path = 'fees/daily-fees?from=2026-10-02&to=2026-10-02'
        html = self.get(path).data
        for value in (b'Fictional Pupil', b'Second Pupil', b'Fictional Father', b'F-42', b'Campus A', b'0007',
                      b'Total Fee Collected (Rs.)</span><b>900</b>', b'<tfoot>'):
            self.assertIn(value, html)
        self.assertNotIn(b'No Challan Pupil', html)

        def csv_rows(path):
            return list(csv.reader(StringIO(self.get(path+'&export=csv').data.decode('utf-8-sig'))))
        headings, first, second, total = csv_rows(path)
        self.assertEqual(headings[-3:], ['Receipts','Collected','Discount'])
        self.assertEqual(first[headings.index('Receiving Account')], 'Bank, Cash')
        self.assertEqual(first[-3:], ['2','400','50'])
        self.assertEqual(second[-3:], ['1','500','0'])
        self.assertEqual(total[-3:], ['3','900','50'])
        bank = csv_rows(path+'&account=Bank')
        self.assertEqual(len(bank), 3)
        self.assertEqual(bank[-1][-3:], ['1','150','0'])
        workbook = load_workbook(BytesIO(self.get(path+'&export=xlsx').data), data_only=True)
        self.assertEqual(list(workbook['Report'].values)[-1][-3:], (3,900,50))

    def test_bill_month_report_and_no_challan_strength(self):
        text=self.get('fees/student-fees?from=2026-09&to=2026-09&export=csv').data.decode()
        self.assertIn('Fictional Pupil',text);self.assertIn(',700,',text);self.assertIn('No Challan Pupil',text)
        self.assertIn('0,0,0,0,0,0,0,0,0,1',text)
    def test_particular_payments_not_guessed_for_legacy_mixed_bill(self):
        self.bill.lines=[dict(particular='Tuition',amount=80000),dict(particular='Books',amount=20000)];db.session.commit()
        text=self.get('fees/class-fees?from=2026-09&to=2026-09&export=csv').data.decode()
        self.assertIn('Books',text);self.assertIn('Allocation unavailable',text)
        self.assertNotRegex(text,r'(?m)(?:^|,)250(?:,|$)')
    def test_defaulter_reminder_has_only_outstanding_students(self):
        text=self.get('fees/fee-reminder?from=2026-09&to=2026-09').data.decode()
        self.assertIn('Fictional Pupil',text);self.assertNotIn('No Challan Pupil',text);self.assertRegex(text,r'(?<![\d,.])700(?![\d,.])')
        self.assertEqual(self.get('fees/defaulters?from=2026-09&to=2026-09&pending_months=2').status_code,200)
    def test_staff_attendance_report_staff_filters_color_totals_and_exports(self):
        from io import StringIO
        import csv
        clerk=Employee(employee_no='A2',name='Fictional Clerk',role='Clerk',status='Active')
        db.session.add(clerk);db.session.flush()
        for employee,department in ((self.e,'Academics'),(clerk,'Administration')):
            db.session.add(self.rm['employee'](employee_id=employee.id,data={'campus':'Campus A','department':department,'gender':'Female'}))
        for category,values in [('campus',['Campus A']),('department',['Academics','Administration']),('designation',['Subject Teacher','Clerk'])]:
            for value in values:db.session.add(self.rm['settings'](category=category,value=value,class_name=''))
        for person,day,state in [(self.e,1,'Present'),(self.e,2,'Late'),(clerk,1,'Absent'),(clerk,2,'Short Leave')]:
            db.session.add(self.m['daily'](kind='staff',person_id=person.id,day=date(2026,9,day),status=state))
        db.session.commit()
        path='attendance/staff-attendance-report?from=2026-09-01&to=2026-09-02'
        page=self.get(path+'&class_name=Old+Class&section=Z&academic_session=obsolete&group_name=old')
        self.assertEqual(page.status_code,200)
        self.assertIn(b'staff-attendance-report',page.data)
        self.assertIn(b'Attendance summary',page.data)
        for key,value in [('employees',2),('marked-days',4),('present',1),('absent',1),('late',1),('leave-days',1),('off-days',0)]:
            self.assertRegex(page.data,rb'data-attendance-status="'+key.encode()+rb'"><span>[^<]+</span><b>'+str(value).encode()+rb'</b>')
        for field in ('class_name','section','academic_session','group_name'):
            self.assertNotIn(('name="'+field+'"').encode(),page.data)
        self.assertIn(b'Active employees only',page.data)
        self.assertNotIn(b'Currently enrolled only',page.data)
        self.assertNotIn(b'Sandwich Leave',page.data)
        self.assertIn(b'Fictional Teacher',page.data)
        self.assertIn(b'Fictional Clerk',page.data)
        filtered=self.get(path+'&department=Academics&designation=Subject+Teacher')
        self.assertIn(b'Fictional Teacher',filtered.data)
        self.assertNotIn(b'Fictional Clerk',filtered.data)
        self.assertIn(b'data-attendance-status="present"><span>Present</span><b>1</b>',filtered.data)
        export=self.get(path+'&department=Academics&designation=Subject+Teacher&export=csv')
        rows=list(csv.reader(StringIO(export.data.decode('utf-8-sig'))))
        self.assertEqual(rows[0][:3],['ID','Name','Designation'])
        self.assertEqual(len(rows),2)
        self.assertEqual(rows[1][1],'Fictional Teacher')
        self.assertEqual(rows[1][-1],'2')
        self.assertEqual(self.get(path+'&export=xlsx').status_code,200)
        # Historical statuses remain available instead of silently losing a marked day.
        db.session.add(self.m['daily'](kind='staff',person_id=self.e.id,day=date(2026,9,3),status='Sandwich Leave'));db.session.commit()
        self.assertIn(b'Sandwich Leave',self.get(path.replace('to=2026-09-02','to=2026-09-03')).data)

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
        self.assertIn(b'Fictional Teacher|T1|2026-09-01|08:15 AM|Late',page.data);self.assertNotIn(b'[emp_name]',page.data)
    def test_student_attendance_branding_uses_actual_details_not_other_pupil(self):
        Item=app.extensions['school_settings_models']['item'];db.session.add(self.rm['student'](student_id=self.s.id,data={'campus':'Campus A','roll_no':'0007','section':'A'}))
        db.session.add(Item(kind='exam-branding',scope='Campus A',name='Individual Attendance Report',data=dict(header='[studentName]|[fatherName]|[rollNo]|[sectionName]|[attendance]',body='',footer='')))
        db.session.add(self.m['daily'](kind='student',person_id=self.s.id,day=date(2026,9,1),status='Absent'));db.session.commit()
        page=self.get('attendance/individual-attendance?from=2026-09&to=2026-09&person_id='+str(self.s.id));self.assertEqual(page.status_code,200);self.assertIn(b'Fictional Pupil|Fictional Father|0007|A|Absent: 1',page.data)

    def test_student_fee_sheet_month_grid_and_exports_use_saved_challan_totals(self):
        import csv,io
        suffix='?from=2026-09&to=2026-10'
        page=self.get('fees/fee-sheet'+suffix);self.assertEqual(page.status_code,200);self.assertIn(b'Sep 2026',page.data);self.assertRegex(page.data,rb'(?<![\d,.])700(?![\d,.])')
        rows=list(csv.reader(io.StringIO(self.get('fees/fee-sheet'+suffix+'&export=csv').data.decode('utf-8-sig'))))
        pupil=next(r for r in rows if 'Fictional Pupil' in r);self.assertEqual(pupil[-3:],['700','—','700'])
        rows=list(csv.reader(io.StringIO(self.get('fees/fee-sheet'+suffix+'&metric=paid&export=csv').data.decode('utf-8-sig'))));self.assertEqual(next(r for r in rows if 'Fictional Pupil' in r)[-3:],['250','—','250'])
        export=self.get('fees/fee-sheet'+suffix+'&export=xlsx');self.assertEqual(export.status_code,200);self.assertTrue(export.data.startswith(b'PK'))
        from openpyxl import load_workbook
        xrows=list(load_workbook(io.BytesIO(export.data))['Report'].values)
        xpupil=next(r for r in xrows if 'Fictional Pupil' in r);self.assertEqual(xpupil[-3:],(700,'—',700))
        only=self.get('fees/fee-sheet'+suffix+'&defaulters=1');self.assertNotIn(b'No Challan Pupil',only.data)
        for q in ['from=2025-01&to=2026-10','from=2026-09&to=2026-10&metric=bad']:
            self.assertEqual(self.get('fees/fee-sheet?'+q).status_code,422)
