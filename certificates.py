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

TAGS=('copyType todayDate instName instContact instEmail instLogo instAddress studentName fatherName fatherMobile rollNo regNo admissionNo familyNo campusName className sectionName SessionName studentGroup CurrentStatus dob currentMonth admissionDate leavingDate admissionClass boardRegNo boardRollNo boardTotalMarks boardObtMarks stdPhoto guardianPhoto qrCode examHall examRollNo sid stdPic gender religion studentCnic studentContactNo studentEmail birthCity bloodGroup caste identificationMark fatherCnic guardianName guardianCnic currentAddress permanentAddress color_primary color_secondary color_3 color_4 institute_name institute_logo campus_address campus_city campus_open_date campus_contact campus_email currPayable tuitionFee admissionfee totalPayable totalRemPayable totalPaidAmount totalDiscountGiven currentTotal currentPaid curRemaining curDiscount refNo reference').split()
HTML_TAGS=['p','div','span','b','strong','i','em','u','s','strike','br','hr','h1','h2','h3','h4','h5','h6','table','thead','tbody','tfoot','tr','td','th','ul','ol','li','blockquote','a','img','sup','sub']
CSS=CSSSanitizer(allowed_css_properties=['color','background-color','font-family','font-size','font-weight','font-style','text-decoration','text-align','text-transform','line-height','letter-spacing','width','height','min-height','max-width','margin','margin-top','margin-bottom','margin-left','margin-right','padding','padding-top','padding-bottom','padding-left','padding-right','border','border-top','border-bottom','border-left','border-right','border-color','border-width','border-style','border-radius','border-collapse','vertical-align','display','float','object-fit'])

