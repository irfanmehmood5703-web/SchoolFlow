"""Imports validate the full file, retain fee rules and protect downstream work."""
import csv,html,io,os,re,unittest,copy
from datetime import date
os.environ['DATABASE_URL']='sqlite:///:memory:'
from app import app,db,Student
from record_schema import DEMO_CHOICES
from openpyxl import Workbook,load_workbook

class StudentImportTests(unittest.TestCase):
    path='/workspace/core/institute/student-import'
    def setUp(self):
        app.config.update(TESTING=True,IDENTITY_ENFORCE_IN_TESTS=False,SECRET_KEY='import-test')
        self.ctx=app.app_context();self.ctx.push();db.drop_all();db.create_all();self.rm=app.extensions['record_models'];self.P=app.extensions['student_fee_plan_model'];self.Batch=app.extensions['student_import_model'];self.ops=app.extensions['ops_models']
        for category,values in DEMO_CHOICES.items():
            for value in values:db.session.add(self.rm['settings'](category=category,value=value,class_name=''))
        Schedule=app.extensions['fee_setup_models']['schedule'];self.schedule=Schedule(name=DEMO_CHOICES['fee_plan'][0],campus=DEMO_CHOICES['campus'][0],class_name=DEMO_CHOICES['class_name'][0],description='',due_day=31,lines=[dict(key='Tuition Fee',amount=350000,minimum=300000,maximum=500000,first_only=False,month_override=True,months=[9,10,11])]);db.session.add(self.schedule);db.session.commit()
        self.c=app.test_client();self.c.get(self.path)
        with self.c.session_transaction() as sess:self.csrf=sess['record_csrf']
    def tearDown(self):db.session.remove();db.drop_all();self.ctx.pop()
    def rows(self,count=1):return [dict(name='Fictional '+str(i),gender='M',father='Fictional Father',father_cnic='TEST-CNIC',phone='00000000000',admission_no='IMP-TEST-'+str(i)) for i in range(count)]
    def upload(self,rows=None,headers=None,filename='students.csv',content=None):
        rows=rows or self.rows();headers=headers or list(dict.fromkeys(k for row in rows for k in row))
        if content is None:
            stream=io.StringIO();writer=csv.writer(stream);writer.writerow(headers)
            for row in rows:writer.writerow([row.get(h,'') for h in headers])
            content=stream.getvalue().encode()
        r=self.c.post(self.path+'/upload',data={'_csrf':self.csrf,'file':(io.BytesIO(content),filename)},content_type='multipart/form-data')
        self.assertEqual(r.status_code,302,r.data[:400]);return self.Batch.query.order_by(self.Batch.created.desc()).first()
    def review(self,batch,page=1,**changes):
        data=dict(_csrf=self.csrf,action='review',version=str(batch.version),page=str(page))
        data.update({'map_'+str(i):key for i,key in enumerate(batch.data['mapping'])});data.update(changes)
        r=self.c.post(self.path+'/'+batch.id,data=data)
        self.assertEqual(r.status_code,302,r.data[:400]);return self.c.get(r.location)
    def confirmation(self,batch):
        page=self.c.get(self.path+'/'+batch.id);self.assertEqual(page.status_code,200)
        match=re.search(rb'name="confirmation" value="([^"]+)"',page.data);self.assertIsNotNone(match,page.data[-1500:]);return html.unescape(match[1].decode())
    def apply(self,batch,confirmation=None):return self.c.post(self.path+'/'+batch.id+'/apply',data=dict(_csrf=self.csrf,confirmation=confirmation or self.confirmation(batch)))
    def undo(self,batch):return self.c.post(self.path+'/'+batch.id+'/undo',data=dict(_csrf=self.csrf,version=str(batch.version)))
    def test_template_is_private_download_uses_configured_names_and_text_cells(self):
        r=self.c.get(self.path+'/template.xlsx');self.assertEqual(r.status_code,200)
        wb=load_workbook(io.BytesIO(r.data),data_only=False);headers=[c.value for c in wb['Students'][1]];self.assertIn('Student Name',headers);self.assertIn('Actual — Tuition Fee',headers)
        self.assertIn('Demo Campus',str(list(wb['Instructions'].values)));wb.close();self.assertEqual(Student.query.count(),0)
    def test_upload_mapping_and_review_never_create_students_or_fee_plans(self):
        batch=self.upload();self.assertEqual(Student.query.count(),0);self.assertEqual(self.P.query.count(),0)
        page=self.review(batch);self.assertIn(b'No students or fees have been imported',page.data);self.assertIsNotNone(self.confirmation(batch));self.assertEqual(Student.query.count(),0)
    def test_import_saves_real_students_family_and_scoped_fee_snapshots_no_messages(self):
        rows=self.rows(2)
        for row in rows:row.update(family_no='F-SIBLINGS',**{'discount::Tuition Fee':'1500','arrears::Tuition Fee':'100','percentage':'10','effective':'2026-11'})
        batch=self.upload(rows);self.review(batch);self.assertEqual(self.apply(batch).status_code,302)
        self.assertEqual(Student.query.count(),2);self.assertEqual(self.rm['family'].query.count(),1);self.assertEqual(self.P.query.count(),2)
        line=self.P.query.first().data['lines'][1];self.assertEqual((line['actual'],line['discount'],line['net'],line['arrears']),(370000,150000,220000,10000))
        self.assertEqual(self.P.query.first().data['due_day'],31);self.assertEqual(line['fee_rules']['months'],[9,10,11]);self.assertEqual(self.rm['communication'].query.count(),0);self.assertEqual(self.ops['bill'].query.count(),0)
    def test_replay_cannot_duplicate_import(self):
        batch=self.upload();self.review(batch);token=self.confirmation(batch);self.assertEqual(self.apply(batch,token).status_code,302);self.assertEqual(self.apply(batch,token).status_code,422);self.assertEqual(Student.query.count(),1)
    def test_duplicate_admissions_bad_rows_and_family_conflicts_block_entire_batch(self):
        rows=self.rows(2);rows[1]['admission_no']=rows[0]['admission_no'];rows[1]['gender']='Unknown'
        batch=self.upload(rows);page=self.review(batch);self.assertIn(b'Duplicate admission',page.data);self.assertNotIn(b'name="confirmation"',page.data);self.assertEqual(Student.query.count(),0)
        self.assertEqual(self.c.post(self.path+'/'+batch.id+'/apply',data=dict(_csrf=self.csrf,confirmation='invalid')).status_code,422)
        rows=self.rows(2);rows[0]['family_no']=rows[1]['family_no']='F-CONFLICT';rows[1]['father']='Other father';batch=self.upload(rows);page=self.review(batch);self.assertIn(b'conflicting father',page.data)
    def test_mapping_aliases_ignore_extra_columns_and_fix_rows(self):
        rows=[{'Pupil':'Fictional <script>Student</script>','Sex':'bad','Father Name':'Fictional Father','father_cnic':'TEST','Mobile':'000','Unrelated':'ignored'}];batch=self.upload(rows)
        mapping=dict(batch.data['mapping'] and {'map_'+str(i):v for i,v in enumerate(batch.data['mapping'])});mapping.update(map_0='name',map_1='gender')
        page=self.review(batch,**mapping,cell_0_1='F');self.assertNotIn(b'<script>Student',page.data);self.assertIn(b'&lt;script&gt;',page.data);self.confirmation(batch)
        self.assertEqual(self.apply(batch).status_code,302);self.assertEqual(Student.query.one().name,'Fictional <script>Student</script>')
    def test_bad_fee_amount_bounds_discount_nan_and_missing_schedule(self):
        for changes in [{'amount::Tuition Fee':'2000'},{'amount::Tuition Fee':'6000'},{'discount::Tuition Fee':'3501'},{'arrears::Tuition Fee':'NaN'}]:
            row=self.rows()[0];row.update(changes);batch=self.upload([row]);page=self.review(batch);self.assertNotIn(b'name="confirmation"',page.data);self.assertEqual(Student.query.count(),0)
        self.schedule.name='Changed';db.session.commit();batch=self.upload();page=self.review(batch);self.assertIn(b'Configure a fee schedule',page.data)
    def test_stale_settings_after_review_require_new_confirmation(self):
        batch=self.upload();self.review(batch);token=self.confirmation(batch)
        self.schedule.lines=[dict(self.schedule.lines[0],amount=400000)];db.session.commit()
        self.assertEqual(self.apply(batch,token).status_code,422);self.assertEqual(Student.query.count(),0)
        self.review(batch);self.assertEqual(self.apply(batch).status_code,302);self.assertEqual(self.P.query.one().data['lines'][1]['actual'],400000)
    def test_capacity_is_previewed_for_the_batch_and_full_students_wait(self):
        Cap=app.extensions['admission_capacity_models']['capacity'];db.session.add(Cap(campus='Demo Campus',class_name='Demo Class',academic_session=DEMO_CHOICES['academic_session'][0],seats=1));db.session.commit()
        batch=self.upload(self.rows(2));page=self.review(batch);self.assertIn(b'Waiting',page.data);self.assertEqual(self.apply(batch).status_code,302)
        self.assertEqual([s.status for s in Student.query.order_by(Student.id)],['Active','Waiting'])
    def test_undo_unused_batch_and_keep_history(self):
        batch=self.upload(self.rows(2));self.review(batch);self.apply(batch);self.assertEqual(self.undo(batch).status_code,302)
        self.assertEqual(Student.query.count(),0);self.assertEqual(self.P.query.count(),0);self.assertEqual(self.rm['family'].query.count(),0);self.assertEqual(batch.status,'Undone')
        self.assertEqual(self.undo(batch).status_code,422);self.assertEqual(self.ops['audit'].query.filter_by(action='Undo student import').count(),1)
    def test_undo_blocks_after_student_plan_financial_or_attendance_changes(self):
        batch=self.upload();self.review(batch);self.apply(batch);s=Student.query.one();original=s.name;s.name='Changed';db.session.commit();self.assertEqual(self.undo(batch).status_code,422)
        s.name=original;db.session.commit();bill=self.ops['bill'](student_id=s.id,month='2026-11',due=date(2026,11,10),lines=[dict(particular='Tuition Fee',amount=350000)]);db.session.add(bill);db.session.commit();self.assertEqual(self.undo(batch).status_code,422)
        db.session.delete(bill);db.session.commit();db.session.add(self.ops['daily'](kind='student',person_id=s.id,day=date(2026,11,1),status='Present'));db.session.commit();self.assertEqual(self.undo(batch).status_code,422)
    def test_existing_family_is_linked_without_rewriting_it_and_conflicts_reported(self):
        family=self.rm['family'](number='EXISTING',data=dict(father='Fictional Father',father_cnic='TEST-CNIC',phone='00000000000'));db.session.add(family);db.session.commit();before=copy.deepcopy(family.data)
        rows=self.rows();rows[0]['family_no']='EXISTING';batch=self.upload(rows);self.review(batch);self.assertEqual(self.apply(batch).status_code,302);self.assertEqual(self.rm['family'].query.count(),1);self.assertEqual(family.data,before)
    def test_xlsx_date_cells_and_formula_rejection(self):
        wb=Workbook();ws=wb.active;row=self.rows()[0];row['birth_date']=date(2018,1,12);ws.append(list(row));ws.append(list(row.values()));out=io.BytesIO();wb.save(out)
        batch=self.upload(content=out.getvalue(),filename='students.xlsx');self.review(batch);self.confirmation(batch)
        ws['A2']='=1+1';out=io.BytesIO();wb.save(out);r=self.c.post(self.path+'/upload',data={'_csrf':self.csrf,'file':(io.BytesIO(out.getvalue()),'formula.xlsx')});self.assertEqual(r.status_code,422)
    def test_upload_limits_extensions_csrf_and_other_session_privacy(self):
        self.assertEqual(self.c.post(self.path+'/upload',data={}).status_code,400)
        for content,name in [(b'bad','s.xlsm'),(b'','s.csv'),(b'bad','s.xlsx'),(b'A\n','s.csv'),(b'\xff','s.csv')]:
            self.assertEqual(self.c.post(self.path+'/upload',data={'_csrf':self.csrf,'file':(io.BytesIO(content),name)}).status_code,422)
        batch=self.upload();other=app.test_client();other.get(self.path);self.assertEqual(other.get(self.path+'/'+batch.id).status_code,404)
        self.assertNotIn(batch.id.encode(),other.get(self.path).data)
    def test_draft_versions_cancel_and_invalid_duplicate_mappings(self):
        batch=self.upload();data=dict(_csrf=self.csrf,action='review',version=str(batch.version),map_0='name',map_1='name')
        self.assertEqual(self.c.post(self.path+'/'+batch.id,data=data).status_code,422)
        self.assertEqual(self.c.post(self.path+'/'+batch.id,data=dict(_csrf=self.csrf,action='review',version='99')).status_code,422)
        self.assertEqual(self.c.post(self.path+'/'+batch.id,data=dict(_csrf=self.csrf,action='cancel',version=str(batch.version))).status_code,302);self.assertEqual(batch.status,'Cancelled');self.assertEqual(Student.query.count(),0)

    def test_large_preview_queries_are_batched_and_original_blank_row_numbers_retained(self):
        from sqlalchemy import event
        batch=self.upload(self.rows(100));queries=[]
        def capture(conn,cursor,statement,parameters,context,executemany):
            if statement.lstrip().lower().startswith('select'):queries.append(statement)
        db.session.remove();batch=db.session.get(self.Batch,batch.id);event.listen(db.engine,'before_cursor_execute',capture)
        try:page=self.c.get(self.path+'/'+batch.id)
        finally:event.remove(db.engine,'before_cursor_execute',capture)
        self.assertEqual(page.status_code,200);self.assertLessEqual(len(queries),25,queries)
        batch=self.upload(content=b'name,gender,father,father_cnic,phone\n,,,,\nFictional,M,Father,TEST,000\n')
        self.assertEqual(batch.data['row_numbers'],[3]);self.assertIn(b'<th>3</th>',self.c.get(self.path+'/'+batch.id).data)

    def test_template_never_exports_configured_names_as_excel_formulas(self):
        self.rm['settings'].query.filter_by(category='campus').delete();db.session.add(self.rm['settings'](category='campus',value='=HYPERLINK("example.invalid")',class_name=''));db.session.commit()
        response=self.c.get(self.path+'/template.xlsx');wb=load_workbook(io.BytesIO(response.data),data_only=False)
        self.assertFalse(any(cell.data_type=='f' for sheet in wb for row in sheet for cell in row));wb.close()

    def test_undo_blocks_uploaded_documents_and_later_edit_events(self):
        batch=self.upload();self.review(batch);self.apply(batch);student=Student.query.one()
        file=self.rm['file'](owner_kind='student',owner_id=student.id,title='Doc',filename='test.txt',mime='text/plain',photo=False,content=b'private',sha256='x');db.session.add(file);db.session.commit();self.assertEqual(self.undo(batch).status_code,422)
        db.session.delete(file);db.session.add(self.rm['event'](owner_kind='student',owner_id=student.id,action='Updated'));db.session.commit();self.assertEqual(self.undo(batch).status_code,422)

    def test_concurrent_confirmation_imports_the_batch_once(self):
        import tempfile,threading
        from concurrent.futures import ThreadPoolExecutor
        from flask import g,request
        from sqlalchemy import create_engine,select,func
        settings=[dict(category=r.category,value=r.value,class_name=r.class_name) for r in self.rm['settings'].query.all()]
        schedule=dict(name=self.schedule.name,campus=self.schedule.campus,class_name=self.schedule.class_name,due_day=self.schedule.due_day,description='',lines=self.schedule.lines)
        with tempfile.TemporaryDirectory() as directory:
            engine=create_engine('sqlite:///'+directory+'/import.db',connect_args={'timeout':20});db.metadata.create_all(engine,tables=app.extensions['identity_helpers']['workspace_tables']())
            with engine.begin() as connection:
                connection.execute(self.rm['settings'].__table__.insert(),settings);connection.execute(app.extensions['fee_setup_models']['schedule'].__table__.insert().values(**schedule))
            barrier=threading.Barrier(2)
            def bind_test_database():
                if request.blueprint=='student_import':
                    g.institute_engine=engine
                    if request.endpoint=='student_import.apply':barrier.wait(timeout=10)
            app.before_request_funcs.setdefault(None,[]).append(bind_test_database)
            def client():
                c=app.test_client()
                with c.session_transaction() as sess:sess['record_csrf']='import-concurrent'
                return c
            try:
                c=client();source=b'name,gender,father,father_cnic,phone\nConcurrent Pupil,M,Father,TEST,000\n'
                uploaded=c.post(self.path+'/upload',data={'_csrf':'import-concurrent','file':(io.BytesIO(source),'students.csv')});self.assertEqual(uploaded.status_code,302);url=uploaded.location
                token=url.split('/')[-1]
                with engine.connect() as connection:stage=connection.execute(select(self.Batch.__table__).where(self.Batch.__table__.c.id==token)).mappings().one()
                data=dict(_csrf='import-concurrent',action='review',version=str(stage['version']));data.update({'map_'+str(i):v for i,v in enumerate(stage['data']['mapping'])})
                self.assertEqual(c.post(url,data=data).status_code,302);page=c.get(url)
                confirmation=html.unescape(re.search(rb'name="confirmation" value="([^"]+)"',page.data)[1].decode())
                def apply(_):return client().post(url+'/apply',data=dict(_csrf='import-concurrent',confirmation=confirmation)).status_code
                with ThreadPoolExecutor(max_workers=2) as pool:statuses=list(pool.map(apply,range(2)))
                self.assertEqual(sorted(statuses),[302,422])
                with engine.connect() as connection:self.assertEqual(connection.scalar(select(func.count()).select_from(Student.__table__)),1)
            finally:
                app.before_request_funcs[None].remove(bind_test_database);db.session.remove();g.pop('institute_engine',None);engine.dispose()

    def roll_setup(self):
        Setting=app.extensions['school_settings_models']['setting'];Item=app.extensions['school_settings_models']['item']
        db.session.add(Setting(key='roll-numbers',data=dict(enabled=True,skip=True,imports=True)))
        db.session.add(Item(kind='roll-series',scope='',name='test-global',data=dict(class_name='',section='',prefix='R-',digits=3,start=1,next=1)));db.session.commit()
    def test_import_roll_preview_reserves_later_typed_roll_and_apply_consumes_once(self):
        self.roll_setup();rows=self.rows(2);rows[1]['roll_no']='R-001';batch=self.upload(rows);self.review(batch);token=self.confirmation(batch)
        Item=app.extensions['school_settings_models']['item'];series=Item.query.filter_by(kind='roll-series').one();self.assertEqual(series.data['next'],1)
        self.assertEqual(self.apply(batch,token).status_code,302)
        details=self.rm['student'].query.order_by(self.rm['student'].student_id).all();self.assertEqual([r.data['roll_no'] for r in details],['R-002','R-001']);self.assertEqual(series.data['next'],3)
        self.assertEqual(self.apply(batch,token).status_code,422);self.assertEqual(series.data['next'],3)
    def test_changed_roll_controls_invalidate_reviewed_import(self):
        self.roll_setup();batch=self.upload();self.review(batch);token=self.confirmation(batch)
        Setting=app.extensions['school_settings_models']['setting'];row=db.session.get(Setting,'roll-numbers');row.data={**row.data,'imports':False};db.session.commit()
        self.assertEqual(self.apply(batch,token).status_code,422);self.assertEqual(Student.query.count(),0)
