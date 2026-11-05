"""Tenant-scoped CSV/XLSX mapping, correction, atomic import and guarded undo."""
import copy,csv,hashlib,hmac,io,json,re,secrets,zipfile
from datetime import date,datetime,timezone
from zoneinfo import ZoneInfo
from flask import Blueprint,abort,flash,g,redirect,render_template,request,send_file,session,url_for
from itsdangerous import BadData,URLSafeTimedSerializer
from openpyxl import Workbook,load_workbook
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import StaleDataError
from werkzeug.datastructures import MultiDict
from operations import money
from record_schema import STUDENT_SECTIONS,FAMILY_KEYS
from student_fee_plans import fee_percentage,increment_lines

MAX_ROWS=200
MAX_COLUMNS=160


def configure_student_import(app,db,Student):
    bp=Blueprint('student_import',__name__,url_prefix='/workspace/core/institute/student-import')
    rm=app.extensions['record_models'];P=app.extensions['student_fee_plan_model'];ops=app.extensions['ops_models'];Audit=ops['audit'];Family=rm['family'];Details=rm['student']
    class StudentImportBatch(db.Model):
        id=db.Column(db.String(32),primary_key=True)
        owner=db.Column(db.String(100),nullable=False,index=True)
        status=db.Column(db.String(20),nullable=False,default='Draft')
        data=db.Column(db.JSON,nullable=False)
        created=db.Column(db.DateTime,nullable=False,default=lambda:datetime.now(timezone.utc))
        version=db.Column(db.Integer,nullable=False,default=1)
        __mapper_args__={'version_id_col':version}
    app.extensions['student_import_model']=StudentImportBatch
    def today():return datetime.now(ZoneInfo('Asia/Karachi')).date().isoformat()
    def owner():return 'owner:'+str(session['owner_id']) if session.get('owner_id') else 'demo:'+hashlib.sha256(session.get('record_csrf','').encode()).hexdigest()
    def signer():return URLSafeTimedSerializer(app.config['SECRET_KEY'],salt='schoolflow-student-import-v1')
    def actor():return dict(owner=owner(),scope=(getattr(g,'school_identity',None) or {}).get('scope'),csrf=session.get('record_csrf'))
    def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=True).encode()).hexdigest()
    def batch_for(token):
        batch=db.get_or_404(StudentImportBatch,token)
        if batch.owner!=owner():abort(404)
        return batch
    def commit():
        try:db.session.commit()
        except (IntegrityError,StaleDataError):db.session.rollback();raise ValueError('A record changed. Review the complete batch again; no partial import was saved.')
    @bp.before_request
    def protect():
        request.max_content_length=8*1024*1024
        request.max_form_memory_size=6*1024*1024
        if request.method=='POST':
            token=request.form.get('_csrf','')
            if not token or not hmac.compare_digest(token,session.get('record_csrf','')):abort(400,'Reload this form.')
            app.extensions['admission_capacity']['lock']()
    @bp.errorhandler(ValueError)
    def invalid(error):
        db.session.rollback();return render_template('operation_error.html',title='Check student import',error=str(error)),422
    @bp.errorhandler(IntegrityError)
    @bp.errorhandler(StaleDataError)
    def conflict(error):
        db.session.rollback();return render_template('operation_error.html',title='Check student import',error='A record changed. Review again; no partial import was saved.'),422

    def columns():
        fields={f['key']:f['label'] for _,fs in STUDENT_SECTIONS for f in fs if f['key'] not in ('family_mode','family_id')}
        fields.update(effective='Fee effective month',percentage='Fee increment percentage',concession_reason='Fee concession reason')
        for h in app.extensions['fee_setup_helpers']['heads']():
            for key,title in [('amount','Actual'),('discount','Discount'),('arrears','Opening arrears')]:fields[key+'::'+h['key']]=title+' — '+h['label']
        return fields
    def normalized(value):return re.sub(r'[^a-z0-9]','',value.casefold())
    def mapping_for(headers,fields):
        aliases={normalized(v):k for k,v in fields.items()};aliases.update({normalized(k):k for k in fields})
        aliases.update({'studentname':'name','student':'name','dob':'birth_date','fathername':'father','fathermobile':'phone','mobile':'phone','class':'class_name','group':'group_name','session':'academic_session','feeplan':'fee_plan','family':'family_no','wef':'effective','admissionnumber':'admission_no'})
        result=[];used=set()
        for title in headers:
            key=aliases.get(normalized(title),'')
            if key in used:key=''
            result.append(key);used.add(key)
        return result
    def read_upload(upload):
        content=upload.read(5*1024*1024+1)
        if not content or len(content)>5*1024*1024:raise ValueError('Upload a non-empty CSV/XLSX up to 5 MB.')
        filename=upload.filename.lower()
        if filename.endswith('.xlsx'):
            try:
                with zipfile.ZipFile(io.BytesIO(content)) as archive:
                    if len(archive.infolist())>1000 or sum(x.file_size for x in archive.infolist())>30*1024*1024:raise ValueError('Workbook is too large after decompression.')
                workbook=load_workbook(io.BytesIO(content),read_only=True,data_only=False,keep_links=False)
                try:
                    sheet=workbook.active
                    if sheet.max_row>MAX_ROWS+1 or sheet.max_column>MAX_COLUMNS:raise ValueError('Use at most 200 student rows and 160 columns per upload.')
                    rows=[]
                    for row in sheet.iter_rows():
                        values=[]
                        for cell in row:
                            if cell.data_type=='f':raise ValueError('Replace Excel formulas with values before uploading.')
                            v=cell.value
                            if isinstance(v,(date,datetime)):v=v.date().isoformat() if isinstance(v,datetime) else v.isoformat()
                            values.append('' if v is None else str(v).strip())
                        rows.append(values)
                finally:workbook.close()
            except ValueError:raise
            except Exception:raise ValueError('Choose a readable .xlsx workbook without encryption.')
        elif filename.endswith('.csv'):
            try:
                text=content.decode('utf-8-sig');reader=csv.reader(io.StringIO(text));rows=[]
                for row in reader:
                    if len(row)>MAX_COLUMNS or len(rows)>MAX_ROWS:raise ValueError('Use at most 200 student rows and 160 columns.')
                    rows.append([v.strip() for v in row])
            except (UnicodeError,csv.Error):raise ValueError('Use UTF-8 CSV with a header row, or an .xlsx workbook.')
        else:raise ValueError('Use a CSV or XLSX file; macros and legacy XLS are not accepted.')
        if len(rows)<2 or not rows[0] or not any(any(v for v in r) for r in rows[1:]):raise ValueError('Include a header row and at least one student row.')
        headers=rows[0];width=len(headers)
        if any(len(r)>width for r in rows[1:]):raise ValueError('A data row has more columns than the header.')
        indexed=[(i+2,r) for i,r in enumerate(rows[1:]) if any(r)]
        positions=[i for i,r in indexed];rows=[r+['']*(width-len(r)) for i,r in indexed]
        if len(rows)>MAX_ROWS or any(len(v)>5000 for r in rows for v in r) or any(len(v)>160 for v in headers):raise ValueError('Too many rows or an overlong cell/header. Correct the sheet before uploading.')
        return headers,rows,positions
    @bp.get('')
    def index():return render_template('student_import.html',title='Student Excel / CSV import',batches=StudentImportBatch.query.filter_by(owner=owner()).order_by(StudentImportBatch.created.desc()).limit(30).all())
    @bp.get('/template.xlsx')
    def template():
        wb=Workbook();sheet=wb.active;sheet.title='Students';fields=columns();sheet.append(list(fields.values()));sheet.freeze_panes='A2'
        guide=wb.create_sheet('Instructions');guide.append(['SchoolFlow student import: enter plain configured names, not IDs.']);guide.append(['Dates: YYYY-MM-DD. Gender: M/F/Other. Blank fees use the scoped schedule.']);guide.append(['Use text cells for phones/CNICs to preserve leading zeros; separate subjects with |.']);guide.append(['Required fields match Add Student. No photos, formulas or external messages are imported.']);guide.append(['Blank effective month/admission date use the upload date. Blank increments/discounts/arrears use zero.'])
        for category in ('campus','class_name','section','group_name','academic_session','fee_plan'):
            guide.append([category]+[x[0] for x in app.extensions['record_helpers']['choices']().get(category,[])])
        for ws in wb.worksheets:
            for row in ws:
                for cell in row:
                    if isinstance(cell.value,str):cell.data_type='s'
        output=io.BytesIO();wb.save(output);output.seek(0)
        return send_file(output,mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',as_attachment=True,download_name='schoolflow-student-import.xlsx')
    @bp.post('/upload')
    def upload():
        file=request.files.get('file')
        if not file or not file.filename:raise ValueError('Choose a student sheet.')
        headers,rows,positions=read_upload(file);token=secrets.token_hex(16)
        batch=StudentImportBatch(id=token,owner=owner(),data=dict(headers=headers,rows=rows,row_numbers=positions,mapping=mapping_for(headers,columns()),default_date=today(),ready=False,hash=''))
        db.session.add(batch);commit();return redirect(url_for('student_import.review',token=token))
    def prepare(batch):
        roll_allocator=app.extensions['roll_number_helpers']['allocator'](imports=True)
        request.roll_import_allocator=roll_allocator
        fields=columns();mapping=batch.data['mapping'];raw=batch.data['rows'];errors={};prepared=[];choices=app.extensions['record_helpers']['choices']();canonical={cat:{v[0].casefold():v[0] for v in values} for cat,values in choices.items()}
        families={f.number:f for f in Family.query.all()};family_values={};mapped=[]
        known=dict(admissions={r[0] for r in db.session.query(Student.admission_no).all()},families={f.id:f for f in families.values()},family_numbers=set(families))
        Schedule=app.extensions['fee_setup_models']['schedule'];schedules={(s.campus,s.class_name,s.name):s for s in Schedule.query.all()}
        for i,row in enumerate(raw):
            data={key:row[j].strip() for j,key in enumerate(mapping) if key}
            for key in ('gender','status'):
                value=data.get(key,'');data[key]={'m':'Male','f':'Female','o':'Other','active':'Active','currentlyenrolled':'Active'}.get(normalized(value),value)
            for _,fs in STUDENT_SECTIONS:
                for f in fs:
                    key=f['key'];v=data.get(key,'')
                    if v and f['category']:data[key]=canonical.get(f['category'],{}).get(v.casefold(),v)
            data.setdefault('family_no','');number=data['family_no']
            if number:
                values=family_values.setdefault(number,dict(families[number].data) if number in families else {})
                for key in FAMILY_KEYS:
                    v=data.get(key,'')
                    if v and values.get(key) and str(values[key])!=v:errors.setdefault(i,[]).append('Family '+number+': conflicting '+key.replace('_',' '))
                    elif v:values[key]=v
            mapped.append(data)
        admissions=set();capacity={ (r['campus'],r['class_name'],r['academic_session']):dict(r) for r in app.extensions['admission_capacity']['rows']() }
        for i,input_data in enumerate(mapped):
            data=dict(input_data);number=data.get('family_no','')
            if number:data.update(family_values[number])
            for key,value in [('admission_date',batch.data['default_date']),('status','Active'),('guardian_relation','Father')]:
                if not data.get(key):data[key]=value
            for key,category in [('campus','campus'),('class_name','class_name'),('section','section'),('group_name','group_name'),('academic_session','academic_session'),('fee_plan','fee_plan')]:
                if not data.get(key) and len(choices.get(category,[]))==1:data[key]=choices[category][0][0]
            data['family_mode']='existing' if number in families else 'new';data['family_id']=str(families[number].id) if number in families else ''
            data['admission_no']=data.get('admission_no') or 'IMP-'+batch.id[:12]+'-'+str(i+1)
            if data['admission_no'] in admissions:errors.setdefault(i,[]).append('Duplicate admission number in this sheet.')
            admissions.add(data['admission_no'])
            form=MultiDict(data);form.setlist('subjects',[s.strip() for s in data.get('subjects','').split('|') if s.strip()])
            validated,problems=app.extensions['record_helpers']['validate']('student',None,form,known=known)
            for key,problem in problems.items():errors.setdefault(i,[]).append(key.replace('_',' ')+': '+problem)
            for key,limit in [('name',120),('admission_no',30),('class_name',50),('father',120),('phone',30),('family_no',60)]:
                if len(validated.get(key,''))>limit:errors.setdefault(i,[]).append(key+' exceeds '+str(limit)+' characters.')
            plan=None
            try:
                effective=data.get('effective') or batch.data['default_date'][:7]
                if not re.fullmatch(r'\d{4}-\d{2}',effective):raise ValueError('Fee effective month must be YYYY-MM.')
                date.fromisoformat(effective+'-01')
                schedule=schedules.get((validated.get('campus',''),validated.get('class_name',''),validated.get('fee_plan','')))
                if not schedule:raise ValueError('Configure a fee schedule for this campus, class and plan before importing.')
                lines=app.extensions['fee_setup_helpers']['assigned_rows'](schedule)
                for line in lines:
                    key=line['particular']
                    if data.get('amount::'+key):line['actual']=money(data['amount::'+key])
                    line['discount']=money(data.get('discount::'+key));line['arrears']=money(data.get('arrears::'+key))
                pct=fee_percentage(data.get('percentage') or '0');lines=increment_lines(lines,pct,False)
                if len(data.get('concession_reason',''))>200:raise ValueError('Fee concession reason exceeds 200 characters.')
                plan=dict(effective=effective,data=dict(schedule=schedule.name,lines=lines,percentage=str(pct),year=effective[:4],reason=data.get('concession_reason','')[:200],notes='Imported student fee plan',**app.extensions['fee_setup_helpers']['snapshot'](schedule)))
            except ValueError as error:errors.setdefault(i,[]).append(str(error))
            scope=(validated.get('campus',''),validated.get('class_name',''),validated.get('academic_session',''));limit=capacity.get(scope)
            if validated.get('status')=='Active' and limit and limit['seats'] is not None:
                if limit['occupied']>=limit['seats']:validated['status']='Waiting'
                else:limit['occupied']+=1
            prepared.append(dict(row=i,sheet_row=batch.data.get('row_numbers',list(range(2,len(raw)+2)))[i],student=validated,plan=plan,roll_revision=roll_allocator.stamp))
        # Reserve typed rolls from the entire sheet before assigning blanks,
        # including typed values that appear later in the file.
        roll_allocator.reserved=[copy.deepcopy(entry['student']) for entry in prepared if str(entry['student'].get('roll_no','')).strip()]
        for entry in prepared:roll_allocator.allocate(entry['student'])
        return prepared,errors
    @bp.route('/<token>',methods=['GET','POST'])
    def review(token):
        batch=batch_for(token)
        try:page=max(1,int(request.values.get('page','1')))
        except ValueError:raise ValueError('Choose a valid page.')
        pages=max(1,(len(batch.data.get('rows',[]))+9)//10);page=min(page,pages)
        if batch.status!='Draft':return render_template('student_import_done.html',title='Student import batch',batch=batch)
        if request.method=='POST':
            if request.form.get('version')!=str(batch.version):raise ValueError('This import changed. Reload before saving corrections.')
            if request.form.get('action')=='cancel':batch.status='Cancelled';batch.data={};commit();return redirect(url_for('student_import.index'))
            if request.form.get('action')!='review':raise ValueError('Review the mapping and rows before importing.')
            fields=columns();mapping=[request.form.get('map_'+str(i),'') for i in range(len(batch.data['headers']))]
            used=[x for x in mapping if x]
            if len(used)!=len(set(used)) or any(x not in fields for x in used):raise ValueError('Map each target field only once; ignore unused columns.')
            data=copy.deepcopy(batch.data);data['mapping']=mapping
            for i in range((page-1)*10,min(page*10,len(data['rows']))):
                for j in range(len(data['headers'])):
                    value=request.form.get(f'cell_{i}_{j}',data['rows'][i][j]).strip()
                    if len(value)>5000:raise ValueError('Use cell values up to 5,000 characters.')
                    data['rows'][i][j]=value
            batch.data=data;prepared,errors=prepare(batch);batch.data={**data,'ready':not errors,'hash':digest(prepared)};commit()
            return redirect(url_for('student_import.review',token=token,page=page))
        prepared,errors=prepare(batch);unchanged=batch.data.get('hash')==digest(prepared)
        confirmation=signer().dumps(dict(batch=batch.id,version=batch.version,hash=digest(prepared),actor=actor())) if not errors and batch.data.get('ready') and unchanged else ''
        return render_template('student_import_review.html',title='Review student import',batch=batch,fields=columns(),prepared=prepared,errors=errors,page=page,pages=pages,confirmation=confirmation,stale=batch.data.get('ready') and not unchanged)
    def snapshot(ids):
        students=Student.query.filter(Student.id.in_(ids)).order_by(Student.id).all();details=app.extensions['record_helpers']['raw_many']('student',students)
        plans=P.query.filter(P.student_id.in_(ids)).order_by(P.id).all()
        return digest(dict(students=[[s.id,s.name,s.admission_no,s.father,s.phone,s.class_name,s.status,details.get(s.id)] for s in students],plans=[[p.id,p.version,p.effective,p.data] for p in plans]))
    @bp.post('/<token>/apply')
    def apply(token):
        batch=batch_for(token)
        if batch.status!='Draft':raise ValueError('This batch is already imported or closed. It cannot be imported again.')
        if len(request.form.get('confirmation',''))>8192:raise ValueError('Invalid confirmation. Review again.')
        try:payload=signer().loads(request.form.get('confirmation',''),max_age=900)
        except BadData:raise ValueError('Review confirmation expired or changed. Review the sheet again.')
        prepared,errors=prepare(batch)
        if errors or payload!=dict(batch=batch.id,version=batch.version,hash=digest(prepared),actor=actor()) or not batch.data.get('ready') or batch.data.get('hash')!=digest(prepared):raise ValueError('The sheet, settings or source data changed. Review all errors/rows again; nothing was imported.')
        families={f.number:f for f in Family.query.all()};ids=[];created_families=[]
        for entry in prepared:
            # The complete cohort/seat preview was revalidated under the shared write gate.
            data=copy.deepcopy(entry['student'])
            number=data.get('family_no') or 'F-'+secrets.token_hex(6).upper();family=families.get(number)
            if not family:
                family=Family(number=number,data={k:data.get(k,'') for k in FAMILY_KEYS});db.session.add(family);db.session.flush();families[number]=family;created_families.append(family.id)
            data.update(family.data);data.update(family_no=number,family_id=str(family.id),family_mode='existing')
            pupil=Student(**{k:data[k] for k in ('name','admission_no','father','phone','class_name','status')});db.session.add(pupil);db.session.flush();ids.append(pupil.id)
            data['bio_id']=data.get('bio_id') or str(pupil.id)
            db.session.add(Details(student_id=pupil.id,family_id=family.id,data=data));db.session.flush()
            plan=entry['plan'];db.session.add(P(student_id=pupil.id,effective=plan['effective'],data=plan['data']));db.session.add(rm['event'](owner_kind='student',owner_id=pupil.id,action='Imported'))
        request.roll_import_allocator.persist()
        db.session.flush();batch.status='Imported';batch.data={**batch.data,'student_ids':ids,'created_families':created_families,'snapshot':snapshot(ids)}
        db.session.add(Audit(action='Import students',data=dict(batch=batch.id,student_ids=ids,owner_id=session.get('owner_id'))));commit()
        flash(f'{len(ids)} students and their fee plans imported. No messages were sent.','success');return redirect(url_for('student_import.review',token=token))
    @bp.post('/<token>/undo')
    def undo(token):
        batch=batch_for(token)
        if batch.status!='Imported' or request.form.get('version')!=str(batch.version):raise ValueError('This batch changed or is not an imported batch.')
        ids=batch.data['student_ids']
        if snapshot(ids)!=batch.data['snapshot']:raise ValueError('Imported records or plans changed. Undo is blocked to protect later work.')
        allowed={Details.__table__.name,P.__table__.name}
        for table in db.metadata.sorted_tables:
            if table.name in allowed:continue
            for column in table.columns:
                if any(fk.column.table.name==Student.__table__.name for fk in column.foreign_keys):
                    if db.session.execute(select(column).where(column.in_(ids)).limit(1)).first():raise ValueError('Imported students have linked attendance, financial or document records. Undo is blocked.')
        if rm['file'].query.filter(rm['file'].owner_kind=='student',rm['file'].owner_id.in_(ids)).first():raise ValueError('Imported students have uploaded photos/documents. Undo is blocked.')
        if ops['daily'].query.filter(ops['daily'].kind=='student',ops['daily'].person_id.in_(ids)).first():raise ValueError('Imported students have attendance. Undo is blocked.')
        if rm['event'].query.filter(rm['event'].owner_kind=='student',rm['event'].owner_id.in_(ids),rm['event'].action!='Imported').first():raise ValueError('Imported students have later edit events. Undo is blocked.')
        rm['event'].query.filter(rm['event'].owner_kind=='student',rm['event'].owner_id.in_(ids),rm['event'].action=='Imported').delete(synchronize_session=False)
        P.query.filter(P.student_id.in_(ids)).delete(synchronize_session=False);Details.query.filter(Details.student_id.in_(ids)).delete(synchronize_session=False);Student.query.filter(Student.id.in_(ids)).delete(synchronize_session=False)
        for fid in batch.data['created_families']:
            if not Details.query.filter_by(family_id=fid).first():
                family=db.session.get(Family,fid)
                if family:db.session.delete(family)
        batch.status='Undone';db.session.add(Audit(action='Undo student import',data=dict(batch=batch.id,student_ids=ids,owner_id=session.get('owner_id'))));commit();return redirect(url_for('student_import.review',token=token))
    app.register_blueprint(bp)