def clean_html(value,report_assets=False):
    def attribute(tag,name,value):
        if name=='style':return True
        if name=='class' and tag=='table':return value in ('guardian-front','guardian-back','guardian-facts','guardian-verification-facts')
        if name in ('colspan','rowspan') and tag in ('td','th'):return bool(re.fullmatch(r'\d{1,2}',value))
        if name in ('alt','title'):return True
        if tag=='a' and name=='href':return value.startswith(('https://','http://','mailto:','#'))
        if tag=='img' and name=='src' and report_assets and re.fullmatch(r'/workspace/core/(?:logo|hrm/employee-qr/\d+\.svg)',value):return True
        if tag=='img' and name=='src':return bool(re.fullmatch(r'/(?:records/files/\d+|workspace/certificates/(?:logo/\d+|qr/\d+\.svg|guardian-qr/\d+\.svg))',value))
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
        logo=db.deferred(db.Column(db.LargeBinary))
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
        snapshot=db.deferred(db.Column(db.JSON,nullable=False))
        html=db.deferred(db.Column(db.Text,nullable=False,default=''))
        created=db.Column(db.DateTime,nullable=False,default=lambda:datetime.now(ZoneInfo('UTC')))
    app.extensions['certificate_models']=dict(campus=CertificateCampus,template=CertificateTemplate,batch=CertificateBatch,issue=CertificateIssue)
    def now():return datetime.now(ZoneInfo('Asia/Karachi'))
    def campuses():return sorted(({x.value for x in rm['settings'].query.filter_by(category='campus').all()}|{x[0] for x in db.session.query(CertificateCampus.campus).all()})-{''})
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
    def selected_campus(names=None):
        if names is None: names=campuses()
        name=request.values.get('campus','') or (names[0] if names else '')
        if name and name not in names:raise ValueError('Choose a configured campus.')
        return name
    def filtered_students(campus,active=False):
        rows=Student.query.order_by(Student.id).all();result=[]
        raw=app.extensions['record_helpers']['raw_many']('student',rows)
        q=request.values.get('q','').strip().lower()
        for s in rows:
            d=raw[s.id]
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
            workbook=Workbook();sheet=workbook.active;sheet.title='InstituteAxis';sheet.append(headers)
            for cell in sheet[1]:cell.font=Font(bold=True,color='FFFFFF');cell.fill=PatternFill('solid',fgColor='176B4A')
            for row in rows:
                safe=[re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]','',x) if isinstance(x,str) else x for x in row]
                sheet.append(safe)
                for cell in sheet[sheet.max_row]:
                    if isinstance(cell.value,str):cell.data_type='s'  # Never execute names / QR strings as formulas.
            sheet.freeze_panes='A2';sheet.auto_filter.ref=sheet.dimensions
            for i in range(1,len(headers)+1):sheet.column_dimensions[get_column_letter(i)].width=25
            output=io.BytesIO();workbook.save(output)
            return app.response_class(output.getvalue(),mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',headers={'Content-Disposition':f'attachment; filename="instituteaxis-{name}.xlsx"'})
        stream=io.StringIO();writer=csv.writer(stream);writer.writerow(headers)
        for row in rows:writer.writerow(["'"+str(x) if str(x).lstrip().startswith(('=','+','-','@')) else str(x) for x in row])
        response=app.response_class('\ufeff'+stream.getvalue(),mimetype='text/csv');response.headers['Content-Disposition']=f'attachment; filename="instituteaxis-{name}.csv"';return response
    def qr_payload(s):
        namespace=(getattr(g,'school_identity',None) or {}).get('scope','DEMO')
        token=hmac.new(str(app.config['SECRET_KEY']).encode(),f'schoolflow:student-qr:{namespace}:{s.id}:{s.admission_no}'.encode(),hashlib.sha256).hexdigest()
        return 'schoolflow:student:'+token
    def guardian_signature(iid):
        return hmac.new(str(app.config['SECRET_KEY']).encode(),f'guardian-card:{iid}'.encode(),hashlib.sha256).hexdigest()[:32]
    def guardian_status(issue):
        if issue.snapshot.get('template',{}).get('key')!='guardian-card':return 'Not a guardian card'
        if any((a.data or {}).get('issue_id')==issue.id for a in Audit.query.filter_by(action='Revoke guardian card').all()):return 'REVOKED'
        student=db.session.get(Student,issue.student_id)
        if not student or student.status!='Active':return 'INACTIVE'
        d=details(student);issued=issue.snapshot.get('student',{})
        issued_session=issued.get('academic_session','')
        current_session=d.get('academic_session','')
        if not issued_session or not current_session:return 'SESSION NOT SET'
        if str(issued_session)!=str(current_session) or issued.get('class_name')!=student.class_name or issued.get('section','')!=d.get('section',''):
            return 'EXPIRED'
        latest=CertificateIssue.query.join(CertificateTemplate,CertificateIssue.template_id==CertificateTemplate.id).filter(CertificateIssue.student_id==student.id,CertificateTemplate.key=='guardian-card',CertificateIssue.id>issue.id).first()
        if latest:return 'SUPERSEDED'
        return 'VALID'
    @bp.get('/guardian-qr/<int:iid>.svg')
    def guardian_qr_image(iid):
        issue=db.get_or_404(CertificateIssue,iid)
        if issue.snapshot.get('template',{}).get('key')!='guardian-card':abort(404)
        response=app.response_class(guardian_qr(iid),mimetype='image/svg+xml');response.headers['Cache-Control']='private, no-store';return response
    @bp.get('/guardian-verify/<int:iid>/<signature>')
    def guardian_verify(iid,signature):
        if not hmac.compare_digest(signature,guardian_signature(iid)):abort(404)
        issue=db.get_or_404(CertificateIssue,iid)
        status=guardian_status(issue)
        response=app.response_class('<!doctype html><meta name="schoolflow-document" content="1"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Guardian card verification</title><main style="font:18px Arial;max-width:480px;margin:12vh auto;padding:25px;border:2px solid #176b4a;border-radius:12px"><h2>InstituteAxis Guardian Card</h2><h1>'+str(escape(status))+'</h1><p>Reference: '+str(escape(issue.reference))+'</p><p>Verify the guardian photo in person before releasing a student.</p></main>',mimetype='text/html')
        response.headers['Cache-Control']='no-store';return response
    @bp.post('/guardian-revoke/<int:iid>')
    def guardian_revoke(iid):
        issue=db.get_or_404(CertificateIssue,iid)
        if issue.snapshot.get('template',{}).get('key')!='guardian-card':abort(404)
        db.session.add(Audit(action='Revoke guardian card',data=dict(issue_id=issue.id,reference=issue.reference,campus=issue.campus)))
        commit();flash('Guardian card revoked. Its verification will show REVOKED.','success')
        return redirect(url_for('certificates.index',tab='logs',campus=issue.campus))
    def guardian_qr(iid):
        link=url_for('certificates.guardian_verify',iid=iid,signature=guardian_signature(iid),_external=True)
        return qrcode.make(link,image_factory=SvgPathImage,box_size=5,border=4).to_string()
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
        size=('90px','90px') if 'QR' in alt else (('55px','55px') if 'logo' in alt.lower() else (('78px','92px') if 'Guardian photo' in alt else (('58px','70px') if 'Student photo' in alt else ('70px','80px'))))
        return f'<img src="{escape(src)}" alt="{escape(alt)}" style="max-width:{size[0]};height:{size[1]};object-fit:contain">'
    def mapping(s,c,ref,copy_type):
        d=details(s);settings=c.data;today=now().date()
        photo=rm['file'].query.filter_by(owner_kind='student',owner_id=s.id,photo=True).first()
        image=image_tag(url_for('records.record_file',id=photo.id),'Student photo') if photo else '<span>Student photo not uploaded</span>'
        guardian=rm['file'].query.filter_by(owner_kind='guardian',owner_id=s.id,photo=True).first()
        guardian_image=image_tag(url_for('records.record_file',id=guardian.id),'Guardian photo') if guardian else '<span>Guardian photo not uploaded</span>'
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
        for key,value in [('stdPhoto',image),('stdPic',image),('guardianPhoto',guardian_image),('instLogo',logo),('institute_logo',logo),('qrCode',qr)]:values[key.casefold()]=Markup(value)
        return values,amounts,d
    # All render state is passed explicitly; no globals or shared request state.
    def document(s,c,t,ref,copy_type,content=None):
        from certificate_defaults import default_content
        values,amounts,data=mapping(s,c,ref,copy_type)
        if t.key=='guardian-card':
            d=details(s);values['sessionname']=str(d.get('academic_session') or 'Not set')
            values['qrcode']=Markup(image_tag(url_for('certificates.guardian_qr_image',iid=int(ref)),'Student QR code')) if str(ref).isdigit() else Markup('<span>QR available after issuing</span>')
        values['reference']=f"{CATALOG.get(t.key,{'prefix':'DOC'})['prefix']}-{ref}"
        def replace(match):
            value=values.get(match.group(1).casefold())
            if value is None:return str(escape(match.group(0)))
            return str(value) if isinstance(value,Markup) else str(escape(value))
        content=content or {key:getattr(t,key) for key in ('header','body','footer')}
        # Upgrade only the original unlabelled ID-card template markup in memory.
        # Do not overwrite campus-edited templates or historical issued snapshots.
        if t.key in ('student-card-new','student-card','guardian-card'):
            legacy='[stdPhoto]<h3>[studentName]</h3><p>[fatherName]</p><p>Class: [className] · Section: [sectionName]</p><p>SID: [sid] · Roll: [rollNo]</p>'
            labelled='[stdPhoto]<p><b>Student Name:</b> [studentName]</p><p><b>Father Name:</b> [fatherName]</p><p><b>Class:</b> [className] &nbsp; <b>Section:</b> [sectionName]</p><p><b>Roll No.:</b> [rollNo] &nbsp; <b>Student ID:</b> [sid]</p>'
            if legacy in content.get('body',''):
                content=dict(content,body=content['body'].replace(legacy,labelled))
        # Upgrade the unedited starter guardian card without changing campus-customized cards.
        if t.key == 'guardian-card' and 'For student pick-up and drop-off' in content.get('body','') and 'Card expiry: __________________' in content.get('body',''):
            content=dict(content,body=default_content('guardian-card')['body'])
        if t.key=='guardian-card' and 'Valid Until' in content.get('body','') and 'GUARDIAN VERIFICATION' in content.get('body',''):
            content=dict(content,body=content['body'].replace('Valid Until','Valid Session').replace('________________','[SessionName]'))
        # Existing campuses keep their original database template after a code deploy.
        # Recognise the exact shipped migration starter (not school-edited templates)
        # and use the current design for NEW previews/issues only. Issued HTML is immutable.
        if t.key == 'migration':
            old_identity='<p><b>[studentName]</b>, son / daughter of <b>[fatherName]</b>, Class <b>[className]</b>, Section <b>[sectionName]</b>.</p>'
            old_registration='<table style="width:100%"><tr><td>Registration No.: [regNo]</td><td>Date of Birth: [dob]</td><td>Session: [SessionName]</td></tr></table>'
            old_copy='<p>Certificate copy: [copyType]</p>'
            old_body=(old_identity+'<p>Migration from campus: [campusName]</p>'
                +'<p>Migration to campus: ____________________</p>'
                +'<p>Effective date: ____________________</p>'
                +'<p>Reason / remarks: ________________________________________</p>'
                +old_registration+old_copy)
            old_prefix=('<table style="width:100%"><tr><td>Date: [todayDate]</td>'
                +'<td style="text-align:right">Ref: [reference]</td></tr></table>'
                +'<h1 style="text-align:center;color:#176b4a">MIGRATION SLIP CAMPUS - CAMPUS</h1>')
            if content.get('body','') == old_prefix + old_body:
                content=dict(content,body=default_content('migration')['body'])
        # Shorten only the exact previously shipped migration paragraphs in saved
        # templates; never overwrite school-edited text or historical issued HTML.
        if t.key == 'migration':
            old_approval=(
                'This document records a campus transfer request for the above-named student within <b>[instName]</b>. '
                'The transfer becomes effective only after approval by the authorised school administration and acknowledgement by the receiving campus. '
                'Until then, the student remains enrolled at the transferring campus.'
            )
            old_note=(
                'Note: This slip does not itself change the student\'s campus or enrolment record. '
                'The authorised transfer must be recorded separately in the school system.'
            )
            if old_approval in content.get('body','') and old_note in content.get('body',''):
                content=dict(content,body=content['body'].replace(
                    old_approval,
                    'Transfer is effective only after school approval and receiving-campus acknowledgement. Until then, the student remains enrolled at the current campus.'
                ).replace(old_note,"Note: Update the student's campus in InstituteAxis only after approval."))
        # Existing campus databases retain the original rustication starter.
        # Upgrade only its distinctive unedited text for new previews/issues;
        # issued document snapshots and customised templates are not changed.
        if t.key == 'rustication':
            old_rustication=(
                '<p>This notice records an administrative decision concerning the student’s enrolment.</p>'
                '<p>Effective date: ____________________</p>'
                '<p>Reason and supporting record: ______________________________</p>'
                '<p>Parent / guardian acknowledgement: ________________________</p>'
                '<p>This document does not change the student’s saved status.</p>'
            )
            if old_rustication in content.get('body',''):
                content=dict(content,body=default_content('rustication')['body'])
        # Upgrade the exact shipped warning-letter starter in school databases.
        # Preserve customized templates and immutable previously issued snapshots.
        if t.key == 'warning':
            old_warning=(
                '<h3>Subject: Attendance and academic progress</h3>'
                '<p>Dear parent / guardian,</p>'
                '<p>Please meet the school to discuss the student’s attendance, academic progress and agreed steps for improvement.</p>'
                '<p>Areas requiring attention: ______________________________</p>'
                '<p>Meeting date and time: _________________________________</p>'
                '<p>Review date: _________________________________________</p>'
                '<p>Sincerely,<br>Principal, [instName]</p>'
            )
            if old_warning in content.get('body',''):
                content=dict(content,body=default_content('warning')['body'])
        # Upgrade only the untouched starter wording for future certificates.
        # Campus-customized wording and previously issued documents remain unchanged.
        if t.key == 'character':
            legacy_character='This certificate records the student’s character and conduct during attendance at [instName].'
            if legacy_character in content.get('body',''):
                content=dict(content,body=default_content('character')['body'])
        if t.key == 'school-leaving':
            legacy_start='<p><b>[studentName]</b>, son / daughter of <b>[fatherName]</b>, Class <b>[className]</b>, Section <b>[sectionName]</b>.</p><p>Was admitted on'
            if legacy_start in content.get('body',''):
                content=dict(content,body=default_content('school-leaving')['body'])
        # Refresh only identifiable InstituteAxis starter templates stored before the
        # redesigned defaults shipped. Never rewrite custom school templates or
        # historical issued HTML snapshots.
        starter_markers = {
            'envelope': ('SID: [sid]', 'Roll No.: [rollNo]', '[studentName]'),
            'admitted-card': ('ACCOUNTANT SIGNATURE', 'PRINCIPAL SIGNATURE', '[admissionDate]'),
            'birth': ('The date of birth above is reproduced from the school', 'Registration No.: [regNo]'),
            'appreciation': ('Awarded for Excellence', 'Has achieved position'),
            'admission-confirmation': ('Basic Fee Plan', 'Current Fee Status', '[admissionfee]'),
            'fee-clearance': ('Decided Tuition Fee', 'Current Month Remaining', '[totalRemPayable]'),
            'trip': ('Educational and Recreational School Trip', 'Venue / destination'),
        }
        markers = starter_markers.get(t.key)
        if markers and all(marker.casefold() in content.get('body','').casefold() for marker in markers):
            content=dict(content,body=default_content(t.key)['body'])
        # Refresh the exact previous admission-letter default, preserving edited bodies.
        if t.key == 'admission-confirmation':
            previous_default = '9da93f77169098dac3ae421e1d1dfa38d704d86e0fcc9670b9670b0a0f97a994'
            if hashlib.sha256(content.get('body', '').encode()).hexdigest() == previous_default:
                content = dict(content, body=default_content(t.key)['body'])
        sections={key:clean_html(re.sub(r'\[([A-Za-z_][A-Za-z0-9_]*)\]',replace,value)) for key,value in content.items()}
        html=render_template('certificate_document.html',sections=sections,layout=CATALOG.get(t.key,{'layout':'certificate'})['layout'])
        return html,amounts,data

    qr_columns=[('sid','SID'),('roll','Roll No.'),('name','Student Name'),('father','Father Name'),('campus','Campus'),('class','Class'),('section','Section'),('gender','Gender'),('photo','Student Photo'),('qr','QR Code')]
    def selected_columns():
        columns=request.values.getlist('columns') or ([] if request.values.get('columns_configured') else [key for key,label in qr_columns])
        if not columns or not set(columns)<={key for key,label in qr_columns}:raise ValueError('Choose at least one valid export / print column.')
        return list(dict.fromkeys(columns))
    def photos_for(students):
        ids=[s.id for s in students];result={};File=rm['file']
        for offset in range(0,len(ids),900):
            for row in db.session.query(File.id,File.owner_id).filter(File.owner_kind=='student',File.photo==True,File.owner_id.in_(ids[offset:offset+900])).order_by(File.id).all():
                result.setdefault(row.owner_id,row)
        return result
    def qr_values(s,d,photos):
        photo=photos.get(s.id)
        return dict(sid=s.id,roll=d.get('roll_no') or s.admission_no,name=s.name,father=s.father or '',campus=d.get('campus',''),**{'class':s.class_name},section=d.get('section',''),gender=d.get('gender',''),photo=url_for('records.record_file',id=photo.id) if photo else '',qr=qr_payload(s))

    admission_letter_key = 'admission-confirmation'

    @bp.route('',methods=['GET'])
    def index():
        campus_names=campuses();campus=selected_campus(campus_names);tab=request.args.get('tab','cards')
        if tab not in ('cards','admission-letter','logs','qr'):abort(404)
        c=CertificateCampus.query.filter_by(campus=campus).first()
        templates=CertificateTemplate.query.filter_by(campus_id=c.id).all() if c else []
        page=num(request.args.get('page','1'),'page');size=num(request.args.get('size','100' if tab=='qr' else '25'),'page size');columns=selected_columns()
        if page<1 or size not in (25,50,100):raise ValueError('Choose a valid page and page size.')
        all_rows=filtered_students(campus,active=tab=='qr') if tab!='logs' else [];total=len(all_rows);rows=all_rows[(page-1)*size:page*size]
        issues=CertificateIssue.query.filter_by(campus=campus).order_by(CertificateIssue.id.desc()).all() if campus and tab=='logs' else []
        q=request.args.get('q','').strip().lower()
        if q:issues=[r for r in issues if q in f'{r.student_name} {r.document_name} {r.reference} {r.student_id}'.lower()]
        if tab=='logs':total=len(issues);issues=issues[(page-1)*size:page*size]
        if request.args.get('export') in ('csv','xlsx'):
            if tab=='logs':return csv_response(['Reference','Certificate','SID','Student','Campus','Generated At (Karachi)'],[[r.reference,r.document_name,r.student_id,r.student_name,r.campus,local_time(r.created)] for r in issues],'certificate-logs')
            photos=photos_for([s for s,d in all_rows]);export_rows=[]
            for s,d in all_rows:
                values=qr_values(s,d,photos);export_rows.append([values[key] for key in columns])
            return csv_response([dict(qr_columns)[key] for key in columns],export_rows,'student-qr' if tab=='qr' else 'certificate-students')
        photos=photos_for([s for s,d in rows]);option_rows=rm['settings'].query.filter(rm['settings'].category.in_(['class_name','section','gender'])).all()
        catalog={**CATALOG,**{t.key:dict(name=t.name,captured=True) for t in templates if t.key not in CATALOG}}
        admission_letter = tab == 'admission-letter'
        if admission_letter:
            catalog = {admission_letter_key: catalog[admission_letter_key]}
        return render_template('certificates.html',title='Admission Letter' if admission_letter else 'Student Cards & Certificates',admission_letter=admission_letter,campuses=campus_names,campus=campus,config=c,tab=tab,templates={t.key:t for t in templates},catalog=catalog,qr_columns=qr_columns,columns=columns,rows=rows,issues=issues,total=total,page=page,size=size,pages=max(1,(total+size-1)//size),token=secrets.token_urlsafe(32),options=lambda category:[x.value for x in option_rows if x.category==category],photo=lambda sid:photos.get(sid),local_time=local_time,guardian_signature=guardian_signature)
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
        tab = 'admission-letter' if request.form.get('tab') == 'admission-letter' else 'cards'
        return redirect(url_for('certificates.index',campus=campus,tab=tab))

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
        # Never populate a certificate with another student's details unless
        # that student was explicitly selected by the operator.
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
        t=db.get_or_404(CertificateTemplate,num(template_id,'template'));c,students=get_selection(t)
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
        if t.key=='birth' and any(not str(details(s).get('birth_date') or '').strip() for s in students):raise ValueError('Enter and verify the student date of birth in the admission record before issuing a school birth certificate.')
        batch=CertificateBatch(token=token,template_id=t.id,student_ids=ids,copy_type=copy_type);db.session.add(batch);db.session.flush()
        snapshot_bytes=0
        for s in students:
            issue=CertificateIssue(batch_id=batch.id,student_id=s.id,template_id=t.id,campus=c.campus,document_name=t.name,student_name=s.name,reference='Pending',snapshot={});db.session.add(issue);db.session.flush()
            html,amounts,d=document(s,c,t,issue.id,copy_type)
            issue.reference=f"{CATALOG.get(t.key,{'prefix':'DOC'})['prefix']}-{issue.id}";issue.html=html
            # Freeze image bytes as well as names/fees; later profile/logo edits do not alter a reprint.
            def freeze(match):
                src=match.group(1)
                if src.startswith('/records/files/'):
                    f=db.session.get(rm['file'],int(src.rsplit('/',1)[1]));mime=f.mime if f else None;content=f.content if f else None
                elif src.startswith('/workspace/certificates/logo/'):
                    mime=c.logo_mime;content=c.logo
                else:
                    mime='image/svg+xml';content=guardian_qr(issue.id) if t.key=='guardian-card' else qrcode.make(qr_payload(s),image_factory=SvgPathImage,box_size=5,border=4).to_string()
                return 'src="data:'+mime+';base64,'+base64.b64encode(content).decode()+'"' if content and mime else 'alt="Image unavailable"'
            issue.html=re.sub(r'src="(/(?:records/files/\d+|workspace/certificates/(?:logo/\d+|qr/\d+\.svg|guardian-qr/\d+\.svg)))"',freeze,issue.html)
            snapshot_bytes+=len(issue.html.encode())+sum(len(getattr(t,key).encode()) for key in ('header','body','footer'))
            if snapshot_bytes>20*1024*1024:raise ValueError('These documents are too large for one print batch. Select fewer students.')
            issue.snapshot=dict(student=dict(id=s.id,name=s.name,father=d.get('father') or s.father,roll_no=d.get('roll_no') or s.admission_no,class_name=s.class_name,section=d.get('section',''),academic_session=d.get('academic_session','')),template=dict(name=t.name,key=t.key,version=t.version,**{key:getattr(t,key) for key in ('header','body','footer')}),fees=amounts,copy_type=copy_type)
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
        pupils=Student.query.filter(Student.id.in_(ids)).all()
        if len(pupils)!=len(ids):abort(404)
        raw=app.extensions['record_helpers']['raw_many']('student',pupils)
        photos=photos_for(pupils);by_id={s.id:s for s in pupils};students=[]
        for sid in ids:
            s=by_id[sid];d=raw[sid]
            if s.status!='Active' or d.get('campus')!=campus:raise ValueError('Select active students from the chosen campus.')
            students.append((s,d,photos.get(s.id)))
        return render_template('student_qr_print.html',title='Student QR Codes',students=students,columns=selected_columns(),qr_columns=qr_columns,qr_values=lambda s,d:qr_values(s,d,photos))
    app.register_blueprint(bp)
