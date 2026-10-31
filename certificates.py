"""Campus certificate templates, non-issuing previews, issued snapshots and QR output."""
import base64,csv,hashlib,hmac,io,re,secrets
from datetime import datetime,date
from zoneinfo import ZoneInfo
import bleach,qrcode
from bleach.css_sanitizer import CSSSanitizer
from qrcode.image.svg import SvgPathImage
from flask import Blueprint,abort,flash,redirect,render_template,request,session,url_for,g
from markupsafe import Markup,escape
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import StaleDataError
from certificate_defaults import DOCUMENTS,CATALOG,default_content

TAGS=('copyType todayDate instName instContact instEmail instLogo instAddress studentName fatherName fatherMobile rollNo regNo familyNo campusName className sectionName SessionName studentGroup CurrentStatus dob currentMonth admissionDate leavingDate admissionClass boardRegNo boardRollNo boardTotalMarks boardObtMarks stdPhoto qrCode examHall examRollNo sid stdPic gender religion studentCnic studentContactNo studentEmail birthCity bloodGroup caste identificationMark fatherCnic guardianName guardianCnic currentAddress permanentAddress color_primary color_secondary color_3 color_4 institute_name institute_logo campus_address campus_city campus_open_date campus_contact campus_email currPayable tuitionFee admissionfee totalPayable totalRemPayable totalPaidAmount totalDiscountGiven currentTotal currentPaid curRemaining curDiscount refNo reference').split()
HTML_TAGS=['p','div','span','b','strong','i','em','u','s','strike','br','hr','h1','h2','h3','h4','h5','h6','table','thead','tbody','tfoot','tr','td','th','ul','ol','li','blockquote','a','img','sup','sub']
CSS=CSSSanitizer(allowed_css_properties=['color','background-color','font-family','font-size','font-weight','font-style','text-decoration','text-align','text-transform','line-height','letter-spacing','width','height','min-height','max-width','margin','margin-top','margin-bottom','margin-left','margin-right','padding','padding-top','padding-bottom','padding-left','padding-right','border','border-top','border-bottom','border-left','border-right','border-color','border-width','border-style','border-radius','border-collapse','vertical-align','display','float','object-fit'])

def clean_html(value):
    def attribute(tag,name,value):
        if name=='style':return True
        if name in ('colspan','rowspan') and tag in ('td','th'):return bool(re.fullmatch(r'\d{1,2}',value))
        if name in ('alt','title'):return True
        if tag=='a' and name=='href':return value.startswith(('https://','http://','mailto:','#'))
        if tag=='img' and name=='src':return bool(re.fullmatch(r'/(?:records/files/\d+|workspace/certificates/(?:logo/\d+|qr/\d+\.svg))',value))
        return False
    return bleach.clean(str(value),tags=HTML_TAGS,attributes=attribute,protocols=['http','https','mailto'],strip=True,strip_comments=True,css_sanitizer=CSS)

