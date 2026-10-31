"""Tenant fee heads and scoped schedules; billing keeps immutable money snapshots."""
import calendar,hmac,re
from datetime import date
from flask import Blueprint,abort,flash,redirect,render_template,request,session,url_for
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import StaleDataError
from operations import money
from student_fee_plans import PARTICULARS

TIMINGS={'monthly':'Every month','months':'Chosen months','first':'First challan only','manual':'Ask when making challans','fine':'By fine policy'}


def configure_fee_setup(app,db,Student):
    bp=Blueprint('fee_setup',__name__,url_prefix='/workspace/core/fees')
    models=app.extensions['ops_models'];W=models['workflow'];Bill=models['bill'];Audit=models['audit'];P=app.extensions['student_fee_plan_model'];rm=app.extensions['record_models']
    class FeeHead(db.Model):
        key=db.Column(db.String(200),primary_key=True)
        label=db.Column(db.String(160),nullable=False)
        timing=db.Column(db.String(20),nullable=False,default='manual')
        months=db.Column(db.JSON,nullable=False,default=list)
        custom=db.Column(db.Boolean,nullable=False,default=True)
        version=db.Column(db.Integer,nullable=False,default=1)
        __mapper_args__={'version_id_col':version}
    class FeeSchedule(db.Model):
        id=db.Column(db.Integer,primary_key=True)
        name=db.Column(db.String(160),nullable=False)
        campus=db.Column(db.String(160),nullable=False)
        class_name=db.Column(db.String(160),nullable=False)
        description=db.Column(db.String(1000),nullable=False,default='')
        due_day=db.Column(db.Integer,nullable=False)
        lines=db.Column(db.JSON,nullable=False)
        version=db.Column(db.Integer,nullable=False,default=1)
        __table_args__=(db.UniqueConstraint('name','campus','class_name'),)
        __mapper_args__={'version_id_col':version}
    app.extensions['fee_setup_models']=dict(head=FeeHead,schedule=FeeSchedule)

    def text(key,required=False,limit=160):
        value=request.form.get(key,'').strip()
        if (required and not value) or len(value)>limit:raise ValueError('Check '+key.replace('_',' ')+'.')
        return value
    def options(category):return sorted({r.value for r in rm['settings'].query.filter_by(category=category).all()})
    def head_map():
        if hasattr(request,'fee_head_cache'):return request.fee_head_cache
        rows={r.key:r for r in FeeHead.query.order_by(FeeHead.key).all()}
        request.fee_head_cache=rows
        return rows
    def label(key):
        row=head_map().get(key)
        if row:return row.label
        suffix=' — First Time Arrears'
        return label(key[:-len(suffix)])+suffix if key.endswith(suffix) else key
    def resolve(value):
        suffix=' — First Time Arrears'
        if value.endswith(suffix):return resolve(value[:-len(suffix)])+suffix
        return next((r.key for r in head_map().values() if r.label.casefold()==value.casefold()),value) if value not in head_map() else value
    def heads():
        rows=head_map();legacy={r[0] for r in db.session.query(W.data['particular'].as_string()).filter(W.kind=='fee-plans').distinct().all() if r[0]}
        names=list(PARTICULARS)+sorted((set(rows)|legacy)-set(PARTICULARS))
        return [dict(key=k,label=rows[k].label if k in rows else k,timing=rows[k].timing if k in rows else 'manual',months=rows[k].months if k in rows else [],custom=k not in PARTICULARS,version=rows[k].version if k in rows else 0) for k in names]
    def version(row):
        if request.form.get('version')!=str(row.version if row else 0):raise ValueError('These settings changed. Reload before saving.')
    def months(name):
        raw=request.form.getlist(name)
        if any(not s.isdigit() or not 1<=int(s)<=12 for s in raw):raise ValueError('Choose valid months.')
        return sorted({int(s) for s in raw})
    def audit(event,**data):db.session.add(Audit(action=event,data={**data,'owner_id':session.get('owner_id')}))
    def commit():
        try:db.session.commit()
        except (IntegrityError,StaleDataError):
            db.session.rollback();raise ValueError('Another save changed these fee settings. Reload before retrying.')
    @bp.before_request
    def protect():
        if request.method=='POST':
            token=request.form.get('_csrf','')
            if not token or not hmac.compare_digest(token,session.get('record_csrf','')):abort(400,'Reload the fee settings form.')
            app.extensions['admission_capacity']['lock']()
    @bp.errorhandler(ValueError)
    def invalid(error):
        db.session.rollback();return render_template('operation_error.html',title='Check fee settings',error=str(error)),422

    def used_head(key):
        return (any(any(x['key']==key for x in r.lines) for r in FeeSchedule.query.all()) or
                any(any(x['particular']==key for x in r.data['lines']) for r in P.query.all()) or
                any(any(x.get('particular')==key for x in r.lines) for r in Bill.query.all()) or
                any(r.data.get('particular')==key for r in W.query.filter_by(kind='fee-plans').all()))
    @bp.route('/heads',methods=['GET','POST'])
    def head_settings():
        if request.method=='POST':
            action=text('action');key=text('key',True,200);row=db.session.get(FeeHead,key);version(row)
            before=dict(label=row.label,timing=row.timing,months=list(row.months),version=row.version) if row else None
            if action=='delete':
                if not row or not row.custom:raise ValueError('Standard heads are retained. Only unused custom heads can be deleted.')
                if used_head(key):raise ValueError('This head is in use by a schedule, student plan or challan.')
                db.session.delete(row);audit('Delete unused fee head',key=key,before=before)
            elif action=='save':
                display=text('label',True)
                if any(h['key']!=key and h['label'].casefold()==display.casefold() for h in heads()):raise ValueError('Use a distinct display name for each fee head.')
                timing=text('timing',True);chosen=months('months')
                if timing not in TIMINGS:raise ValueError('Choose a billing timing.')
                if timing=='months' and not chosen:raise ValueError('Choose at least one billing month.')
                if not row:
                    known={h['key'].casefold():h['key'] for h in heads()}
                    if key.casefold() in known and key!=known[key.casefold()]:raise ValueError('That head already exists. Edit its display name instead.')
                    row=FeeHead(key=key,label=display,custom=key not in PARTICULARS);db.session.add(row)
                row.label=display;row.timing=timing;row.months=chosen if timing=='months' else []
                audit('Save fee head',key=key,label=display,timing=timing,months=row.months,before=before)
            else:raise ValueError('Choose Save or Delete.')
            commit();return redirect(url_for('fee_setup.head_settings'))
        edit=request.args.get('edit','');selected=next((h for h in heads() if h['key']==edit),None)
        return render_template('fee_heads.html',title='Fee heads & billing timing',heads=heads(),selected=selected,timings=TIMINGS,month_names=calendar.month_name)

    def scoped_schedule(student,name):
        data=app.extensions['record_helpers']['raw_many']('student',[student]).get(student.id,{})
        return FeeSchedule.query.filter_by(name=name,campus=data.get('campus',''),class_name=student.class_name).first()
    def for_student(student,data):return FeeSchedule.query.filter_by(campus=data.get('campus',''),class_name=student.class_name).order_by(FeeSchedule.name).all()
    def rules(line):return dict(first_only=line.get('first_only',False),month_override=line.get('month_override',False),months=list(line.get('months',[])),minimum=line.get('minimum'),maximum=line.get('maximum'))
    def assigned_rows(schedule):
        bykey={x['key']:x for x in schedule.lines};keys=list(PARTICULARS)+[k for k in bykey if k not in PARTICULARS]
        return [dict(particular=k,actual=bykey[k]['amount'] if k in bykey else 0,discount=0,arrears=0,fee_rules=rules(bykey[k]) if k in bykey else {}) for k in keys]
    def snapshot(schedule):return dict(schedule_id=schedule.id,schedule_version=schedule.version,due_day=schedule.due_day)
    def effective_rule(key,line=None):
        row=head_map().get(key);mode=row.timing if row else 'manual';override=(line or {}).get('fee_rules',line or {})
        chosen=override.get('months',[]) if override.get('month_override') else (row.months if row and mode=='months' else list(range(1,13)))
        return dict(timing=mode,months=list(chosen),first_only=mode=='first' or bool(override.get('first_only')),head_version=row.version if row else 0,label=row.label if row else key)
    def eligible(rule,at,first,selected):
        if rule['timing']=='fine':
            if selected:raise ValueError('Fine-policy heads need a verified fine policy. No fixed fine was charged.')
            return False
        return ((rule['timing']!='manual' or selected) and (not rule['first_only'] or first) and int(at[5:7]) in rule['months'])
    def annual(line):
        rule=effective_rule(line['key'],line)
        if rule['timing'] in ('manual','fine'):return None
        return line['amount']*(1 if rule['first_only'] and rule['months'] else len(rule['months']))
    def due(at,day):
        parsed=date.fromisoformat(at+'-01')
        return parsed.replace(day=min(int(day),calendar.monthrange(parsed.year,parsed.month)[1]))

    @bp.route('/schedules',methods=['GET','POST'])
    def schedules():
        edit=request.values.get('id','');row=db.get_or_404(FeeSchedule,int(edit)) if edit.isdigit() else None
        if edit and not edit.isdigit():raise ValueError('Choose a saved schedule.')
        if request.method=='POST':
            action=text('action');version(row)
            before=dict(name=row.name,campus=row.campus,class_name=row.class_name,description=row.description,due_day=row.due_day,lines=row.lines,version=row.version) if row else None
            if action=='delete':
                if not row:abort(404)
                if any((p.data.get('schedule_id')==row.id or (not p.data.get('schedule_id') and p.data.get('schedule')==row.name)) for p in P.query.all()):raise ValueError('This schedule is saved on student fee plans.')
                Map=app.extensions['institute_setup_models']['mapping']
                if any(row.name in m.data.get('fee_plans',[]) for m in Map.query.filter_by(campus=row.campus,class_name=row.class_name).all()):raise ValueError('Remove this schedule from the class map before deleting it.')
                db.session.delete(row);audit('Delete unused fee schedule',id=row.id,before=before)
            elif action in ('save','duplicate'):
                name=text('name',True);description=text('description',limit=1000);day=text('due_day',True)
                if not day.isdigit() or not 1<=int(day)<=31:raise ValueError('Due day must be 1–31; shorter months use their last day.')
                campuses=request.form.getlist('campuses');classes=request.form.getlist('classes')
                if not campuses or not classes or any(c not in options('campus') for c in campuses) or any(c not in options('class_name') for c in classes):raise ValueError('Choose configured campuses and classes.')
                if row and action=='save' and (campuses!=[row.campus] or classes!=[row.class_name] or name!=row.name):raise ValueError('Keep an existing schedule name and scope stable. Use Duplicate for another scope/name.')
                keys=request.form.getlist('head_key');catalog={h['key'] for h in heads()}
                if not keys or len(keys)!=len(set(keys)) or not set(keys)<=catalog:raise ValueError('Choose unique configured fee heads.')
                lines=[]
                for i,key in enumerate(keys):
                    if request.form.get('head_version_'+str(i))!=str(head_map()[key].version if key in head_map() else 0):raise ValueError('A fee head changed. Reload this schedule form.')
                    amount=money(text('amount_'+str(i),True));low=text('minimum_'+str(i));high=text('maximum_'+str(i));lo=money(low) if low else None;hi=money(high) if high else None
                    if (lo is not None and amount<lo) or (hi is not None and amount>hi) or (lo is not None and hi is not None and lo>hi):raise ValueError('The configured actual amount must lie within its minimum/maximum: '+label(key))
                    lines.append(dict(key=key,amount=amount,minimum=lo,maximum=hi,first_only=request.form.get('first_'+str(i))=='1',month_override=request.form.get('override_'+str(i))=='1',months=months('months_'+str(i))))
                for campus in dict.fromkeys(campuses):
                    for cls in dict.fromkeys(classes):
                        target=row if row and action=='save' else None
                        if FeeSchedule.query.filter_by(name=name,campus=campus,class_name=cls).filter(FeeSchedule.id!=(target.id if target else 0)).first():raise ValueError('That schedule name already exists for '+campus+' / '+cls+'.')
                        older=[w for w in W.query.filter_by(kind='fee-plans',status='Active').all() if w.data.get('name')==name and w.data.get('campus')==campus and w.data.get('class_name')==cls]
                        if older and request.form.get('replace_previous')!='1':raise ValueError('This scope has a saved schedule. Tick Replace earlier configuration to use these updated settings; student snapshots remain unchanged.')
                        for w in older:w.status='Inactive'
                        if target:target.description=description;target.due_day=int(day);target.lines=lines
                        else:db.session.add(FeeSchedule(name=name,campus=campus,class_name=cls,description=description,due_day=int(day),lines=lines))
                if not rm['settings'].query.filter_by(category='fee_plan',value=name,class_name='').first():db.session.add(rm['settings'](category='fee_plan',value=name,class_name=''))
                audit('Save fee schedule',name=name,campuses=campuses,classes=classes,action=action,before=before,after=dict(description=description,due_day=int(day),lines=lines))
            else:raise ValueError('Choose Save, Duplicate or Delete.')
            commit();return redirect(url_for('fee_setup.schedules'))
        previous={}
        for w in W.query.filter_by(kind='fee-plans',status='Active').order_by(W.id).all():previous.setdefault((w.data.get('name',''),w.data.get('campus',''),w.data.get('class_name','')),w)
        defaults={};source={x['key']:x for x in row.lines} if row else {}
        seed=request.args.get('from_saved','')
        if seed:
            if row or not seed.isdigit():raise ValueError('Choose one saved schedule to load.')
            w=db.get_or_404(W,int(seed))
            if w.kind!='fee-plans' or w.status!='Active':abort(404)
            defaults=dict(name=w.data['name'],campuses=[w.data['campus']] if w.data.get('campus') else [],classes=[w.data['class_name']] if w.data.get('class_name') else [],due_day=w.data.get('due_day',''),description='')
            group=[x for x in W.query.filter_by(kind='fee-plans',status='Active').all() if all(x.data.get(k,'')==w.data.get(k,'') for k in ('name','campus','class_name'))]
            for x in group:
                key=x.data['particular']
                if key in source:raise ValueError('This saved schedule contains duplicate heads. Correct the source before loading it.')
                source[key]=dict(key=key,amount=money(x.data['amount']),minimum=None,maximum=None,first_only=False,month_override=False,months=[])

        editor=[dict(h,**{'line':source.get(h['key'],dict(amount=0,minimum=None,maximum=None,first_only=False,month_override=False,months=[]))}) for h in heads()]
        return render_template('fee_schedules.html',title='Fee schedules',rows=FeeSchedule.query.order_by(FeeSchedule.name,FeeSchedule.campus,FeeSchedule.class_name).all(),row=row,defaults=defaults,previous=list(previous.values()),editor=editor,options=options,months=calendar.month_name,annual=annual,label=label)

    @bp.get('/preview/<int:schedule_id>')
    def preview(schedule_id):
        row=db.get_or_404(FeeSchedule,schedule_id);at=request.args.get('month',date.today().strftime('%Y-%m'))
        try:date.fromisoformat(at+'-01')
        except ValueError:raise ValueError('Choose a valid preview month.')
        if not re.fullmatch(r'\d{4}-\d{2}',at):raise ValueError('Choose a valid preview month.')
        first=request.args.get('first')=='1';selected=set(request.args.getlist('manual'));rows=[]
        if not selected<={x['key'] for x in row.lines}:raise ValueError('Choose heads from this schedule.')
        for line in row.lines:
            rule=effective_rule(line['key'],line)
            applies=False if rule['timing']=='fine' else eligible(rule,at,first,line['key'] in selected)
            rows.append(dict(key=line['key'],label=rule['label'],timing=TIMINGS[rule['timing']],amount=line['amount'] if applies else 0,reason='Fine policy pending' if rule['timing']=='fine' else ('Included' if applies else 'Not due in this preview')))
        return render_template('fee_schedule_preview.html',title='Fee schedule preview',schedule=row,rows=rows,at=at,first=first,selected=selected,total=sum(r['amount'] for r in rows),due=due(at,row.due_day))

    @app.context_processor
    def context():return dict(fee_head_label=label)
    app.extensions['fee_setup_helpers']=dict(heads=heads,label=label,for_student=for_student,scoped_schedule=scoped_schedule,assigned_rows=assigned_rows,snapshot=snapshot,resolve=resolve,effective_rule=effective_rule,eligible=eligible,due=due)
    app.register_blueprint(bp)
