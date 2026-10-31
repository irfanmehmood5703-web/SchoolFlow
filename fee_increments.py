"""Explicit, previewed batch increments using the individual-plan calculation."""
import copy,hashlib,hmac,re
from datetime import date
from flask import Blueprint,abort,flash,g,redirect,render_template,request,session,url_for
from itsdangerous import BadData,URLSafeTimedSerializer
from sqlalchemy import and_,String,cast
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import StaleDataError
from student_fee_plans import fee_percentage,increment_lines


def configure_fee_increments(app,db,Student):
    bp=Blueprint('fee_increments',__name__,url_prefix='/workspace/core/fees/increments')
    P=app.extensions['student_fee_plan_model'];rm=app.extensions['record_models'];Audit=app.extensions['ops_models']['audit'];Details=rm['student']
    def signer():return URLSafeTimedSerializer(app.config['SECRET_KEY'],salt='schoolflow-fee-increment-v1')
    def actor():return dict(scope=(getattr(g,'school_identity',None) or {}).get('scope'),institute=session.get('institute_id'),owner=session.get('owner_id'),demo=bool(session.get('demo')),csrf=hashlib.sha256(session.get('record_csrf','').encode()).hexdigest())
    def latest_query():
        latest=db.session.query(P.student_id,db.func.max(P.effective).label('effective')).group_by(P.student_id).subquery()
        return P.query.join(latest,and_(P.student_id==latest.c.student_id,P.effective==latest.c.effective))
    def preview_data(ids,params):
        people={s.id:s for s in Student.query.filter(Student.id.in_(ids)).all()}
        plans={p.student_id:p for p in latest_query().filter(P.student_id.in_(ids)).all()}
        data=app.extensions['record_helpers']['raw_many']('student',list(people.values()));rows=[];sources=[]
        pct=fee_percentage(params['percentage'])
        for sid in ids:
            s=people.get(sid);p=plans.get(sid);d=data.get(sid,{})
            if not s or s.status!='Active' or not p:raise ValueError('Every selected student must still be active with a saved fee plan. Reload the selection.')
            if (params['campus'] and d.get('campus','')!=params['campus']) or (params['class_name'] and s.class_name!=params['class_name']):raise ValueError('A selected student is outside the chosen campus/class. Reload the selection.')
            if params['effective']<p.effective:raise ValueError('A selected student has a later effective plan. Historical plans cannot be changed in this batch.')
            lines=increment_lines(p.data['lines'],pct,params['effective']==p.effective)
            after=copy.deepcopy(p.data);after.update(lines=lines,percentage=str(pct),year=params['year'],bulk_increment=dict(effective=params['effective'],note=params['note']))
            rows.append(dict(student=s,details=d,source=p,after=after,lines=[dict(old=old,new=new) for old,new in zip(p.data['lines'],lines)],old_net=sum(x['net'] for x in p.data['lines']),net=sum(x['net'] for x in lines),increment=sum(x['increment'] for x in lines),arrears=sum(x['arrears'] for x in lines)))
            sources.append([s.id,p.id,p.version,d.get('campus',''),s.class_name,s.name])
        return rows,sources
    @bp.before_request
    def protect():
        if request.method=='POST':
            token=request.form.get('_csrf','')
            if not token or not hmac.compare_digest(token,session.get('record_csrf','')):abort(400,'Reload this form.')
            app.extensions['admission_capacity']['lock']()
    @bp.errorhandler(ValueError)
    def invalid(error):
        db.session.rollback();return render_template('operation_error.html',title='Check fee increment',error=str(error)),422
    @bp.route('',methods=['GET','POST'])
    def index():
        if request.method=='POST':
            action=request.form.get('action')
            if action=='preview':
                raw=request.form.getlist('student_ids')
                if not raw or len(raw)>100 or any(not re.fullmatch(r'[1-9]\d*',x) for x in raw):raise ValueError('Select 1–100 students from the displayed page.')
                ids=sorted({int(x) for x in raw})
                effective=request.form.get('effective','')
                if not re.fullmatch(r'\d{4}-\d{2}',effective):raise ValueError('Choose a valid effective month.')
                try:date.fromisoformat(effective+'-01')
                except ValueError:raise ValueError('Choose a valid effective month.')
                year=request.form.get('year','').strip();note=request.form.get('note','').strip()
                if not year.isdigit() or not 1900<=int(year)<=9999:raise ValueError('Enter a fee-plan year from 1900 to 9999.')
                if len(note)>1000:raise ValueError('Use an increment note up to 1,000 characters.')
                if 'percentage' not in request.form or not request.form['percentage'].strip():raise ValueError('Enter the percentage explicitly.')
                params=dict(effective=effective,year=year,note=note,percentage=str(fee_percentage(request.form['percentage'])),campus=request.form.get('campus',''),class_name=request.form.get('class_name',''))
                rows,sources=preview_data(ids,params)
                token=signer().dumps(dict(v=1,actor=actor(),ids=ids,params=params,sources=sources))
                response=render_template('fee_increment_preview.html',title='Review bulk fee increment',rows=rows,params=params,token=token,total_before=sum(r['old_net'] for r in rows),total_after=sum(r['net'] for r in rows))
                db.session.rollback()  # Preview releases the write gate without persisting anything.
                return response
            if action!='apply':raise ValueError('Preview the selected students before applying an increment.')
            token=request.form.get('preview_token','')
            if len(token)>65536:raise ValueError('Invalid preview. Preview the batch again.')
            try:payload=signer().loads(token,max_age=900)
            except BadData:raise ValueError('This preview expired or changed. Preview the batch again.')
            if not isinstance(payload,dict) or payload.get('v')!=1 or payload.get('actor')!=actor():raise ValueError('This preview belongs to another institute or sign-in session. Preview again.')
            params=payload['params'];rows,sources=preview_data(payload['ids'],params)
            if sources!=payload['sources']:raise ValueError('A student or fee plan changed after preview. Preview again; no batch changes were saved.')
            changes=[]
            for row in rows:
                source=row['source'];target=source if source.effective==params['effective'] else None
                before=copy.deepcopy(target.data) if target else None
                if target and target.data==row['after']:continue
                if target:target.data=row['after']
                else:db.session.add(P(student_id=source.student_id,effective=params['effective'],data=row['after']))
                changes.append(dict(student_id=source.student_id,source_id=source.id,source_version=source.version,before=before,after=row['after']))
            if changes:db.session.add(Audit(action='Apply bulk fee increment',data=dict(effective=params['effective'],percentage=params['percentage'],year=params['year'],note=params['note'],owner_id=session.get('owner_id'),changes=changes)))
            try:db.session.commit()
            except (IntegrityError,StaleDataError):db.session.rollback();raise ValueError('A fee plan changed during this batch. Preview again; no batch changes were saved.')
            flash(f'{len(changes)} fee plans saved; {len(rows)-len(changes)} were already unchanged. Existing challans retain their saved amounts.','success')
            return redirect(url_for('student_plans.index',mode='update',campus=params['campus'],class_name=params['class_name']))
        try:page=max(1,int(request.args.get('page','1')));size=int(request.args.get('size','25'))
        except ValueError:raise ValueError('Choose valid pagination.')
        if size not in (25,50,100):raise ValueError('Choose 25, 50 or 100 rows per page.')
        campus=request.args.get('campus','');cls=request.args.get('class_name','');q=request.args.get('q','').strip().lower()
        query=Student.query.filter(Student.status=='Active',Student.id.in_(latest_query().with_entities(P.student_id)))
        query=query.outerjoin(Details,Details.student_id==Student.id)
        if campus:query=query.filter(Details.data['campus'].as_string()==campus)
        if cls:query=query.filter(Student.class_name==cls)
        if q:query=query.filter(db.func.lower(db.func.coalesce(Student.name,'')+' '+Student.admission_no+' '+cast(Student.id,String)).contains(q,autoescape=True))
        total=query.count();pages=max(1,(total+size-1)//size);page=min(page,pages)
        students=query.order_by(Student.id).offset((page-1)*size).limit(size).all();data=app.extensions['record_helpers']['raw_many']('student',students)
        plans={p.student_id:p for p in latest_query().filter(P.student_id.in_([s.id for s in students])).all()} if students else {}
        campuses=sorted({r[0] for r in db.session.query(Details.data['campus'].as_string()).distinct().all() if r[0]})
        classes=sorted({r[0] for r in db.session.query(Student.class_name).distinct().all() if r[0]})
        return render_template('fee_increments.html',title='Bulk fee increment',rows=[(s,data[s.id],plans[s.id]) for s in students],campuses=campuses,classes=classes,campus=campus,class_name=cls,page=page,pages=pages,size=size,total=total)
    app.register_blueprint(bp)
