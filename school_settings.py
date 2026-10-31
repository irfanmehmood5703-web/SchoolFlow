"""Tenant-owned Exam and HRM configuration, consumed by operational workflows.

All mutations share the institute write gate. Version checks reject stale forms.
No provider delivery is performed by template previews or configuration saves.
"""
import calendar, hmac, re, io
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from flask import Blueprint, abort, flash, redirect, render_template, request, session, url_for, has_request_context
from markupsafe import Markup, escape
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import StaleDataError
from certificates import clean_html
from record_schema import EMPLOYEE_SECTIONS

DAYS=('Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday')
EXAM_PAGES=[('display','Mark Display Names'),('subject-groups','Subject Groups'),('subjects','Subjects'),('class-subjects','Subjects in Classes'),('test-types','Test Types'),('weightage','Test Type Weightage'),('grading','Grading Policies'),('class-grading','Class Grading Policy'),('student-shifts','Student Shifts'),('sms','Student SMS Templates'),('branding','Exam Brandings')]
HRM_PAGES=[('employee-fields','Employee Form Settings'),('print-templates','Print Templates'),('allowances','Allowance / Deduction'),('departments','Departments'),('designation-groups','Designation Groups'),('designations','Manage Designations'),('employment-types','Employment Types'),('shift-templates','Shift Templates'),('sms','HRM SMS Templates'),('attendance-lock','Lock Attendance'),('branding','HRM Brandings')]
HRM_LAYOUTS=['Individual Attendance Report','Combine Attendance Report','Salary Slip Report','Salary Signature Report','Salary Payment Report','Monthly Attendance','Salary Increment Sheet','Bank Salary Sheet']
EXAM_LAYOUTS=['Attendance Sheet','Roll No. Slip','Result Card','Award List','Individual Attendance Report','Combine Attendance Report','Class/section attendance','Combined Subject Result Card','Combined Subject Report','Term Wise Report','Subject Group Wise Report','Combined And Subject Wise Report','Month Wise Report','Absentees Print Report','Date Sheet','Attendance Summary','Department Wise Report','Admission Query','Admission Form','Admission Query Blank','Admission Form Blank','Print Fee Reminder','General Branding']
CAMPUS_TAGS='institute_name campus_address campus_name campus_city campus_open_date campus_contact campus_email institute_logo slogan salary_date salary_month cheque_no total_salary_amount color_primary color_secondary color_3 color_4'.split()
EMP_TAGS='emp_id emp_name emp_father_name emp_fname emp_cnic emp_email emp_dob emp_contact emp_photo emp_city home_phone emergency_contact_name emergency_contact_no emp_address contact_relation gender marital_status emp_marital_status emp_reference emp_notes department_name designation_group designation_name employment_type joining_date bank_info emp_status lecture_assigned leaving_date emp_qr emp_degrees emp_documents agreement_no probation_from probation_to son_daughter_of mr_ms he_she he_she_capital his_her his_her_capital him_her plan_basic_salary plan_security_payment plan_net_salary annual_increment annual_increment_month plan_earning_basic_salary plan_earning_security_payment_return plan_deduction_advance_salary plan_deduction_security_payment date time qr_status earnings deductions attendance_deduction this_month_deduction this_month_compensation net_salary salary_status'.split()
STUDENT_TAGS='sid studentName stdPic rollNo regNo dob gender religion currentStatus queryDate admissionDate studentCnic studentContactNo studentEmail birthCity bloodGroup caste identificationMark bioId feePlanList fatherName fatherMobile fatherCnic whatsappNo fatherEmail fatherProfession guardianName guardianRelation guardianCnic motherName motherMobile motherEmail motherCnic currentAddress permanentAddress className sectionName SessionName studentGroup parentsAppOTP familyNo examRollNo examHall rollnosliptitle Examstartingdate examtimeduration parentsAppLink consumerNumber awardList_present_stds awardList_absent_stds awardList_leave_stds qr_att_status qr_in_status todayDate currentMonth examDate Subject examName TotalMarks ObtMarks percentage grade remarks attendance subjInfo subjInfoEnd challanNo dueDate expiryDate challanMonth challanStatus challanTotal particularSecStart particularSecEnd particularName particularPayable challanConsumerNumber arrears thisMonth totalPayable totalRemPayable totalPaidAmount totalDiscountGiven currentTotal currentPaid curRemaining curDiscount'.split()
STUDENT_SMS=['Individual Marks','Subject Combined Marks','Combine Marks','QR Attendance','QR Absent','Absent','Present','Late','Leave','Short Leave','Off Day','Death Leave','Paper Leave','Admission Query','New Admission','Left/Expelled Student','Challan Generated','Challan Paid','Fee Defaulters','Student Birthday','Date Sheet','Roll No. Slip','Parents App OTP','General SMS 1','General SMS 2','General SMS 3']
HRM_SMS=['Present','Absent','Late','Full Day Leave','Short Leave','Off Day','QR In/Out','QR Absent','Death Leave','Paper Leave','Generate Salary','Pay Salary','Birthday','New Joining','General SMS 1','General SMS 2','General SMS 3']
CATALOG_PAGES={'departments':'department','designation-groups':'designation_group','designations':'designation','employment-types':'employment_type'}
LOCKED_FIELDS={f['key'] for _,fields in EMPLOYEE_SECTIONS for f in fields if f['required']}


