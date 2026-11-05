"""Admission series, scoped allocation, reviewed blank fill and rollback."""
import hashlib,html,json,os,re,unittest
os.environ['DATABASE_URL']='sqlite:///:memory:'
from app import app,db,Student

class RollNumberTests(unittest.TestCase):
    path='/workspace/core/roll-number-series'
    def setUp(self):
        app.config.update(TESTING=True,IDENTITY_ENFORCE_IN_TESTS=False,SECRET_KEY='roll-tests')
        self.ctx=app.app_context();self.ctx.push();db.drop_all();db.create_all();self.rm=app.extensions['record_models'];self.m=app.extensions['school_settings_models']
        for cat,values in {'campus':['Campus A','Campus B'],'class_name':['One','Two'],'section':['A','B'],'group_name':['General'],'academic_session':['2026-27'],'fee_plan':['Plan A']}.items():
            for value in values:db.session.add(self.rm['settings'](category=cat,value=value,class_name=''))
        db.session.commit();self.c=app.test_client();self.c.get(self.path)
        with self.c.session_transaction() as s:self.csrf=s['record_csrf']
    def tearDown(self):db.session.remove();db.drop_all();self.ctx.pop()
    def post(self,**values):return self.c.post(self.path,data={'_csrf':self.csrf,**values})
    def series(self,scope=('','',''),start='1',prefix='',digits='0',version='0'):
        k=hashlib.sha256(json.dumps(list(scope),sort_keys=True,default=str,separators=(',',':')).encode()).hexdigest()
        self.assertEqual(self.post(action='series',series_key=k,**{'start_'+k:start,'prefix_'+k:prefix,'digits_'+k:digits,'version_'+k:version}).status_code,302)
        return k
    def enable(self,**changes):
        row=db.session.get(self.m['setting'],'roll-numbers');data=dict(action='settings',version=str(row.version if row else 0),enabled='1',skip='1');data.update(changes)
        self.assertEqual(self.post(**data).status_code,302)
    def pupil(self,roll='',campus='Campus A',cls='One',section='A',status='Active'):
        p=Student(admission_no='TEST-'+str(Student.query.count()),name='Fictional Pupil',class_name=cls,status=status);db.session.add(p);db.session.flush();d=self.rm['student'](student_id=p.id,data=dict(roll_no=roll,campus=campus,class_name=cls,section=section,status=status));db.session.add(d);db.session.commit();return p,d
    def allocate(self,**changes):
        data=dict(campus='Campus A',class_name='One',section='A',status='Active',roll_no='');data.update(changes)
        app.extensions['admission_capacity']['lock']();app.extensions['roll_number_helpers']['assign'](data);db.session.commit();return data['roll_no']
    def test_get_is_read_only_and_automatic_assignment_defaults_off(self):
        self.series();self.assertEqual(self.allocate(),'');self.assertEqual(self.m['setting'].query.count(),0)
        self.assertEqual(self.c.get(self.path).status_code,200)
    def test_most_specific_series_and_disabled_fallback_prefix_padding(self):
        self.series(start='10',prefix='S-',digits='3');self.series(('Campus A','',''),start='20');self.series(('Campus A','One',''),start='30');self.series(('Campus A','One','A'),start='40');self.enable()
        self.assertEqual(self.allocate(),'40');self.assertEqual(self.allocate(section='B'),'30');self.assertEqual(self.allocate(class_name='Two'),'20');self.assertEqual(self.allocate(campus='Campus B'),'S-010')
        self.series(('Campus A','One','A'),start='',version='2');self.assertEqual(self.allocate(),'31')
    def test_duplicate_checks_include_inactive_and_numeric_leading_zeros(self):
        self.pupil('P-001',status='Inactive');self.pupil('P-2');self.pupil('X-3');self.series(start='1',prefix='P-',digits='3');self.enable();self.assertEqual(self.allocate(),'P-003');self.assertEqual(self.allocate(),'P-004')
    def test_typed_roll_and_queries_are_preserved_and_unsaved_allocations_rollback(self):
        self.series(start='5');self.enable();self.assertEqual(self.allocate(roll_no='MANUAL'),'MANUAL');self.assertEqual(self.allocate(status='Admission Query'),'')
        data=dict(campus='Campus A',class_name='One',section='A',status='Active',roll_no='');app.extensions['roll_number_helpers']['assign'](data);self.assertEqual(data['roll_no'],'5');db.session.rollback();self.assertEqual(self.allocate(),'5')
    def test_fill_blanks_requires_review_and_rejects_stale_replayed_or_foreign_form(self):
        pupil,blank=self.pupil(None);self.pupil('KEEP');k=self.series(start='9');self.enable()
        page=self.c.get(self.path+'?fill='+k);token=html.unescape(re.search(rb'name="review" value="([^"]+)"',page.data)[1].decode());self.assertIsNone(blank.data['roll_no'])
        other=app.test_client();other.get(self.path)
        with other.session_transaction() as s:csrf=s['record_csrf']
        self.assertEqual(other.post(self.path,data={'_csrf':csrf,'action':'fill','review':token}).status_code,422)
        self.assertEqual(self.post(action='fill',review=token).status_code,302);self.assertEqual(blank.data['roll_no'],'9');self.assertEqual(self.post(action='fill',review=token).status_code,422)
        self.assertEqual([d.data['roll_no'] for d in self.rm['student'].query.order_by(self.rm['student'].student_id).all()],['9','KEEP'])
    def test_config_save_does_not_reset_consumed_counter_and_validation_is_atomic(self):
        self.series(start='1');self.enable();self.assertEqual(self.allocate(),'1');row=self.m['item'].query.filter_by(kind='roll-series').one();self.series(start='1',version=str(row.version));self.assertEqual(self.allocate(),'2')
        before=row.data.copy();k=row.name
        for v in ['-1','1.5','x','9999999999999']:
            self.assertEqual(self.post(action='series',series_key=k,**{'start_'+k:v,'digits_'+k:'0','version_'+k:str(row.version)}).status_code,422);self.assertEqual(row.data,before)
        self.assertEqual(self.c.post(self.path,data={'action':'settings'}).status_code,400)
    def test_single_admission_assigns_but_edit_does_not_renumber(self):
        self.series(start='7');self.enable()
        data=dict(_csrf=self.csrf,name='Fictional admission',father='Test guardian',father_cnic='TEST',phone='000',family_mode='new',gender='Female',guardian_relation='Father',admission_date='2026-11-05',campus='Campus A',class_name='One',section='A',group_name='General',academic_session='2026-27',fee_plan='Plan A',status='Active',save_action='view')
        r=self.c.post('/records/student/new',data=data);self.assertEqual(r.status_code,302,r.data[:500]);detail=self.rm['student'].query.one();self.assertEqual(detail.data['roll_no'],'7')
        data.update(family_mode='existing',family_id=str(detail.family_id),roll_no='7');sid=detail.student_id;self.assertEqual(self.c.post(f'/records/student/{sid}/edit',data=data).status_code,302);self.assertEqual(self.allocate(),'8')
    def test_import_allocator_is_opt_in_and_preview_consumes_no_counter(self):
        self.series(start='100');self.enable();cls=app.extensions['roll_number_helpers']['allocator'];data=dict(campus='Campus A',class_name='One',section='A',status='Active',roll_no='');a=cls(imports=True);a.allocate(data);self.assertEqual(data['roll_no'],'')
        self.enable(imports='1');a=cls(imports=True)
        for expected in ['100','101']:
            data=dict(campus='Campus A',class_name='One',section='A',status='Active',roll_no='');a.allocate(data);self.assertEqual(data['roll_no'],expected)
        self.assertEqual(self.allocate(),'100')

    def test_concurrent_new_admissions_receive_distinct_rolls(self):
        import tempfile,threading
        from concurrent.futures import ThreadPoolExecutor
        from flask import g,request
        from sqlalchemy import create_engine,select
        self.series(start='1');self.enable();db.session.remove()
        with tempfile.TemporaryDirectory() as directory:
            engine=create_engine('sqlite:///'+directory+'/rolls.db',connect_args={'timeout':20});tables=app.extensions['identity_helpers']['workspace_tables']();db.metadata.create_all(engine,tables=tables)
            with db.engine.connect() as source,engine.begin() as target:
                for table in tables:
                    rows=[dict(r) for r in source.execute(select(table)).mappings().all()]
                    if rows:target.execute(table.insert(),rows)
            barrier=threading.Barrier(2)
            def bind():
                if request.endpoint=='records.new_record':g.institute_engine=engine;barrier.wait(timeout=10)
            app.before_request_funcs.setdefault(None,[]).append(bind)
            try:
                def save(i):
                    c=app.test_client()
                    with c.session_transaction() as s:s['record_csrf']='roll-concurrent'
                    return c.post('/records/student/new',data=dict(_csrf='roll-concurrent',name='Fictional '+str(i),father='Guardian',father_cnic='TEST',phone='000',family_mode='new',gender='Female',guardian_relation='Father',admission_date='2026-11-05',campus='Campus A',class_name='One',section='A',group_name='General',academic_session='2026-27',fee_plan='Plan A',status='Active')).status_code
                with ThreadPoolExecutor(max_workers=2) as pool:statuses=list(pool.map(save,range(2)))
                self.assertEqual(statuses,[302,302])
                with engine.connect() as connection:values=connection.execute(select(self.rm['student'].__table__.c.data)).scalars().all()
                self.assertEqual(sorted(d['roll_no'] for d in values),['1','2'])
            finally:app.before_request_funcs[None].remove(bind);db.session.remove();g.pop('institute_engine',None);engine.dispose()
