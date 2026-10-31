"""Class seats and explicit admission reviews, scoped to one institute DB.

A cohort is campus + current class + academic session, across its sections.
All seat-changing student saves, reviews and limit changes share a DB write gate.
"""
from collections import Counter
from datetime import datetime, timezone
import hmac
from flask import Blueprint,abort,flash,redirect,render_template,request,session,url_for
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import StaleDataError


def configure_admission_capacity(app,db,Student):
    bp=Blueprint('admission_limits',__name__,url_prefix='/workspace')
    rm=app.extensions['record_models'];Details=rm['student'];Audit=app.extensions['ops_models']['audit']

    class AdmissionCapacity(db.Model):
        campus=db.Column(db.String(160),primary_key=True)
        class_name=db.Column(db.String(160),primary_key=True)
        academic_session=db.Column(db.String(160),primary_key=True)
        seats=db.Column(db.Integer)  # None is explicitly unlimited; zero closes admissions.
        version=db.Column(db.Integer,nullable=False,default=1)
        __mapper_args__={'version_id_col':version}

    class AdmissionWriteGate(db.Model):
        id=db.Column(db.Integer,primary_key=True)
        revision=db.Column(db.Integer,nullable=False,default=0)

    app.extensions['admission_capacity_models']=dict(capacity=AdmissionCapacity,gate=AdmissionWriteGate)

    def lock():
        engine=db.session.get_bind(mapper=AdmissionWriteGate.__mapper__)
        insert=postgres_insert if engine.dialect.name=='postgresql' else sqlite_insert
        statement=insert(AdmissionWriteGate).values(id=1,revision=1)
        db.session.execute(statement.on_conflict_do_update(index_elements=['id'],set_={'revision':AdmissionWriteGate.revision+1}))

    def choices(category):
        return sorted({row.value for row in rm['settings'].query.filter_by(category=category).all()})

    def cohort(student,data):
        return data.get('campus',''),student.class_name or '',data.get('academic_session','')

    def active_counts(exclude=None):
        active=Student.query.filter_by(status='Active').all()
        details={row.student_id:row.data for row in Details.query.all()}
        return Counter(cohort(s,details.get(s.id,{})) for s in active if s.id!=exclude)

    def guard(data,obj=None):
        # Acquire the write lock before counting seats, including unlimited
        # cohorts, so a simultaneous limit edit cannot race a student save.
        lock()
        if obj:db.session.refresh(obj)
        setup=app.extensions.get('institute_setup_helpers')
        if setup:
            old_data=app.extensions['record_helpers']['read_many']('student',[obj])[0][1] if obj else None
            errors=setup['validate_admission'](data,old_data,fresh=True)
            if errors:raise ValueError(next(iter(errors.values())))
        if data.get('status')!='Active':return False
        target=(data.get('campus',''),data.get('class_name',''),data.get('academic_session',''))
        old=Details.query.filter_by(student_id=obj.id).populate_existing().first() if obj else None
        old_cohort=cohort(obj,old.data if old else {}) if obj else None
        if obj and obj.status=='Active' and target==old_cohort:return False
        limit=db.session.get(AdmissionCapacity,target)
        if limit and limit.seats is not None and active_counts(exclude=obj.id if obj else None)[target]>=limit.seats:
            if obj and obj.status=='Active':
                raise ValueError('The destination class has no available seats. This enrolled student was not transferred. Increase the limit or choose another class.')
            data['status']='Waiting'
            return True
        return False

    def capacity_rows():
        counts=active_counts()
        return [dict(campus=r.campus,class_name=r.class_name,academic_session=r.academic_session,seats=r.seats,
                     occupied=counts[(r.campus,r.class_name,r.academic_session)],
                     available=None if r.seats is None else max(0,r.seats-counts[(r.campus,r.class_name,r.academic_session)]),version=r.version)
                for r in AdmissionCapacity.query.order_by(AdmissionCapacity.campus,AdmissionCapacity.class_name,AdmissionCapacity.academic_session).all()]

    @bp.before_request
    def csrf():
        if request.method=='POST':
            token=request.form.get('_csrf','')
            if not token or not hmac.compare_digest(token,session.get('record_csrf','')):abort(400,'Reload the admissions form.')

    @bp.errorhandler(ValueError)
    def invalid(error):
        db.session.rollback()
        return render_template('operation_error.html',title='Check admission settings',error=str(error)),422

    @bp.route('/admission-capacity',methods=['GET','POST'])
    def capacity():
        if request.method=='POST':
            key=tuple(request.form.get(k,'').strip() for k in ('campus','class_name','academic_session'))
            for field,value in zip(('campus','class_name','academic_session'),key):
                if value not in choices(field):raise ValueError('Choose a configured campus, class and academic session.')
            unlimited=request.form.get('unlimited')=='on'
            value=request.form.get('seats','').strip()
            if not unlimited and (not value.isdigit() or len(value)>6 or int(value)>100000):
                raise ValueError('Enter a seat limit from 0 to 100,000, or choose No seat limit.')
            lock()
            row=db.session.get(AdmissionCapacity,key,populate_existing=True)
            try:version=int(request.form.get('version','-1'))
            except ValueError:raise ValueError('Reload before changing the seat limit.')
            if version!=(row.version if row else 0):raise ValueError('This seat limit changed in another tab. Reload before saving.')
            seats=None if unlimited else int(value)
            occupied=active_counts()[key]
            if seats is not None and seats<occupied:raise ValueError(f'{occupied} students are already enrolled. The limit cannot be lower than that count.')
            if row:row.seats=seats
            else:db.session.add(AdmissionCapacity(campus=key[0],class_name=key[1],academic_session=key[2],seats=seats))
            db.session.add(Audit(action='Change admission seats',data=dict(campus=key[0],class_name=key[1],academic_session=key[2],seats=seats,owner_id=session.get('owner_id'))))
            try:db.session.commit()
            except (IntegrityError,StaleDataError):db.session.rollback();raise ValueError('Seat settings changed. Reload and try again.')
            flash('Seat limit saved. Waiting students require an explicit approval.','success')
            return redirect(url_for('admission_limits.capacity',campus=key[0],class_name=key[1],academic_session=key[2]))
        key=tuple(request.args.get(k,'') for k in ('campus','class_name','academic_session'))
        row=db.session.get(AdmissionCapacity,key) if all(key) else None
        return render_template('admission_capacity.html',title='Class Admission Seats',choices=choices,rows=capacity_rows(),selected=key,record=row)

    def filtered_rows():
        query=request.values.get('q','').strip().lower()[:160]
        details={row.student_id:row.data for row in Details.query.all()}
        rows=[]
        for student in Student.query.order_by(Student.id).all():
            data=details.get(student.id,{})
            if query and query not in (student.name+' '+student.admission_no).lower():continue
            if any(request.values.get(k) and request.values[k]!=(student.class_name if k=='class_name' else data.get(k,'')) for k in ('campus','class_name','academic_session')):continue
            rows.append((student,data))
        return rows

    @bp.route('/admission-approvals')
    def approvals():
        tab=request.args.get('tab','Waiting')
        tabs={'Waiting':'Waiting','Allowed':'Active','Refused':'Refused','All':None}
        if tab not in tabs:raise ValueError('Choose a valid admissions tab.')
        all_rows=filtered_rows()
        counts={name:sum(not status or s.status==status for s,d in all_rows) for name,status in tabs.items()}
        rows=[row for row in all_rows if not tabs[tab] or row[0].status==tabs[tab]]
        try:page=max(1,int(request.args.get('page','1')));size=int(request.args.get('size','25'))
        except ValueError:raise ValueError('Choose valid pagination.')
        if size not in (25,50,100):raise ValueError('Choose 25, 50 or 100 rows.')
        pages=max(1,(len(rows)+size-1)//size);page=min(page,pages)
        return render_template('admission_approvals.html',title='Admission Approvals',choices=choices,tabs=tabs,tab=tab,counts=counts,
                               rows=rows[(page-1)*size:page*size],page=page,pages=pages,size=size,total=len(rows))

    def review():
        action=request.form.get('action')
        if action not in ('approve','reject'):raise ValueError('Choose Allow or Refuse.')
        raw=request.form.getlist('ids')
        if not raw or len(raw)>100 or any(not n.isdigit() or len(n)>12 or int(n)<1 for n in raw):raise ValueError('Select up to 100 valid waiting students.')
        ids={int(n) for n in raw}
        lock()
        # Refresh objects after obtaining the gate: a second reviewer may have
        # already changed their status while this request was waiting.
        db.session.expire_all()
        rows=[(s,d) for s,d in filtered_rows() if s.id in ids]
        if len(rows)!=len(ids) or any(s.status!='Waiting' for s,d in rows):
            raise ValueError('A selected record changed or is outside these filters. Reload and select waiting students only.')
        if action=='approve':
            setup=app.extensions.get('institute_setup_helpers')
            if setup:
                for student,data in rows:
                    errors=setup['validate_admission']({**data,'class_name':student.class_name,'status':'Active'},fresh=True)
                    if errors:raise ValueError('Admission cannot be allowed: '+next(iter(errors.values())))
            requested=Counter(cohort(s,d) for s,d in rows);occupied=active_counts()
            for key,number in requested.items():
                limit=db.session.get(AdmissionCapacity,key)
                if limit and limit.seats is not None and occupied[key]+number>limit.seats:
                    raise ValueError('Not enough available seats in '+key[1]+'. No students were approved. Increase the limit or select fewer students.')
        status='Active' if action=='approve' else 'Refused'
        for student,data in rows:
            student.status=status
            detail=Details.query.filter_by(student_id=student.id).first()
            if detail:detail.data={**detail.data,'status':status};detail.updated_at=datetime.now(timezone.utc)
            db.session.add(rm['event'](owner_kind='student',owner_id=student.id,action='Admission allowed' if action=='approve' else 'Admission refused'))
        db.session.add(Audit(action='Admission '+('allow' if action=='approve' else 'refuse'),data=dict(ids=sorted(ids),status=status,owner_id=session.get('owner_id'))))
        db.session.commit()
        flash(f'{len(rows)} admission(s) '+('allowed.' if action=='approve' else 'refused.'),'success')
        filters={k:request.form.get(k,'') for k in ('q','campus','class_name','academic_session')}
        return redirect(url_for('admission_limits.approvals',tab='Waiting',**filters))

    app.extensions['admission_capacity']=dict(guard=guard,review=review,rows=capacity_rows,lock=lock)
    app.register_blueprint(bp)