def configure_school_settings(app,db,Student,Employee):
    bp=Blueprint('school_settings',__name__,url_prefix='/workspace/core')
    rm=app.extensions['record_models'];ops=app.extensions['ops_models'];W=ops['workflow'];Audit=ops['audit']
    class SchoolSetting(db.Model):
        key=db.Column(db.String(180),primary_key=True)
        data=db.Column(db.JSON,nullable=False,default=dict)
        version=db.Column(db.Integer,nullable=False,default=1)
        __mapper_args__={'version_id_col':version}
    class SchoolSettingItem(db.Model):
        id=db.Column(db.Integer,primary_key=True)
        kind=db.Column(db.String(60),nullable=False,index=True)
        scope=db.Column(db.String(160),nullable=False,default='')
        name=db.Column(db.String(160),nullable=False)
        data=db.Column(db.JSON,nullable=False,default=dict)
        version=db.Column(db.Integer,nullable=False,default=1)
        __table_args__=(db.UniqueConstraint('kind','scope','name'),)
        __mapper_args__={'version_id_col':version}
    app.extensions['school_settings_models']=dict(setting=SchoolSetting,item=SchoolSettingItem)

    def setting(key):return db.session.get(SchoolSetting,key,populate_existing=True)
    def config(key):
        cache=getattr(request,'school_settings_cache',{}) if has_request_context() else {}
        if has_request_context() and request.method=='GET' and key in cache:return cache[key]
        row=setting(key);data=dict(row.data) if row else {}
        if has_request_context() and request.method=='GET':cache[key]=data;request.school_settings_cache=cache
        return data
    def items(kind,scope=None):
        cache=getattr(request,'school_settings_items',{}) if has_request_context() else {};key=(kind,scope)
        if has_request_context() and request.method=='GET' and key in cache:return cache[key]
        q=SchoolSettingItem.query.filter_by(kind=kind)
        if scope is not None:q=q.filter_by(scope=scope)
        rows=q.order_by(SchoolSettingItem.name,SchoolSettingItem.id).all()
        if has_request_context() and request.method=='GET':cache[key]=rows;request.school_settings_items=cache
        return rows
    def options(category):return sorted({r.value for r in rm['settings'].query.filter_by(category=category).all()})
    def value(key,required=False,limit=160):
        result=request.form.get(key,'').strip()
        if (required and not result) or len(result)>limit:raise ValueError('Check '+key.replace('_',' ')+'.')
        return result
    def choice(key,category,required=True):
        result=value(key,required)
        if result and result not in options(category):raise ValueError('Choose a configured '+key.replace('_',' ')+'.')
        return result
    def number(raw,maximum=100):
        try:n=Decimal(str(raw))
        except InvalidOperation:raise ValueError('Enter a valid number.')
        if not n.is_finite() or n<0 or n>maximum:raise ValueError('Number is outside the allowed range.')
        return str(n)
    def version(row):
        if request.form.get('version','')!=str(row.version if row else 0):raise ValueError('These settings changed. Reload before saving.')
    def save_config(key,data):
        row=setting(key);version(row)
        if row:row.data=data
        else:db.session.add(SchoolSetting(key=key,data=data))
    def edit_item(kind):
        sid=value('id')
        if not sid:return None
        if not sid.isdigit():abort(404)
        row=db.get_or_404(SchoolSettingItem,int(sid))
        if row.kind!=kind:abort(404)
        return row
    def save_item(kind,name,data,scope='',row=None):
        version(row)
        duplicate=SchoolSettingItem.query.filter_by(kind=kind,scope=scope,name=name).first()
        if duplicate and (not row or duplicate.id!=row.id):raise ValueError('That name or layout is already configured for this campus.')
        if row:row.name=name;row.scope=scope;row.data=data
        else:row=SchoolSettingItem(kind=kind,name=name,scope=scope,data=data);db.session.add(row)
        return row
    def audit(event,**data):db.session.add(Audit(action=event,data=data))
    def commit():
        try:db.session.commit()
        except (IntegrityError,StaleDataError):
            db.session.rollback();raise ValueError('Another save changed these settings. Reload before retrying.')
    @bp.before_request
    def protect():
        if request.method=='POST':
            token=request.form.get('_csrf','')
            if not token or not hmac.compare_digest(token,session.get('record_csrf','')):abort(400,'Reload the settings form.')
            app.extensions['admission_capacity']['lock']()
    @bp.errorhandler(ValueError)
    def invalid(exc):
        db.session.rollback();return render_template('operation_error.html',title='Check school settings',error=str(exc)),422

    def employee_sections():
        fields=config('hrm:employee-fields')
        return [(title,[dict(f,required=f['key'] in LOCKED_FIELDS or fields.get(f['key'],{}).get('required',f['required'])) for f in fs if f['key'] in LOCKED_FIELDS or fields.get(f['key'],{}).get('visible',True)]) for title,fs in EMPLOYEE_SECTIONS if any(f['key'] in LOCKED_FIELDS or fields.get(f['key'],{}).get('visible',True) for f in fs)]
    def employee_validate(data,old=None):
        links=items('designation')
        assigned=next((r for r in links if r.name==data.get('role')),None)
        if assigned and assigned.data.get('group')!=data.get('designation_group'):raise ValueError('Choose the designation group linked to this designation.')
    def attendance_guard(kind,day,monthly=False):
        if kind!='staff':return
        locks=config('hrm:attendance-lock');key='monthly' if monthly else 'daily'
        cutoff=locks.get(key,'')
        if cutoff and (day.strftime('%Y-%m') if monthly else day.isoformat())<=cutoff:
            raise ValueError('This attendance period is locked in HRM Settings. Unlock it before changing attendance.')
    def weekday_schedule():
        result={}
        for i,label in enumerate(DAYS):
            off=request.form.get(f'off_{i}')=='1'
            row={'off':off}
            for key in ('in','out') if value('schedule_type')=='combined' else ('time',):
                key_off=off or request.form.get(f'{key}_off_{i}')=='1'
                row[key+'_off']=key_off
                time=value(f'{key}_{i}')
                if not key_off and not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d',time):raise ValueError('Enter a time or mark '+label+' off.')
                row[key]='' if key_off else time
            if value('schedule_type')=='combined':row['off']=row['in_off'] and row['out_off']
            result[str(i)]=row
        return result
    def resolved_shift(kind,person,data,day):
        if kind=='staff':
            assigned=config('hrm:shift-assignment').get(str(person.id),{})
            selected=assigned.get(str(day.weekday()),{})
            if selected.get('off'):return {'off':True,'in':'','out':''}
            result={'off':False,'in':'','out':''}
            for direction in ('in','out'):
                sid=selected.get(direction)
                row=db.session.get(SchoolSettingItem,int(sid)) if str(sid or '').isdigit() else None
                if row and row.kind=='shift-template' and row.data.get('direction')==direction:
                    daily=row.data.get('days',{}).get(str(day.weekday()),{})
                    result[direction]='' if daily.get('off') else daily.get('time','')
            return result
        shifts=items('student-shift',data.get('campus',''))
        matches=[r for r in shifts if person.class_name in r.data.get('classes',[]) and r.data.get('section','') in ('',data.get('section',''))]
        matches.sort(key=lambda r:bool(r.data.get('section')),reverse=True)
        return matches[0].data.get('days',{}).get(str(day.weekday()),{}) if matches else {}
    def display_name(typ):return config('exam:display').get(typ.lower(),'') or typ
    def formatted_marks(value):
        if value is None:return '—'
        return f"{value:.{int(config('exam:display').get('decimals',2))}f}"
    def grade_for(campus,cls,percentage):
        link=next((r for r in items('class-grading',campus) if cls in r.data.get('classes',[])),None)
        policy=db.session.get(SchoolSettingItem,link.data['policy']) if link else None
        if not policy:return ('','')
        n=Decimal(str(percentage))
        band=next((b for b in policy.data['bands'] if Decimal(b['min'])<=n<=Decimal(b['max'])),None)
        return (band['grade'],band['remarks']) if band else ('','')
    def subject_allowed(campus,cls,subject):
        links=items('class-subjects',campus)
        link=next((r for r in links if r.name==cls),None)
        return not link or subject in link.data.get('subjects',[])
    def exam_types(campus):return [r.name for r in items('test-type',campus)]
    def tags(module):return list(dict.fromkeys(CAMPUS_TAGS+(EMP_TAGS if module=='hrm' else STUDENT_TAGS)))
    def expand(text,values,html=False):
        def sub(match):
            key=match.group(1)
            if key not in values:return match.group(0)
            return str(escape(str(values[key]))) if html else str(values[key])
        return re.sub(r'\[([A-Za-z0-9_]+)\]',sub,text)
    def campus_values(campus):
        p=db.session.get(app.extensions['institute_setup_models']['profile'],1)
        data=p.data if p else {}
        return dict(institute_name=data.get('name','SchoolFlow'),campus_name=campus,campus_address=data.get('address',''),campus_contact=data.get('contact',''),slogan=data.get('slogan',''),todayDate=date.today().isoformat(),color_primary='#176b4a',color_secondary='#e7f3ec',color_3='#ffffff',color_4='#454b48')
    def branding(module,layout,part,campus='',values=None):
        rows=items(module+'-branding',campus)
        row=next((r for r in rows if r.name==layout),None)
        if not row and campus:row=next((r for r in items(module+'-branding','') if r.name==layout),None)
        if not row:return Markup('')
        html=expand(row.data.get(part,''),{**campus_values(campus),**(values or {})},True)
        # Only this server-created image may use the private school logo path.
        p=db.session.get(app.extensions['institute_setup_models']['profile'],1)
        logo=Markup('<img src="'+url_for('institute_setup.logo')+'" alt="School logo" style="max-width:90px;max-height:90px">') if p and p.logo_mime else ''
        return Markup(html.replace('[institute_logo]',str(logo)))

    @app.context_processor
    def settings_context():return dict(settings_branding=branding,mark_display=display_name,format_marks=formatted_marks)

    def catalog_mutation(page):
        category=CATALOG_PAGES[page];sid=value('id')
        if sid and not sid.isdigit():raise ValueError('Choose a valid catalog entry.')
        row=db.get_or_404(rm['settings'],int(sid)) if sid.isdigit() else None
        if row and row.category!=category:abort(404)
        action=value('action');name=value('name',action!='delete');old=row.value if row else ''
        # Catalogs are shared: referenced names cannot be silently renamed or removed.
        used=False
        if old:
            for d in rm['employee'].query.all():
                field={'department':'department','designation_group':'designation_group','designation':'role','employment_type':'employment_type'}[category]
                if d.data.get(field)==old:used=True
            if category=='designation' and Employee.query.filter_by(role=old).first():used=True
            if category=='designation_group' and any(r.data.get('group')==old for r in items('designation')):used=True
            if category=='designation' and any(old in r.data.get('designations',[]) for r in items('shift-template')):used=True
        if used and (action=='delete' or name!=old):raise ValueError('This name is in use. Keep it for existing records and add another option instead.')
        meta=next((r for r in items(category) if r.name==old),None) if old else None
        version(meta)
        if action=='delete':
            if not row:abort(404)
            db.session.delete(row)
            if meta:db.session.delete(meta)
        else:
            if rm['settings'].query.filter_by(category=category,value=name).filter(rm['settings'].id!=(row.id if row else 0)).first():raise ValueError('This option already exists.')
            data={'group':choice('group','designation_group')} if category=='designation' else {}
            if used and meta and category=='designation' and data['group']!=meta.data.get('group'):raise ValueError('This designation is used. Keep its group stable and create a new designation instead.')
            if row:row.value=name
            else:db.session.add(rm['settings'](category=category,value=name,class_name=''))
            save_item(category,name,data,row=meta)
        audit('Update HRM catalog',category=category,name=name,action=action)

    def lock_mutation():
        old=config('hrm:attendance-lock');action=value('action') or 'save';version(setting('hrm:attendance-lock'))
        if action=='save':
            daily=value('daily');monthly=value('monthly')
            if daily:date.fromisoformat(daily)
            if monthly:
                if not re.fullmatch(r'\d{4}-\d{2}',monthly):raise ValueError('Enter a valid month.')
                date.fromisoformat(monthly+'-01')
            data=dict(daily=daily,monthly=monthly)
        elif action in ('unlock-daily','unlock-monthly'):
            data=dict(old);key='daily' if action=='unlock-daily' else 'monthly'
            if not data.get(key):raise ValueError('No saved cutoff to unlock.')
            if key=='daily':data[key]=(date.fromisoformat(data[key])-timedelta(days=1)).isoformat()
            else:
                # Stored monthly cutoffs are month precision; crossing its start
                # by one day reopens precisely that last locked month.
                data[key]=(date.fromisoformat(data[key]+'-01')-timedelta(days=1)).strftime('%Y-%m')
        else:raise ValueError('Choose a valid lock action.')
        save_config('hrm:attendance-lock',data);audit('Change attendance cutoff',before=old,after=data,action=action)

    @bp.route('/<module>',defaults={'page':None})
    @bp.route('/<module>/<page>',methods=['GET','POST'])
    def index(module,page):
        if module not in ('exam','hrm'):abort(404)
        pages=EXAM_PAGES if module=='exam' else HRM_PAGES
        if page is None:page=pages[0][0]
        if page not in dict(pages):abort(404)
        key=module+':'+page;cfg=setting(key);data=config(key);kind=page;preview=None
        kinds={'subject-groups':'subject-group','subjects':'subject','test-types':'test-type','grading':'grading','class-grading':'class-grading','class-subjects':'class-subjects','student-shifts':'student-shift','shift-templates':'shift-template','branding':module+'-branding','print-templates':'print-template','allowances':'allowance'}
        kind=kinds.get(page,page)
        row=None
        if request.args.get('edit','').isdigit():
            row=db.get_or_404(SchoolSettingItem,int(request.args['edit']))
            if row.kind!=kind:abort(404)
        if request.method=='POST':
            action=value('action') or 'save'
            allowed={'employee-fields':('save','reset'),'attendance-lock':('save','unlock-daily','unlock-monthly'),'display':('save',),'sms':('save',),'weightage':('save',),'branding':('save','preview','delete'),'print-templates':('save','preview','delete')}.get(page,('save','delete'))
            if action not in allowed:raise ValueError('Choose a valid action.')
            if page in CATALOG_PAGES:catalog_mutation(page)
            elif page=='attendance-lock':lock_mutation()
            elif page=='employee-fields':
                if action=='reset':save_config(key,{})
                else:
                    data={}
                    for _,fs in EMPLOYEE_SECTIONS:
                        for f in fs:
                            k=f['key'];visible=k in LOCKED_FIELDS or bool(request.form.get('visible_'+k));required=k in LOCKED_FIELDS or bool(request.form.get('required_'+k))
                            if required and not visible:raise ValueError('A required field must be visible: '+f['label'])
                            data[k]=dict(visible=visible,required=required)
                    data['photo']={'visible':bool(request.form.get('visible_photo')),'required':bool(request.form.get('required_photo'))}
                    data['documents']={'visible':bool(request.form.get('visible_documents')),'required':bool(request.form.get('required_documents'))}
                    for k in ('photo','documents'):
                        if data[k]['required'] and not data[k]['visible']:raise ValueError('A required upload must be visible.')
                    save_config(key,data)
            elif page=='display':
                decimals=value('decimals',True)
                if decimals not in ('0','1','2','3','4'):raise ValueError('Choose 0–4 decimal places.')
                save_config(key,dict(written=value('written'),oral=value('oral'),decimals=int(decimals)))
            elif page=='sms':
                campus=choice('campus','campus');key=module+':sms:'+campus
                names=HRM_SMS if module=='hrm' else STUDENT_SMS
                payload={name:value('sms_'+str(i),limit=5000) for i,name in enumerate(names)}
                allowed=set(tags(module))
                if any(tag not in allowed for text in payload.values() for tag in re.findall(r'\[([A-Za-z0-9_]+)\]',text)):raise ValueError('Use only the listed template tags.')
                save_config(key,payload)
            elif page=='weightage':
                campus=choice('campus','campus');key='exam:weightage:'+campus;payload={}
                for r in items('test-type',campus):payload[str(r.id)]=number(request.form.get('weight_'+str(r.id),'0'))
                if sum(Decimal(x) for x in payload.values())>100:raise ValueError('Total weightage cannot exceed 100%.')
                save_config(key,payload)
            else:
                row=edit_item(kind);version(row)
                if action=='delete':
                    if not row:abort(404)
                    if kind=='shift-template' and any(str(row.id) in (d.get('in'),d.get('out')) for a in config('hrm:shift-assignment').values() for d in a.values()):raise ValueError('This shift is assigned. Reassign employees before deleting it.')
                    if kind=='grading' and any(r.data.get('policy')==row.id for r in items('class-grading')):raise ValueError('This grading policy is assigned to classes.')
                    if kind=='test-type' and (any(w.data.get('exam_test_type')==row.name and w.data.get('campus')==row.scope for w in W.query.filter(W.kind.in_(['awards','date-sheets'])).all()) or Decimal(config('exam:weightage:'+row.scope).get(str(row.id),'0'))):raise ValueError('This test type is in use.')
                    if kind=='subject' and (any(row.name in r.data.get('subjects',[]) for r in items('class-subjects')) or any(p.get('subject')==row.name for w in W.query.filter(W.kind.in_(['awards','date-sheets'])).all() for p in w.data.get('papers',[]))):raise ValueError('This subject is in use.')
                    if kind=='subject-group' and any(r.data.get('group')==row.name for r in items('subject')):raise ValueError('This group contains subjects.')
                    if kind=='subject':
                        if any(row.name in r.data.get('subjects',[]) for r in rm['student'].query.all()):raise ValueError('This subject is saved on student records.')
                        rm['settings'].query.filter_by(category='subject',value=row.name,class_name='').delete()
                    if kind=='allowance' and any(any(a.get('id')==row.id for a in w.data.get('allowances',[])) for w in W.query.filter_by(kind='salary-plans').all()):raise ValueError('This pay head is used by a salary plan.')
                    db.session.delete(row)
                else:
                    name=value('name',True);scope='';payload={}
                    if row and kind in ('subject-group','test-type') and row.name!=name:raise ValueError('Keep this configured name stable; add another option instead.')
                    if kind in ('test-type','class-subjects','class-grading','student-shift',module+'-branding','print-template'):scope=choice('campus','campus',kind!='print-template' and page!='branding')
                    if row and kind=='test-type' and scope!=row.scope:raise ValueError('Keep a test type at its original campus; create another type for a different campus.')
                    if kind=='subject':
                        group=value('group',True)
                        if group not in [r.name for r in items('subject-group')]:raise ValueError('Choose a subject group.')
                        payload=dict(group=group,grading='Marks',diary=bool(request.form.get('diary')))
                        # Canonical subject catalog is used by admissions, marks and reports.
                        if row and row.name!=name:raise ValueError('Keep a subject name stable; add another subject instead.')
                        if not rm['settings'].query.filter_by(category='subject',value=name,class_name='').first():db.session.add(rm['settings'](category='subject',value=name,class_name=''))
                    elif kind=='class-subjects':
                        name=choice('name','class_name');subjects=request.form.getlist('subjects')
                        if not subjects or any(s not in options('subject') for s in subjects):raise ValueError('Choose configured subjects.')
                        payload={'subjects':list(dict.fromkeys(subjects))}
                    elif kind=='class-grading':
                        cls=request.form.getlist('classes');policy=value('policy',True)
                        p=db.session.get(SchoolSettingItem,int(policy)) if policy.isdigit() else None
                        if not p or p.kind!='grading' or not cls or any(c not in options('class_name') for c in cls):raise ValueError('Choose classes and a grading policy.')
                        if any(set(cls)&set(r.data['classes']) for r in items(kind,scope) if not row or r.id!=row.id):raise ValueError('A selected class already has a grading policy. Edit its assignment.')
                        payload={'classes':cls,'policy':p.id}
                    elif kind=='grading':
                        bands=[]
                        for a,b,g,r in zip(request.form.getlist('minimum'),request.form.getlist('maximum'),request.form.getlist('grade'),request.form.getlist('remarks')):
                            if not any((a,b,g,r)):continue
                            low=number(a);high=number(b)
                            if Decimal(low)>Decimal(high) or not g.strip() or len(g)>60 or len(r)>1000:raise ValueError('Check grade bands and remarks.')
                            bands.append(dict(min=low,max=high,grade=g.strip(),remarks=r.strip()))
                        bands.sort(key=lambda b:Decimal(b['min']))
                        if not bands or any(Decimal(a['max'])>=Decimal(b['min']) for a,b in zip(bands,bands[1:])):raise ValueError('Add non-overlapping grade bands.')
                        payload={'bands':bands,'final_remarks':value('final_remarks',limit=1000)}
                    elif kind in ('student-shift','shift-template'):
                        if kind=='student-shift':
                            cls=request.form.getlist('classes');section=choice('section','section',False)
                            if not cls or any(c not in options('class_name') for c in cls):raise ValueError('Choose campus classes.')
                            maps=app.extensions['institute_setup_helpers']['payload']().get('maps',{})
                            if scope in maps and any(c not in {m['class_name'] for m in maps[scope]} for c in cls):raise ValueError('Choose classes enabled at this campus.')
                            if any(set(cls)&set(r.data.get('classes',[])) and section==r.data.get('section','') for r in items(kind,scope) if not row or r.id!=row.id):raise ValueError('A selected class/section already has a schedule. Edit it instead.')
                            payload=dict(classes=cls,section=section)
                            if value('schedule_type')!='combined':raise ValueError('Use the combined In and Out schedule.')
                        else:
                            direction=value('direction',True)
                            if direction not in ('in','out'):raise ValueError('Choose In or Out.')
                            ds=request.form.getlist('designations')
                            if any(d not in options('designation') for d in ds):raise ValueError('Choose configured designations.')
                            if row:
                                assigned=config('hrm:shift-assignment')
                                for sid,schedule in assigned.items():
                                    employee=db.session.get(Employee,int(sid))
                                    for daily in schedule.values():
                                        if str(row.id) in (daily.get('in'),daily.get('out')) and (direction!=row.data['direction'] or (ds and employee and employee.role not in ds)):raise ValueError('This template is assigned. Reassign employees before changing its type or applicability.')
                            payload=dict(direction=direction,designations=ds)
                        payload['days']=weekday_schedule()
                    elif kind=='allowance':
                        typ=value('type',True)
                        if typ not in ('Earning','Deduction'):raise ValueError('Choose Earning or Deduction.')
                        payload={'type':typ,**{k:bool(request.form.get(k)) for k in ('basic','bonusable','deductible','incrementable')}}
                    elif page in ('branding','print-templates'):
                        if page=='branding' and name not in (HRM_LAYOUTS if module=='hrm' else EXAM_LAYOUTS):raise ValueError('Choose a report layout.')
                        payload={k:clean_html(value(k,limit=80000)) for k in ('header','body','footer')}
                        allowed=set(tags(module))
                        if any(tag not in allowed for text in payload.values() for tag in re.findall(r'\[([A-Za-z0-9_]+)\]',text)):raise ValueError('Use only the listed tags.')
                        if action=='preview':
                            from types import SimpleNamespace
                            row=SimpleNamespace(id=row.id if row else '',version=row.version if row else 0,name=name,scope=scope,data=payload)
                            preview={k:Markup(expand(v,{**campus_values(scope),'emp_name':'Fictional Employee','studentName':'Fictional Student'},True)) for k,v in payload.items()}
                        elif action!='save':raise ValueError('Choose save or preview.')
                    if preview is None:save_item(kind,name,payload,scope,row)
            if preview is None:
                audit('Save school settings',module=module,page=page);commit();flash('Settings saved.','success')
                return redirect(url_for('school_settings.index',module=module,page=page,campus=request.form.get('campus','')))
        campus=request.values.get('campus','');campuses=options('campus')
        if not campus and campuses:campus=campuses[0]
        if page in ('sms','weightage'):
            key=module+':'+page+':'+campus;cfg=setting(key);data=config(key)
        if page in CATALOG_PAGES:
            rows=rm['settings'].query.filter_by(category=CATALOG_PAGES[page]).order_by(rm['settings'].value).all()
            meta={r.name:r for r in items(CATALOG_PAGES[page])}
            edit=request.args.get('catalog_edit','');catalog_edit=next((r for r in rows if str(r.id)==edit),None)
        else:rows=items(kind);meta={};catalog_edit=None
        if request.args.get('export')=='xlsx':
            from openpyxl import Workbook
            book=Workbook();sheet=book.active;sheet.title='Settings'
            sheet.append(['Name / Layout','Campus','Details'])
            def cell(v):
                text=str(v)
                return "'"+text if text.lstrip().startswith(('=','+','-','@')) else text
            for r in rows:
                label=r.value if page in CATALOG_PAGES else r.name
                scope='' if page in CATALOG_PAGES else r.scope
                details={} if page in CATALOG_PAGES else r.data
                text='; '.join(str(k).replace('_',' ').title()+': '+str(v) for k,v in details.items())
                sheet.append([cell(label),cell(scope),cell(text)])
            sheet.column_dimensions['A'].width=36;sheet.column_dimensions['B'].width=26;sheet.column_dimensions['C'].width=90
            sheet.freeze_panes='A2';sheet.auto_filter.ref=sheet.dimensions
            output=io.BytesIO();book.save(output)
            response=app.response_class(output.getvalue(),mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet');response.headers['Content-Disposition']='attachment; filename="schoolflow-'+module+'-'+page+'.xlsx"'
            return response
        return render_template('school_settings.html',title=dict(pages)[page],module=module,page=page,pages=pages,rows=rows,row=row,cfg=cfg,data=data,options=options,items=items,campus=campus,campuses=campuses,days=DAYS,fields=EMPLOYEE_SECTIONS,locked_fields=LOCKED_FIELDS,sms_names=HRM_SMS if module=='hrm' else STUDENT_SMS,tags=tags(module),layouts=HRM_LAYOUTS if module=='hrm' else EXAM_LAYOUTS,preview=preview,meta=meta,catalog_edit=catalog_edit)

    @bp.route('/hrm/assign-shifts',methods=['GET','POST'])
    def assign_shifts():
        cfg=setting('hrm:shift-assignment');data=config('hrm:shift-assignment');templates=items('shift-template');byid={str(r.id):r for r in templates}
        employees=Employee.query.order_by(Employee.id).all();details=app.extensions['record_helpers']['raw_many']('employee',employees)
        if request.method=='POST':
            version(cfg);action=value('action');updated=dict(data)
            ids=request.form.getlist('employee_ids')
            if action=='copy':
                source=value('source',True);person=next((e for e in employees if str(e.id)==source),None)
                if not person or source not in data:raise ValueError('Choose an employee with a saved schedule.')
                targets=[e for e in employees if e.role==person.role and details.get(e.id,{}).get('campus','')==details.get(person.id,{}).get('campus','')]
                for target in targets:
                    for d in data[source].values():
                        for direction in ('in','out'):
                            r=byid.get(d.get(direction))
                            if r and r.data.get('designations') and target.role not in r.data['designations']:raise ValueError('A template is not applicable to this designation.')
                    updated[str(target.id)]=data[source]
            elif action=='save':
                if any(not s.isdigit() or int(s) not in {e.id for e in employees} for s in ids):raise ValueError('Invalid employee selection.')
                for sid in ids:
                    person=next(e for e in employees if str(e.id)==sid);schedule={}
                    for i in range(7):
                        d={'off':bool(request.form.get(f'off_{sid}_{i}'))}
                        for direction in ('in','out'):
                            s=value(f'{direction}_{sid}_{i}');r=byid.get(s)
                            if s and (not r or r.data['direction']!=direction or (r.data['designations'] and person.role not in r.data['designations'])):raise ValueError('Choose an applicable '+direction+' template for '+person.name+'.')
                            d[direction]=s
                        schedule[str(i)]=d
                    updated[sid]=schedule
            else:raise ValueError('Choose a valid shift assignment action.')
            save_config('hrm:shift-assignment',updated);audit('Assign employee shifts',action=action,employees=ids);commit();return redirect(url_for('school_settings.assign_shifts'))
        campus=request.args.get('campus','');employee=request.args.get('employee','')
        employees=[e for e in employees if (not campus or details.get(e.id,{}).get('campus')==campus) and (not employee or str(e.id)==employee) and (not request.args.get('unassigned') or not any(d.get('in') or d.get('out') or d.get('off') for d in data.get(str(e.id),{}).values()))]
        total=len(employees);page=max(1,request.args.get('p',1,type=int));pages=max(1,(total+24)//25);page=min(page,pages)
        return render_template('shift_assignments.html',title='Assign employee shifts',employees=employees[(page-1)*25:page*25],all_employees=Employee.query.order_by(Employee.name).all(),details=details,templates=templates,cfg=cfg,data=data,days=DAYS,options=options,page=page,pages=pages,total=total)

    @bp.route('/exam/results/<int:award_id>')
    def results(award_id):
        award=db.get_or_404(W,award_id)
        if award.kind!='awards':abort(404)
        scores=ops['score'].query.filter_by(award_id=award.id).all();pupils=Student.query.filter(Student.id.in_({s.student_id for s in scores})).order_by(Student.id).all()
        details=app.extensions['record_helpers']['raw_many']('student',pupils);rows=[]
        for pupil in pupils:
            saved={s.paper:s for s in scores if s.student_id==pupil.id};papers=award.data['papers'];complete=all(i in saved and (saved[i].obtained is not None or saved[i].state) for i in range(len(papers)))
            obtained=sum(Decimal(str(s.obtained or 0)) for s in saved.values());total=sum(Decimal(str(p['total'])) for p in papers);percent=obtained/total*100 if total and complete else None
            grade,remarks=grade_for(award.data.get('campus',''),award.data.get('class_name',''),percent) if percent is not None else ('','')
            rows.append(dict(student=pupil,details=details.get(pupil.id,{}),obtained=obtained,total=total,percentage=percent,grade=grade,remarks=remarks,complete=complete))
        return render_template('exam_results.html',title='Results · '+award.data['name'],award=award,rows=rows)

    @bp.get('/exam/weighted-results')
    def weighted_results():
        campus=request.args.get('campus','');cls=request.args.get('class_name','');session_name=request.args.get('academic_session','')
        types=items('test-type',campus);weights=config('exam:weightage:'+campus)
        selected=[(t,Decimal(weights.get(str(t.id),'0'))) for t in types if Decimal(weights.get(str(t.id),'0'))>0]
        total=sum(w for _,w in selected);rows=[]
        if campus and cls and session_name:
            if total!=100:raise ValueError('Set test-type weights to a total of 100% before producing weighted results.')
            # Every report is limited to an explicit session, campus and class.
            details_model=rm['student'];pupils=Student.query.join(details_model,details_model.student_id==Student.id).filter(Student.class_name==cls,details_model.data['campus'].as_string()==campus,details_model.data['academic_session'].as_string()==session_name).order_by(Student.id).all()
            pupil_details=app.extensions['record_helpers']['raw_many']('student',pupils)
            awards=[a for a in W.query.filter_by(kind='awards').all() if a.data.get('campus')==campus and a.data.get('class_name')==cls and a.data.get('academic_session')==session_name]
            scores=ops['score'].query.filter(ops['score'].award_id.in_([a.id for a in awards])).all();lookup={(s.award_id,s.student_id,s.paper):s for s in scores}
            for pupil in pupils:
                parts=[];complete=True;weighted=Decimal(0)
                for typ,weight in selected:
                    papers=[(a,i,p) for a in awards if a.data.get('exam_test_type')==typ.name and all(not a.data.get(k) or a.data[k]==pupil_details.get(pupil.id,{}).get(k) for k in ('section','gender','group_name')) for i,p in enumerate(a.data['papers'])]
                    obtained=Decimal(0);maximum=Decimal(0);marked=bool(papers)
                    for a,i,p in papers:
                        score=lookup.get((a.id,pupil.id,i));maximum+=Decimal(str(p['total']))
                        if not score or (score.obtained is None and not score.state):marked=False
                        elif score.obtained is not None:obtained+=Decimal(str(score.obtained))
                    pct=obtained/maximum*100 if marked and maximum else None
                    if pct is None:complete=False
                    else:weighted+=pct*weight/100
                    parts.append(dict(name=typ.name,weight=weight,percentage=pct))
                grade,remarks=grade_for(campus,cls,weighted) if complete else ('','')
                rows.append(dict(student=pupil,parts=parts,weighted=weighted if complete else None,grade=grade,remarks=remarks))
        return render_template('weighted_results.html',title='Weighted exam results',options=options,campus=campus,cls=cls,session_name=session_name,rows=rows,total=total)

    @bp.get('/hrm/designation-options')
    def designation_options():
        from flask import jsonify
        return jsonify({r.name:r.data.get('group','') for r in items('designation')})

    @bp.get('/exam/subject-options')
    def subject_options():
        from flask import jsonify
        maps={}
        for r in items('class-subjects'):maps.setdefault(r.scope,{})[r.name]=r.data.get('subjects',[])
        return jsonify(maps)

    def message_snapshots(subject,ids,audience):
        staff=audience in ('staff','teacher');module='hrm' if staff else 'exam';cls=Employee if staff else Student
        people=cls.query.filter(cls.id.in_(ids)).all();data=app.extensions['record_helpers']['raw_many']('employee' if staff else 'student',people);result=[]
        for p in people:
            d=data.get(p.id,{});campus=d.get('campus','');values=campus_values(campus)
            values.update(emp_name=p.name,emp_fname=d.get('father_name',''),emp_contact=p.phone or '',emp_cnic=d.get('cnic',''),studentName=p.name,fatherName=d.get('father',''),className=getattr(p,'class_name','') or '',sectionName=d.get('section',''),sid=p.id,rollNo=d.get('roll_no',''),SessionName=d.get('academic_session',''))
            name='Pay Salary' if subject=='Salary paid' else ''
            if subject=='Attendance':
                current=ops['daily'].query.filter_by(kind='staff' if staff else 'student',person_id=p.id,day=date.fromisoformat(request.form['day'])).first()
                name=current.status if current else ''
                if staff and name=='Leave':name='Full Day Leave'
                values.update(date=request.form['day'],todayDate=request.form['day'],time=current.time_in if current else '',qr_status=current.status if current else '',qr_att_status=current.status if current else '',qr_in_status=current.time_in if current else '')
            if name=='Pay Salary':
                salaries=ops['salary'].query.filter_by(employee_id=p.id).order_by(ops['salary'].month.desc()).all()
                selected={int(s) for s in request.form.getlist('ids') if s.isdigit()};salary=next((s for s in salaries if s.id in selected),None)
                if salary:values.update(salary_month=salary.month,earnings=f'{salary.earnings/100:.2f}',deductions=f'{salary.deductions/100:.2f}',net_salary=f'{salary.net/100:.2f}',salary_status='Paid',date=str(salary.paid_date),time='')
            body=config(module+':sms:'+campus).get(name) or subject
            result.append(dict(person_id=p.id,template=name,text=expand(body,values)))
        return result

    @bp.get('/hrm/print-template/<int:template_id>')
    def employee_print(template_id):
        template=db.get_or_404(SchoolSettingItem,template_id)
        if template.kind!='print-template':abort(404)
        employees=Employee.query.order_by(Employee.name).all();details=app.extensions['record_helpers']['raw_many']('employee',employees)
        employees=[e for e in employees if not template.scope or details.get(e.id,{}).get('campus')==template.scope]
        eid=request.args.get('employee_id','');person=next((e for e in employees if str(e.id)==eid),None)
        if eid and not person:abort(404)
        sections=None
        if person:
            d=details.get(person.id,{});values=campus_values(d.get('campus',''))
            aliases={'emp_id':person.employee_no,'emp_name':person.name,'emp_fname':d.get('father_name',''),'emp_father_name':d.get('father_name',''),'emp_cnic':d.get('cnic',''),'emp_email':d.get('email',''),'emp_dob':d.get('birth_date',''),'emp_contact':person.phone or '','emp_city':d.get('city',''),'emp_address':d.get('address',''),'department_name':d.get('department',''),'designation_name':person.role or '','emp_status':person.status,'emp_notes':d.get('notes',''),'emp_reference':d.get('reference',''),'emp_degrees':d.get('qualification_degree',''),'emp_documents':'','emp_qr':''}
            aliases.update({k:d.get(k,'') for k in ('home_phone','emergency_contact_name','emergency_contact_no','contact_relation','gender','marital_status','designation_group','employment_type','joining_date','bank_info','lecture_assigned','leaving_date','probation_from','probation_to')})
            female=d.get('gender')=='Female';aliases.update(son_daughter_of='Daughter of' if female else 'Son of',mr_ms='Ms.' if female else 'Mr.',he_she='she' if female else 'he',he_she_capital='She' if female else 'He',his_her='her' if female else 'his',his_her_capital='Her' if female else 'His',him_her='her' if female else 'him')
            values.update(aliases)
            sections={k:Markup(expand(template.data.get(k,''),values,True)) for k in ('header','body','footer')}
            photo=rm['file'].query.filter_by(owner_kind='employee',owner_id=person.id,photo=True).first()
            profile=db.session.get(app.extensions['institute_setup_models']['profile'],1)
            logo='<img src="'+url_for('institute_setup.logo')+'" style="max-width:90px" alt="School logo">' if profile and profile.logo_mime else ''
            picture='<img src="'+url_for('records.record_file',id=photo.id)+'" style="max-width:100px" alt="Employee photo">' if photo else ''
            sections={k:Markup(str(v).replace('[institute_logo]',logo).replace('[emp_photo]',picture)) for k,v in sections.items()}
        return render_template('employee_template_print.html',title=template.name,template=template,employees=employees,person=person,sections=sections)

    @bp.route('/hrm/monthly-attendance',methods=['GET','POST'])
    def monthly_attendance():
        month=request.values.get('month',date.today().strftime('%Y-%m'))
        if not re.fullmatch(r'\d{4}-\d{2}',month):raise ValueError('Choose a month.')
        first=date.fromisoformat(month+'-01');dates=[first+timedelta(days=i) for i in range(calendar.monthrange(first.year,first.month)[1])]
        employee_id=request.values.get('employee_id','');employees=Employee.query.order_by(Employee.name).all();person=next((e for e in employees if str(e.id)==employee_id),None)
        if employee_id and not person:abort(404)
        statuses=['Present','Absent','Late','Leave','Short Leave','Off Day','Death Leave','Paper Leave']
        if request.method=='POST':
            if not person:raise ValueError('Choose an employee.')
            attendance_guard('staff',first,monthly=True)
            for d in dates:
                status=value('status_'+d.isoformat())
                old=ops['daily'].query.filter_by(kind='staff',person_id=person.id,day=d).first()
                if status==(old.status if old else ''):continue
                attendance_guard('staff',d)
                if status and status not in statuses:raise ValueError('Choose a valid attendance status.')
                if not status:
                    if old:db.session.delete(old)
                elif old:old.status=status
                else:db.session.add(ops['daily'](kind='staff',person_id=person.id,day=d,status=status))
            audit('Save monthly staff attendance',employee=person.id,month=month);commit()
            return redirect(url_for('school_settings.monthly_attendance',month=month,employee_id=person.id))
        existing={r.day.isoformat():r for r in ops['daily'].query.filter_by(kind='staff',person_id=person.id).filter(ops['daily'].day>=dates[0],ops['daily'].day<=dates[-1]).all()} if person else {}
        return render_template('monthly_staff_attendance.html',title='Monthly Staff Attendance',details=app.extensions['record_helpers']['raw_many']('employee',[person]).get(person.id,{}) if person else {},employees=employees,person=person,month=month,dates=dates,existing=existing,statuses=statuses)

    app.extensions['school_settings_helpers']=dict(config=config,items=items,employee_sections=employee_sections,employee_validate=employee_validate,attendance_guard=attendance_guard,shift=resolved_shift,subject_allowed=subject_allowed,exam_types=exam_types,grade=grade_for,branding=branding,expand=expand,tags=tags,campus_values=campus_values,message_snapshots=message_snapshots)
    app.register_blueprint(bp)