def configure_certificates(app,db,Student):
    bp=Blueprint('certificates',__name__,url_prefix='/workspace/certificates')
    rm=app.extensions['record_models'];models=app.extensions['ops_models'];Bill=models['bill'];Audit=models['audit'];Plan=app.extensions['student_fee_plan_model']
    details=app.extensions['operation_helpers']['details']
    class CertificateCampus(db.Model):
        id=db.Column(db.Integer,primary_key=True)
        campus=db.Column(db.String(160),nullable=False,unique=True)
        data=db.Column(db.JSON,nullable=False,default=dict)
        logo=db.Column(db.LargeBinary)
        logo_mime=db.Column(db.String(30))
        version=db.Column(db.Integer,nullable=False,default=1)
        __mapper_args__={'version_id_col':version}
    class CertificateTemplate(db.Model):
        id=db.Column(db.Integer,primary_key=True)
        campus_id=db.Column(db.Integer,db.ForeignKey('certificate_campus.id'),nullable=False)
        key=db.Column(db.String(40),nullable=False)
        name=db.Column(db.String(160),nullable=False)
        header=db.Column(db.Text,nullable=False)
        body=db.Column(db.Text,nullable=False)
        footer=db.Column(db.Text,nullable=False)
        version=db.Column(db.Integer,nullable=False,default=1)
        __table_args__=(db.UniqueConstraint('campus_id','key'),)
        __mapper_args__={'version_id_col':version}
    class CertificateBatch(db.Model):
        id=db.Column(db.Integer,primary_key=True)
        token=db.Column(db.String(100),nullable=False,unique=True)
        template_id=db.Column(db.Integer,db.ForeignKey('certificate_template.id'),nullable=False)
        student_ids=db.Column(db.JSON,nullable=False)
        copy_type=db.Column(db.String(20),nullable=False)
        created=db.Column(db.DateTime,nullable=False,default=lambda:datetime.now(ZoneInfo('UTC')))
    class CertificateIssue(db.Model):
        __table_args__=(db.UniqueConstraint('batch_id','student_id'),)
        id=db.Column(db.Integer,primary_key=True,autoincrement=True)
        batch_id=db.Column(db.Integer,db.ForeignKey('certificate_batch.id'),nullable=False)
        student_id=db.Column(db.Integer,db.ForeignKey('student.id'),nullable=False,index=True)
        template_id=db.Column(db.Integer,db.ForeignKey('certificate_template.id'),nullable=False)
        campus=db.Column(db.String(160),nullable=False,index=True)
        document_name=db.Column(db.String(160),nullable=False)
        student_name=db.Column(db.String(160),nullable=False)
        reference=db.Column(db.String(60),nullable=False)
        snapshot=db.Column(db.JSON,nullable=False)
        html=db.Column(db.Text,nullable=False,default='')
        created=db.Column(db.DateTime,nullable=False,default=lambda:datetime.now(ZoneInfo('UTC')))
    app.extensions['certificate_models']=dict(campus=CertificateCampus,template=CertificateTemplate,batch=CertificateBatch,issue=CertificateIssue)
    def now():return datetime.now(ZoneInfo('Asia/Karachi'))
    def campuses():return sorted({x.value for x in rm['settings'].query.filter_by(category='campus').all()}|{x.campus for x in CertificateCampus.query.all()})
    def commit():
        try:db.session.commit()
        except (IntegrityError,StaleDataError):db.session.rollback();raise ValueError('This record was already saved or changed. Reload before retrying.')
    def num(value,label='selection'):
        try:return int(value)
        except (ValueError,TypeError):raise ValueError('Invalid '+label+'.')
    def csrf_token():
        token=request.form.get('_csrf','');expected=session.get('record_csrf','')
        if not token or not expected or not hmac.compare_digest(token,expected):abort(400)
    @bp.before_request
    def protect():
        if request.method=='POST':csrf_token()
    @bp.errorhandler(ValueError)
    def invalid(exc):
        db.session.rollback();return render_template('operation_error.html',title='Check certificate request',error=str(exc)),422
    @bp.errorhandler(IntegrityError)
    def duplicate(exc):
        db.session.rollback();return render_template('operation_error.html',title='Reload this operation',error='This setup or print request was already saved. Reload to view the saved result.'),422
    def campus_for(template):return db.get_or_404(CertificateCampus,template.campus_id)
    def selected_campus():
        name=request.values.get('campus','') or (campuses()[0] if campuses() else '')
        if name and name not in campuses():raise ValueError('Choose a configured campus.')
        return name
    def filtered_students(campus,active=False):
        rows=Student.query.order_by(Student.id).all();result=[]
        q=request.values.get('q','').strip().lower()
        for s in rows:
            d=details(s)
            if campus and d.get('campus')!=campus:continue
            if active and s.status!='Active':continue
            if q and q not in f'{s.id} {s.admission_no} {s.name} {s.father} {d.get("roll_no","")}'.lower():continue
            if any(request.values.get(k) and request.values[k]!=d.get(k) for k in ('section','gender')):continue
            if request.values.get('class_name') and request.values['class_name']!=s.class_name:continue
            result.append((s,d))
        return result
    def csv_response(headers,rows,name):
        if request.args.get('export')=='xlsx':
            from openpyxl import Workbook
            from openpyxl.styles import Font,PatternFill
            from openpyxl.utils import get_column_letter
            workbook=Workbook();sheet=workbook.active;sheet.title='SchoolFlow';sheet.append(headers)
            for cell in sheet[1]:cell.font=Font(bold=True,color='FFFFFF');cell.fill=PatternFill('solid',fgColor='176B4A')
            for row in rows:
                safe=[re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]','',x) if isinstance(x,str) else x for x in row]
                sheet.append(safe)
                for cell in sheet[sheet.max_row]:
                    if isinstance(cell.value,str):cell.data_type='s'  # Never execute names / QR strings as formulas.
            sheet.freeze_panes='A2';sheet.auto_filter.ref=sheet.dimensions
            for i in range(1,len(headers)+1):sheet.column_dimensions[get_column_letter(i)].width=25
            output=io.BytesIO();workbook.save(output)
            return app.response_class(output.getvalue(),mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',headers={'Content-Disposition':f'attachment; filename="schoolflow-{name}.xlsx"'})
        stream=io.StringIO();writer=csv.writer(stream);writer.writerow(headers)
        for row in rows:writer.writerow(["'"+str(x) if str(x).lstrip().startswith(('=','+','-','@')) else str(x) for x in row])
        response=app.response_class('\ufeff'+stream.getvalue(),mimetype='text/csv');response.headers['Content-Disposition']=f'attachment; filename="schoolflow-{name}.csv"';return response
    def qr_payload(s):
        namespace=(getattr(g,'school_identity',None) or {}).get('scope','DEMO')
        token=hmac.new(str(app.config['SECRET_KEY']).encode(),f'schoolflow:student-qr:{namespace}:{s.id}:{s.admission_no}'.encode(),hashlib.sha256).hexdigest()
        return 'schoolflow:student:'+token
    @bp.get('/qr/<int:sid>.svg')
    def qr(sid):
        s=db.get_or_404(Student,sid);img=qrcode.make(qr_payload(s),image_factory=SvgPathImage,box_size=5,border=4)
        response=app.response_class(img.to_string(),mimetype='image/svg+xml');response.headers['Cache-Control']='private, no-store';return response
    @bp.get('/logo/<int:cid>')
    def logo(cid):
        c=db.get_or_404(CertificateCampus,cid)
        if not c.logo:abort(404)
        return app.response_class(c.logo,mimetype=c.logo_mime,headers={'Cache-Control':'private, no-store'})
    def image_tag(src,alt):
        size=('90px','90px') if 'QR' in alt else (('55px','55px') if 'logo' in alt.lower() else ('70px','80px'))
        return f'<img src="{escape(src)}" alt="{escape(alt)}" style="max-width:{size[0]};height:{size[1]};object-fit:contain">'
    def mapping(s,c,ref,copy_type):
        d=details(s);settings=c.data;today=now().date()
        photo=rm['file'].query.filter_by(owner_kind='student',owner_id=s.id,photo=True).first()
        image=image_tag(url_for('records.record_file',id=photo.id),'Student photo') if photo else '<span>Photo</span>'
        logo=image_tag(url_for('certificates.logo',cid=c.id),'School logo') if c.logo else '<span>School logo</span>'
        qr=image_tag(url_for('certificates.qr',sid=s.id),'Student QR code')
        values={tag.casefold():'' for tag in TAGS}
        aliases=dict(studentName=s.name,fatherName=d.get('father') or s.father or '',fatherMobile=s.phone or '',rollNo=d.get('roll_no') or s.admission_no,regNo=s.id,sid=s.id,admissionNo=s.admission_no,familyNo=d.get('family_no',''),campusName=c.campus,className=s.class_name or '',sectionName=d.get('section',''),SessionName=d.get('academic_session',''),studentGroup=d.get('group_name',''),CurrentStatus=s.status,todayDate=today.strftime('%d %B %Y'),currentMonth=today.strftime('%B %Y'),copyType=copy_type,refNo=ref,reference=str(ref),instName=settings.get('name') or 'School Name',institute_name=settings.get('name') or 'School Name',instContact=settings.get('contact',''),instEmail=settings.get('email',''),instAddress=settings.get('address',''),campus_address=settings.get('address',''),campus_city=settings.get('city',''),campus_open_date=settings.get('open_date',''),campus_contact=settings.get('contact',''),campus_email=settings.get('email',''))
        field_map=dict(dob='birth_date',admissionDate='admission_date',leavingDate='leaving_date',admissionClass='class_of_admission',boardRegNo='board_reg_no',boardRollNo='board_roll_no',boardTotalMarks='board_total',boardObtMarks='board_obtained',examHall='exam_hall',examRollNo='exam_roll_no',gender='gender',religion='religion',studentCnic='student_cnic',studentContactNo='student_phone',studentEmail='student_email',birthCity='birth_city',bloodGroup='blood_group',caste='caste',identificationMark='identification_mark',fatherCnic='father_cnic',guardianName='guardian_name',guardianCnic='guardian_cnic',currentAddress='current_address',permanentAddress='permanent_address')
        aliases.update({key:d.get(field,'') for key,field in field_map.items()})
        for key,default in [('color_primary','#176b4a'),('color_secondary','#dceee4'),('color_3','#f5f8f6'),('color_4','#243c30')]:aliases[key]=settings.get(key,default)
        bills=Bill.query.filter_by(student_id=s.id).all();current=[b for b in bills if b.month==today.strftime('%Y-%m')]
        current_plan=Plan.query.filter(Plan.student_id==s.id,Plan.effective<=today.strftime('%Y-%m')).order_by(Plan.effective.desc()).first()
        plan_lines=current_plan.data['lines'] if current_plan else []
        amounts=dict(totalPayable=sum(b.total for b in bills),totalRemPayable=sum(b.remaining for b in bills),totalPaidAmount=sum(b.paid for b in bills),totalDiscountGiven=sum(b.discount for b in bills),currPayable=sum(b.total for b in current),currentTotal=sum(b.total for b in current),currentPaid=sum(b.paid for b in current),curRemaining=sum(b.remaining for b in current),curDiscount=sum(b.discount for b in current),tuitionFee=sum(x['net'] for x in plan_lines if x['particular'].casefold() in ('tuition fee','tuition')),admissionfee=sum(x['net'] for x in plan_lines if x['particular'].casefold()=='admission fee'))
        aliases.update({key:f'{value/100:,.2f}' for key,value in amounts.items()})
        values.update({key.casefold():str(value) for key,value in aliases.items()})
        for key,value in [('stdPhoto',image),('stdPic',image),('instLogo',logo),('institute_logo',logo),('qrCode',qr)]:values[key.casefold()]=Markup(value)
        return values,amounts,d
    # All render state is passed explicitly; no globals or shared request state.
    def document(s,c,t,ref,copy_type,content=None):
        values,amounts,data=mapping(s,c,ref,copy_type)
        values['reference']=f"{CATALOG[t.key]['prefix']}-{ref}"
        def replace(match):
            value=values.get(match.group(1).casefold())
            if value is None:return str(escape(match.group(0)))
            return str(value) if isinstance(value,Markup) else str(escape(value))
        content=content or {key:getattr(t,key) for key in ('header','body','footer')}
        sections={key:clean_html(re.sub(r'\[([A-Za-z_][A-Za-z0-9_]*)\]',replace,value)) for key,value in content.items()}
        html=render_template('certificate_document.html',sections=sections,layout=CATALOG[t.key]['layout'])
        return html,amounts,data

    qr_columns=[('sid','SID'),('roll','Roll No.'),('name','Student Name'),('father','Father Name'),('campus','Campus'),('class','Class'),('section','Section'),('gender','Gender'),('photo','Student Photo'),('qr','QR Code')]
    def selected_columns():
        columns=request.values.getlist('columns') or ([] if request.values.get('columns_configured') else [key for key,label in qr_columns])
        if not columns or not set(columns)<={key for key,label in qr_columns}:raise ValueError('Choose at least one valid export / print column.')
        return list(dict.fromkeys(columns))
    def qr_values(s,d):
        photo=rm['file'].query.filter_by(owner_kind='student',owner_id=s.id,photo=True).first()
        return dict(sid=s.id,roll=d.get('roll_no') or s.admission_no,name=s.name,father=s.father or '',campus=d.get('campus',''),**{'class':s.class_name},section=d.get('section',''),gender=d.get('gender',''),photo=url_for('records.record_file',id=photo.id) if photo else '',qr=qr_payload(s))

    @bp.route('',methods=['GET'])
    def index():
        campus=selected_campus();tab=request.args.get('tab','cards')
        if tab not in ('cards','logs','qr'):abort(404)
        c=CertificateCampus.query.filter_by(campus=campus).first()
        templates=CertificateTemplate.query.filter_by(campus_id=c.id).all() if c else []
        page=num(request.args.get('page','1'),'page');size=num(request.args.get('size','100' if tab=='qr' else '25'),'page size');columns=selected_columns()
        if page<1 or size not in (25,50,100):raise ValueError('Choose a valid page and page size.')
        all_rows=filtered_students(campus,active=tab=='qr');total=len(all_rows);rows=all_rows[(page-1)*size:page*size]
        issues=CertificateIssue.query.filter_by(campus=campus).order_by(CertificateIssue.id.desc()).all() if campus else []
        q=request.args.get('q','').strip().lower()
        if q:issues=[r for r in issues if q in f'{r.student_name} {r.document_name} {r.reference} {r.student_id}'.lower()]
        if tab=='logs':total=len(issues);issues=issues[(page-1)*size:page*size]
        if request.args.get('export') in ('csv','xlsx'):
            if tab=='logs':return csv_response(['Reference','Certificate','SID','Student','Campus','Generated At (Karachi)'],[[r.reference,r.document_name,r.student_id,r.student_name,r.campus,local_time(r.created)] for r in issues],'certificate-logs')
            return csv_response([dict(qr_columns)[key] for key in columns],[[qr_values(s,d)[key] for key in columns] for s,d in all_rows],'student-qr' if tab=='qr' else 'certificate-students')
        return render_template('certificates.html',title='Student Cards & Certificates',campuses=campuses(),campus=campus,config=c,tab=tab,templates={t.key:t for t in templates},catalog=CATALOG,qr_columns=qr_columns,columns=columns,rows=rows,issues=issues,total=total,page=page,size=size,pages=max(1,(total+size-1)//size),token=secrets.token_urlsafe(32),options=lambda category:[x.value for x in rm['settings'].query.filter_by(category=category).all()],photo=lambda sid:rm['file'].query.filter_by(owner_kind='student',owner_id=sid,photo=True).first(),local_time=local_time)
    def local_time(value):
        return value.replace(tzinfo=ZoneInfo('UTC')).astimezone(ZoneInfo('Asia/Karachi')).strftime('%d-%b-%Y %I:%M %p') if value.tzinfo is None else value.astimezone(ZoneInfo('Asia/Karachi')).strftime('%d-%b-%Y %I:%M %p')

    @bp.post('/setup')
    def setup():
        campus=selected_campus()
        if not campus:raise ValueError('Configure a campus first.')
        c=CertificateCampus.query.filter_by(campus=campus).first()
        if not c:c=CertificateCampus(campus=campus,data={});db.session.add(c);db.session.flush()
        for key,meta in CATALOG.items():
            if not CertificateTemplate.query.filter_by(campus_id=c.id,key=key).first():db.session.add(CertificateTemplate(campus_id=c.id,key=key,name=meta['name'],**default_content(key)))
        db.session.add(Audit(action='Set up certificate templates',data=dict(campus=campus)));commit();flash('15 editable campus templates are ready. Configure the school heading and logo before printing.','success')
        return redirect(url_for('certificates.index',campus=campus))

    @bp.route('/campus/<int:cid>',methods=['GET','POST'])
    def campus_config(cid):
        c=db.get_or_404(CertificateCampus,cid)
        if request.method=='POST':
            if request.form.get('version')!=str(c.version):raise ValueError('Campus settings changed; reload before saving.')
            data={key:request.form.get(key,'').strip() for key in ('name','contact','email','address','city','open_date','color_primary','color_secondary','color_3','color_4')}
            if not data['name'] or len(data['name'])>160:raise ValueError('School name is required, up to 160 characters.')
            if any(len(value)>2000 for value in data.values()):raise ValueError('Campus setting is too long.')
            for key in ('color_primary','color_secondary','color_3','color_4'):
                if data[key] and not re.fullmatch(r'#[0-9a-fA-F]{6}',data[key]):raise ValueError('Choose valid six-digit theme colours.')
            if data['open_date']:
                try:date.fromisoformat(data['open_date'])
                except ValueError:raise ValueError('Choose a valid campus opening date.')
            image=request.files.get('logo')
            if image and image.filename:
                content=image.read(2*1024*1024+1)
                if not content or len(content)>2*1024*1024:raise ValueError('Logo must be an image up to 2 MB.')
                try:
                    from PIL import Image
                    probe=Image.open(io.BytesIO(content));fmt=probe.format;probe.verify()
                except Exception:raise ValueError('Choose a valid PNG, JPEG or WebP logo.')
                if fmt not in ('PNG','JPEG','WEBP'):raise ValueError('Choose a PNG, JPEG or WebP logo.')
                c.logo=content;c.logo_mime={'PNG':'image/png','JPEG':'image/jpeg','WEBP':'image/webp'}[fmt]
            if request.form.get('remove_logo'):c.logo=None;c.logo_mime=None
            c.data=data;commit();flash('Campus certificate heading updated. Existing issued documents keep their saved content.','success');return redirect(url_for('certificates.index',campus=c.campus))
        return render_template('certificate_campus.html',title='Certificate School Heading',config=c)

    @bp.route('/template/<int:tid>/edit',methods=['GET','POST'])
    def edit(tid):
        t=db.get_or_404(CertificateTemplate,tid);c=campus_for(t);preview_html=None;name=t.name
        content={key:getattr(t,key) for key in ('header','body','footer')}
        if request.method=='POST':
            target=num(request.form.get('campus_id',c.id),'campus')
            if request.form.get('action')=='switch_campus':
                other=CertificateTemplate.query.filter_by(campus_id=target,key=t.key).first()
                if not other:raise ValueError('Set up document templates in the selected campus first.')
                return redirect(url_for('certificates.edit',tid=other.id))
            if target!=c.id:raise ValueError('Load the selected campus template before saving changes.')
            if request.form.get('version')!=str(t.version):raise ValueError('This template changed. Reload before saving.')
            name=request.form.get('name','').strip()
            if not name or len(name)>160:raise ValueError('Template name is required, up to 160 characters.')
            content={key:request.form.get(key,'') for key in ('header','body','footer')}
            if any(len(value)>150000 for value in content.values()):raise ValueError('A template section is too large.')
            content={key:clean_html(value) for key,value in content.items()}
            if not bleach.clean(content['body'],tags=[],strip=True).strip() and '<img' not in content['body']:raise ValueError('Add document body content.')
            if request.form.get('action')=='preview':
                students=filtered_students(c.campus)
                if students:preview_html=document(students[0][0],c,t,'PREVIEW','Original',content)[0]
                else:flash('Save a student in this campus to preview personalised fields.','info')
            elif request.form.get('action')=='save':
                t.name=name
                for key,value in content.items():setattr(t,key,value)
                db.session.add(Audit(action='Update certificate template',data=dict(template_id=t.id,campus=c.campus)));commit();flash('Template updated. Preview it before printing.','success');return redirect(url_for('certificates.index',campus=c.campus))
            else:raise ValueError('Choose Preview changes or Save template.')
        return render_template('certificate_editor.html',title='Edit Certificate Template',template=t,config=c,content=content,name=name,tags=TAGS,preview_html=preview_html,campus_configs=CertificateCampus.query.order_by(CertificateCampus.campus).all())

    def get_selection(t,allow_first=False):
        ids=list(dict.fromkeys(num(x,'student selection') for x in request.form.getlist('student_ids')))
        c=campus_for(t)
        if not ids and allow_first:
            options=filtered_students(c.campus)
            if options:ids=[options[0][0].id]
        if not ids or len(ids)>100:raise ValueError('Select between 1 and 100 students.')
        rows=[]
        for sid in ids:
            s=db.get_or_404(Student,sid)
            if details(s).get('campus')!=c.campus:raise ValueError('Selected students must belong to the template campus.')
            rows.append(s)
        return c,rows

    @bp.post('/documents')
    def documents():
        action=request.form.get('action','')
        template_id=request.form.get('template_id','')
        if action.startswith('preview:'):template_id=action.split(':',1)[1];action='preview'
        t=db.get_or_404(CertificateTemplate,num(template_id,'template'));c,students=get_selection(t,allow_first=action=='preview')
        copy_type=request.form.get('copy_type','Original')
        if copy_type not in ('Original','Duplicate'):raise ValueError('Choose Original or Duplicate copy.')
        token=request.form.get('token','')
        if not re.fullmatch(r'[A-Za-z0-9_-]{20,100}',token):raise ValueError('Reload the document selection page.')
        if action=='preview':
            index=num(request.form.get('index','0'),'preview page')
            if not 0<=index<len(students):raise ValueError('Invalid preview page.')
            html,amounts,_=document(students[index],c,t,'PREVIEW',copy_type)
            return render_template('certificate_preview.html',title='Preview — '+t.name,template=t,config=c,students=students,index=index,html=html,amounts=amounts,token=token,copy_type=copy_type)
        if action!='issue':raise ValueError('Choose a document action.')
        ids=[s.id for s in students];batch=CertificateBatch.query.filter_by(token=token).first()
        if batch:
            if batch.template_id!=t.id or batch.student_ids!=ids or batch.copy_type!=copy_type:raise ValueError('This print token was already used for a different selection. Reload the page.')
            return redirect(url_for('certificates.batch_print',bid=batch.id))
        if not c.data.get('name'):raise ValueError('Configure the school name in School heading, logo & colours before issuing documents.')
        if t.key=='fee-clearance' and any(sum(b.remaining for b in Bill.query.filter_by(student_id=s.id).all())>0 for s in students):raise ValueError('Fee clearance cannot be issued while a selected student has outstanding dues.')
        batch=CertificateBatch(token=token,template_id=t.id,student_ids=ids,copy_type=copy_type);db.session.add(batch);db.session.flush()
        snapshot_bytes=0
        for s in students:
            issue=CertificateIssue(batch_id=batch.id,student_id=s.id,template_id=t.id,campus=c.campus,document_name=t.name,student_name=s.name,reference='Pending',snapshot={});db.session.add(issue);db.session.flush()
            html,amounts,d=document(s,c,t,issue.id,copy_type)
            issue.reference=f"{CATALOG[t.key]['prefix']}-{issue.id}";issue.html=html
            # Freeze image bytes as well as names/fees; later profile/logo edits do not alter a reprint.
            def freeze(match):
                src=match.group(1)
                if src.startswith('/records/files/'):
                    f=db.session.get(rm['file'],int(src.rsplit('/',1)[1]));mime=f.mime if f else None;content=f.content if f else None
                elif src.startswith('/workspace/certificates/logo/'):
                    mime=c.logo_mime;content=c.logo
                else:
                    mime='image/svg+xml';content=qrcode.make(qr_payload(s),image_factory=SvgPathImage,box_size=5,border=4).to_string()
                return 'src="data:'+mime+';base64,'+base64.b64encode(content).decode()+'"' if content and mime else 'alt="Image unavailable"'
            issue.html=re.sub(r'src="(/(?:records/files/\d+|workspace/certificates/(?:logo/\d+|qr/\d+\.svg)))"',freeze,issue.html)
            snapshot_bytes+=len(issue.html.encode())+sum(len(getattr(t,key).encode()) for key in ('header','body','footer'))
            if snapshot_bytes>20*1024*1024:raise ValueError('These documents are too large for one print batch. Select fewer students.')
            issue.snapshot=dict(student=dict(id=s.id,name=s.name,father=d.get('father') or s.father,roll_no=d.get('roll_no') or s.admission_no,class_name=s.class_name,section=d.get('section','')),template=dict(name=t.name,key=t.key,version=t.version,**{key:getattr(t,key) for key in ('header','body','footer')}),fees=amounts,copy_type=copy_type)
        db.session.add(Audit(action='Generate certificates for printing',data=dict(template_id=t.id,student_ids=ids,batch_token=token)));commit()
        return redirect(url_for('certificates.batch_print',bid=batch.id))

    @bp.get('/batch/<int:bid>')
    def batch_print(bid):
        batch=db.get_or_404(CertificateBatch,bid);issues=CertificateIssue.query.filter_by(batch_id=bid).order_by(CertificateIssue.id).all()
        return render_template('certificate_print.html',title='Print Generated Documents',issues=issues)
    @bp.get('/issued/<int:iid>')
    def issued(iid):
        issue=db.get_or_404(CertificateIssue,iid)
        return render_template('certificate_print.html',title=issue.document_name+' · '+issue.reference,issues=[issue])

    @bp.post('/qr-print')
    def qr_print():
        campus=selected_campus();ids=list(dict.fromkeys(num(x,'student selection') for x in request.form.getlist('student_ids')))
        if not ids or len(ids)>100:raise ValueError('Select between 1 and 100 students to print QR codes.')
        students=[]
        for sid in ids:
            s=db.get_or_404(Student,sid)
            if s.status!='Active' or details(s).get('campus')!=campus:raise ValueError('Select active students from the chosen campus.')
            photo=rm['file'].query.filter_by(owner_kind='student',owner_id=s.id,photo=True).first();students.append((s,details(s),photo))
        return render_template('student_qr_print.html',title='Student QR Codes',students=students,columns=selected_columns(),qr_columns=qr_columns,qr_values=qr_values)
    app.register_blueprint(bp)
