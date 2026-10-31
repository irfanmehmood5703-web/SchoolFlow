"""Shared, single-pass report tag values and private generated image assets.

Plain record values are always escaped in HTML. Only server-built assets may
supply image markup; text substituted from records is never parsed again.
"""
import calendar, hashlib, hmac, re
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo
from flask import g, has_request_context, request, url_for
from markupsafe import escape

TAG=re.compile(r'\[([A-Za-z0-9_]+)\]')


def expand_tags(text,values,html=False,assets=None):
    assets=assets or {}
    def replace(match):
        key=match.group(1)
        if html and key in assets:return assets[key]
        if key not in values:return match.group(0)
        value='' if values[key] is None else str(values[key])
        return str(escape(value)) if html else value
    return TAG.sub(replace,text)


def missing_tags(text,values,assets=None):
    return sorted(set(TAG.findall(text))-set(values)-set(assets or {}))


def make_branding_values(app,db,Student,Employee):
    rm=app.extensions['record_models'];ops=app.extensions['ops_models'];File=rm['file']
    def today():return datetime.now(ZoneInfo('Asia/Karachi')).date()
    def cash(value):return f'{Decimal(str(value or 0))/100:,.2f}'
    def profile():
        if has_request_context() and hasattr(request,'branding_profile'):return request.branding_profile
        row=db.session.get(app.extensions['institute_setup_models']['profile'],1)
        if has_request_context():request.branding_profile=row
        return row
    def school(campus):
        cache=getattr(request,'branding_school_values',{}) if has_request_context() else {}
        if campus in cache:return dict(cache[campus])
        p=profile();data=p.data if p else {};c=db.session.get(app.extensions['institute_setup_models']['campus'],campus) if campus else None
        values=dict(institute_name=data.get('name') or 'SchoolFlow',campus_name=campus,campus_address=data.get('address',''),campus_contact=data.get('contact',''),campus_email=data.get('email',''),campus_city=c.city if c else '',campus_open_date=data.get('open_date',''),slogan=data.get('slogan',''),todayDate=today().isoformat(),currentMonth=today().strftime('%Y-%m'),color_primary='#176b4a',color_secondary='#e7f3ec',color_3='#ffffff',color_4='#454b48')
        if has_request_context():cache[campus]=dict(values);request.branding_school_values=cache
        return values
    def details(kind,person):return app.extensions['record_helpers']['raw_many'](kind,[person]).get(person.id,{})
    def student(person,data=None):
        d=details('student',person) if data is None else data
        values=school(d.get('campus',''))
        values.update(sid=person.id,studentName=person.name,fatherName=d.get('father') or person.father or '',fatherMobile=d.get('phone') or person.phone or '',className=person.class_name or '',currentStatus=person.status,regNo=person.id,rollNo=d.get('roll_no',''),familyNo=d.get('family_no',''),feePlanList=d.get('fee_plan',''))
        aliases={'dob':'birth_date','gender':'gender','religion':'religion','queryDate':'query_date','admissionDate':'admission_date','studentCnic':'student_cnic','studentContactNo':'student_phone','studentEmail':'student_email','birthCity':'birth_city','bloodGroup':'blood_group','caste':'caste','identificationMark':'identification_mark','bioId':'bio_id','fatherCnic':'father_cnic','whatsappNo':'whatsapp','fatherEmail':'guardian_email','fatherProfession':'profession','guardianName':'guardian_name','guardianRelation':'guardian_relation','guardianCnic':'guardian_cnic','motherName':'mother_name','motherMobile':'mother_phone','motherEmail':'mother_email','motherCnic':'mother_cnic','currentAddress':'current_address','permanentAddress':'permanent_address','sectionName':'section','SessionName':'academic_session','studentGroup':'group_name','examRollNo':'exam_roll_no','examHall':'exam_hall'}
        values.update({tag:d.get(field,'') for tag,field in aliases.items()})
        return values
    def employee(person,data=None):
        d=details('employee',person) if data is None else data
        values=school(d.get('campus',''))
        values.update(emp_id=person.employee_no,emp_name=person.name,emp_contact=person.phone or '',designation_name=person.role or '',emp_status=person.status)
        aliases={'emp_father_name':'father_name','emp_fname':'father_name','emp_cnic':'cnic','emp_email':'email','emp_dob':'birth_date','emp_city':'city','emp_address':'address','emp_marital_status':'marital_status','emp_reference':'reference','emp_notes':'notes','department_name':'department'}
        values.update({tag:d.get(field,'') for tag,field in aliases.items()})
        values.update({key:d.get(key,'') for key in ('home_phone','emergency_contact_name','emergency_contact_no','contact_relation','gender','marital_status','designation_group','employment_type','joining_date','bank_info','lecture_assigned','leaving_date','agreement_no','probation_from','probation_to')})
        words={'Female':('Daughter of','Ms.','she','She','her','Her','her'),'Male':('Son of','Mr.','he','He','his','His','him')}.get(d.get('gender'),('Child of','Mx.','they','They','their','Their','them'))
        values.update(zip(('son_daughter_of','mr_ms','he_she','he_she_capital','his_her','his_her_capital','him_her'),words))
        values['emp_degrees']=' · '.join(str(d[k]) for k in ('qualification_degree','qualification_major','qualification_board','qualification_grade','qualification_from','qualification_to') if d.get(k))
        values['emp_documents']='; '.join(prefetch_documents([person]).get(person.id,[]))
        return values
    def plan(data):
        fixed_earnings=data.get('basic',0)+data.get('security_return',0)+sum(a['amount'] for a in data.get('allowances',[]) if a['type']=='Earning')
        fixed_deductions=data.get('security_payment',0)+sum(a['amount'] for a in data.get('allowances',[]) if a['type']=='Deduction')
        month=str(data.get('increment_month',''))
        values=dict(plan_basic_salary=cash(data.get('basic',0)),plan_security_payment=cash(data.get('security_payment',0)),plan_earning_basic_salary=cash(data.get('basic',0)),plan_earning_security_payment_return=cash(data.get('security_return',0)),plan_deduction_security_payment=cash(data.get('security_payment',0)),annual_increment=cash(data.get('annual_increment',0)),annual_increment_month=calendar.month_name[int(month)] if month.isdigit() and 1<=int(month)<=12 else month)
        # Fixed-plan net is intentionally distinct from a generated salary net.
        if not data.get('lecture_wise') or data.get('include_plan_earnings'):values['plan_net_salary']=cash(fixed_earnings-fixed_deductions)
        return values
    def approved_plan(person):
        plans=ops['workflow'].query.filter_by(kind='salary-plans',status='Approved').order_by(ops['workflow'].id.desc()).all()
        row=next((p for p in plans if str(p.data.get('employee_id'))==str(person.id)),None)
        return plan(row.data) if row else {}
    def salary(row,person,data=None):
        values=employee(person,data);values.update(plan(row.detail.get('plan',{})))
        attendance=sum(line.get('amount',0) for line in row.detail.get('attendance',[]))
        advances=sum(row.detail.get('advances',{}).values())
        values.update(salary_month=row.month,salary_date=row.paid_date.isoformat() if row.paid_date else '',earnings=cash(row.earnings),deductions=cash(row.deductions),net_salary=cash(row.net),total_salary_amount=cash(row.net),attendance_deduction=cash(attendance),plan_deduction_advance_salary=cash(advances),salary_status='Paid' if row.paid>=row.net else ('Partially Paid' if row.paid else 'Unpaid'))
        return values
    def prefetch_photos(kind,people):
        cache=getattr(request,'branding_photos',{}) if has_request_context() else {};ids=[p.id for p in people if (kind,p.id) not in cache]
        for sid in ids:cache[(kind,sid)]=None
        for offset in range(0,len(ids),900):
            for fid,owner in db.session.query(File.id,File.owner_id).filter(File.owner_kind==kind,File.photo==True,File.owner_id.in_(ids[offset:offset+900])).all():cache[(kind,owner)]=fid
        if has_request_context():request.branding_photos=cache
        return cache
    def prefetch_documents(people):
        cache=getattr(request,'branding_documents',{}) if has_request_context() else {};ids=[p.id for p in people if p.id not in cache]
        for sid in ids:cache[sid]=[]
        for offset in range(0,len(ids),900):
            for sid,title,filename in db.session.query(File.owner_id,File.title,File.filename).filter(File.owner_kind=='employee',File.photo==False,File.owner_id.in_(ids[offset:offset+900])).order_by(File.id).all():cache[sid].append(title or filename)
        if has_request_context():request.branding_documents=cache
        return cache
    def prefetch_employees(people):
        prefetch_photos('employee',people);prefetch_documents(people)
    def image(src,alt):return '<img src="'+str(escape(src))+'" alt="'+str(escape(alt))+'" style="max-width:90px;max-height:100px;object-fit:contain">'
    def assets(kind=None,person=None):
        p=profile();values={'institute_logo':image(url_for('institute_setup.logo'),'School logo') if p and p.logo_mime else ''}
        if person is not None:
            fid=prefetch_photos(kind,[person]).get((kind,person.id));photo=image(url_for('records.record_file',id=fid),'Student photo' if kind=='student' else 'Employee photo') if fid else ''
            if kind=='student':values['stdPic']=photo
            else:
                values['emp_photo']=photo;values['emp_qr']=image(url_for('school_settings.employee_qr',employee_id=person.id),'Employee QR')
        return values
    def qr_token(person):
        namespace=(getattr(g,'school_identity',None) or {}).get('scope','DEMO')
        return 'schoolflow:employee:'+hmac.new(str(app.config['SECRET_KEY']).encode(),f'schoolflow:employee-qr:{namespace}:{person.id}:{person.employee_no}'.encode(),hashlib.sha256).hexdigest()
    return dict(school=school,student=student,employee=employee,plan=plan,approved_plan=approved_plan,salary=salary,assets=assets,prefetch_photos=prefetch_photos,prefetch_employees=prefetch_employees,qr_token=qr_token)
