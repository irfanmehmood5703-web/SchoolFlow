"""Read-only institute audit history with recorded actors and honest field diffs."""
import csv,io,json,re
from datetime import date,datetime,time,timedelta,timezone
from zoneinfo import ZoneInfo
from flask import Blueprint,abort,g,has_request_context,render_template,request,session,url_for
from sqlalchemy import case,event,or_,func
from report_exports import report_xlsx

LEVELS=[('Critical',('delete','reverse','unpay','approve','reject','privilege','password','freeze','permission','role','credential','gate status','remove attendance gate')),('Important',('payment','receipt','salary','challan','fee plan','fee increment','marks','student','employee','import')),('Routine',('attendance','message','notification','scheduler'))]
SECRET=re.compile(r'password|secret|token|credential|otp|authorization|cookie|private.key',re.I)
COLUMNS={'severity':'How serious','summary':'What happened','record':'Record','action':'Action','area':'Area','actor':'Who did it','when':'When (Karachi)'}

def safe(value,depth=0):
    if depth>8:return '[Nested value]'
    if isinstance(value,dict):return {str(k):('[Hidden]' if SECRET.search(str(k)) else safe(v,depth+1)) for k,v in value.items() if not str(k).startswith('_')}
    if isinstance(value,(tuple,list)):return [safe(v,depth+1) for v in value[:1000]]
    if isinstance(value,bytes):return '[Binary attachment]'
    return value if value is None or isinstance(value,(str,int,float,bool)) else str(value)

def differences(before,after,path=''):
    if isinstance(before,dict) and isinstance(after,dict):
        output=[]
        for k in sorted(before.keys()|after.keys()):
            if SECRET.search(str(k)) or str(k).startswith('_') or k in ('updated_at','version'):continue
            output.extend(differences(before.get(k),after.get(k),path+'.'+str(k) if path else str(k)))
        return output
    if before==after:return []
    return [dict(field=path or 'Value',before=safe(before),after=safe(after))]

def configure_user_logging(app,db,Student,Employee):
    bp=Blueprint('user_logging',__name__,url_prefix='/workspace/core/user-logging');Audit=app.extensions['ops_models']['audit']
    def actor():
        if getattr(g,'parent_actor',None):return dict(g.parent_actor)
        device=getattr(g,'attendance_device_actor',None)
        if device:return dict(device)
        identity=getattr(g,'school_identity',None) or {}
        principal=getattr(g,'staff_principal',None)
        if principal:return dict(kind='Staff',id=principal.id,label=principal.username)
        if identity.get('demo'):return dict(kind='Demo',id=None,label='Demo session')
        if identity.get('email') and session.get('owner_id'):return dict(kind='Owner',id=session['owner_id'],label=identity['email'])
        if request.path.startswith(('/internal/','/operator/')):return dict(kind='System',id=None,label='System')
        return dict(kind='Unknown',id=None,label='Not recorded')
    @event.listens_for(Audit,'before_insert')
    def record_actor(mapper,connection,target):
        if has_request_context():target.data={**target.data,'_activity_actor':actor()}
    def severity_sql():
        return case(*[(or_(*[func.lower(Audit.action).contains(word) for word in words]),level) for level,words in LEVELS],else_='Normal')
    def severity(action):
        return next((level for level,words in LEVELS if any(word in action.casefold() for word in words)),'Normal')
    def entry(row):
        data=row.data or {};action=row.action;lower=action.casefold();level=severity(action);changes=[]
        if isinstance(data.get('before'),dict) and isinstance(data.get('after'),dict):changes=differences(data['before'],data['after'])
        for c in data.get('changes',[]) if isinstance(data.get('changes'),list) else []:
            if isinstance(c,dict) and isinstance(c.get('before'),dict) and isinstance(c.get('after'),dict):changes+=differences(c['before'],c['after'],('Challan '+str(c['bill_id']) if c.get('bill_id') else 'Record '+str(c.get('student_id',c.get('id','')))))
        record='Not recorded';link=None
        kind=data.get('record_kind');rid=data.get('record_id')
        if kind in ('student','employee') and isinstance(rid,int):
            record=kind.title()+' #'+str(rid)+((' · '+str(data['record_name'])) if data.get('record_name') else '')
            if exists(kind,rid):link=url_for('records.record_detail',kind=kind,id=rid)
        else:
            for key,model,typ in [('student',Student,'student'),('student_id',Student,'student'),('employee',Employee,'employee'),('employee_id',Employee,'employee')]:
                if isinstance(data.get(key),int):
                    record=typ.title()+' #'+str(data[key])
                    if exists(typ,data[key]):link=url_for('records.record_detail',kind=typ,id=data[key])
                    break
            if record=='Not recorded' and isinstance(data.get('award'),int):
                record='Award #'+str(data['award']);W=app.extensions['ops_models']['workflow'];award=db.session.get(W,data['award'])
                if award and award.kind=='awards':link=url_for('ops.marks',award_id=award.id)
        area='Core Settings'
        if any(w in lower for w in ('payment','receipt','challan','fee','installment')):area='Fees'
        elif any(w in lower for w in ('salary','lecture','employee')):area='HRM'
        elif 'attendance' in lower:area='Attendance'
        elif any(w in lower for w in ('marks','award','exam')):area='Exam'
        elif 'student' in lower:area='Admissions'
        verb=next((v for words,v in [(('delete',),'Deleted'),(('reverse','unpay'),'Reversed'),(('approve',),'Approved'),(('reject',),'Rejected'),(('create','add','import','generate'),'Created'),(('save','update','change','assign','set'),'Updated')] if any(w in lower for w in words)),'Recorded')
        who=data.get('_activity_actor',{});label=who.get('label','Not recorded') if isinstance(who,dict) else 'Not recorded'
        stamp=row.created.replace(tzinfo=timezone.utc).astimezone(ZoneInfo('Asia/Karachi')).strftime('%d-%b-%Y %I:%M:%S %p') if row.created else 'Not recorded'
        return dict(id=row.id,severity=level,summary=action,record=record,action=verb,area=area,actor=label,when=stamp,changes=changes[:2000],payload=safe(data),link=link)
    def exists(kind,rid):
        cache=getattr(request,'log_record_ids',None)
        if cache is not None:return rid in cache.get(kind,set())
        return db.session.get(Student if kind=='student' else Employee,rid) is not None
    def entries(rows):
        ids={'student':set(),'employee':set()}
        for row in rows:
            d=row.data or {};kind=d.get('record_kind');rid=d.get('record_id')
            if kind in ids and type(rid) is int:ids[kind].add(rid)
            for kind in ids:
                for field in (kind,kind+'_id'):
                    if type(d.get(field)) is int:ids[kind].add(d[field])
        found={}
        for kind,model in [('student',Student),('employee',Employee)]:
            found[kind]=set()
            values=list(ids[kind])
            for start in range(0,len(values),900):found[kind].update(x[0] for x in db.session.query(model.id).filter(model.id.in_(values[start:start+900])).all())
        request.log_record_ids=found
        return [entry(row) for row in rows]
    def query():
        q=Audit.query;selected=request.args.get('severity','all');levels=['Critical','Important','Normal','Routine']
        if selected not in levels+['all']:raise ValueError('Choose a valid severity.')
        level=severity_sql()
        if selected!='all':q=q.filter(level==selected)
        elif request.args.get('routine')!='1':q=q.filter(level!='Routine')
        bounds=[]
        for key in ('from','to'):
            raw=request.args.get(key,'')
            if not raw:bounds.append(None);continue
            try:d=date.fromisoformat(raw)
            except ValueError:raise ValueError('Choose valid From / To dates.')
            if raw!=d.isoformat() or d.year==9999:raise ValueError('Choose a full valid date before year 9999.')
            bounds.append(d)
        if all(bounds) and bounds[0]>bounds[1]:raise ValueError('From date must not follow To date.')
        for idx,d in enumerate(bounds):
            if d:
                at=datetime.combine(d+timedelta(days=idx),time(),ZoneInfo('Asia/Karachi')).astimezone(timezone.utc).replace(tzinfo=None)
                q=q.filter(Audit.created>=at) if idx==0 else q.filter(Audit.created<at)
        text=request.args.get('q','').strip();who=request.args.get('actor','').strip()
        if len(text)>160 or len(who)>160:raise ValueError('Use searches up to 160 characters.')
        if text:q=q.filter(Audit.action.ilike('%'+text.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')+'%',escape='\\'))
        if who:q=q.filter(Audit.data['_activity_actor']['label'].as_string()==who)
        verbs=[(('delete',),'Deleted'),(('reverse','unpay'),'Reversed'),(('approve',),'Approved'),(('reject',),'Rejected'),(('create','add','import','generate'),'Created'),(('save','update','change','assign','set'),'Updated')]
        areas=[(('payment','receipt','challan','fee','installment'),'Fees'),(('salary','lecture','employee'),'HRM'),(('attendance',),'Attendance'),(('marks','award','exam'),'Exam'),(('student',),'Admissions')]
        for key,rules,default in [('action',verbs,'Recorded'),('area',areas,'Core Settings')]:
            selected=request.args.get(key,'')
            if selected:
                if selected not in [label for words,label in rules]+[default]:raise ValueError('Choose a valid '+key+' filter.')
                expression=case(*[(or_(*[func.lower(Audit.action).contains(word) for word in words]),label) for words,label in rules],else_=default)
                q=q.filter(expression==selected)
        return q.order_by(Audit.created.desc(),Audit.id.desc())
    @bp.errorhandler(ValueError)
    def invalid(error):return render_template('operation_error.html',title='Check audit filters',error=str(error)),422
    @bp.after_request
    def private(response):response.headers['Cache-Control']='private, no-store';return response
    @bp.get('')
    def index():
        q=query();prefs=app.extensions['staff_access_helpers']['grid_preferences']('logs')
        try:size=int(request.args.get('size',prefs.get('size',50)));page=int(request.args.get('page','1'))
        except ValueError:raise ValueError('Choose valid pagination.')
        if size not in (25,50,100) or page is None or page<1:raise ValueError('Choose 25, 50 or 100 rows and a valid page.')
        cols=request.args.getlist('columns') or prefs.get('columns') or list(COLUMNS)
        if len(cols)!=len(set(cols)) or any(c not in COLUMNS for c in cols):raise ValueError('Choose valid export columns.')
        export=request.args.get('export','');total=q.count();pages=max(1,(total+size-1)//size);page=min(page,pages)
        if export:
            if export not in ('xlsx','csv'):raise ValueError('Choose Excel or CSV; use Print for PDF.')
            if total>50000:raise ValueError('Narrow the export to 50,000 rows.')
            rows=entries(q.all());headers=[COLUMNS[c] for c in cols];values=[[r[c] for c in cols] for r in rows]
            if export=='xlsx':return report_xlsx(headers,values,'user-logging')
            output=io.StringIO();writer=csv.writer(output);writer.writerow(headers)
            writer.writerows([[("'"+str(v)) if str(v).lstrip().startswith(('=','+','-','@')) else v for v in r] for r in values])
            return app.response_class('\ufeff'+output.getvalue(),mimetype='text/csv',headers={'Content-Disposition':'attachment; filename="schoolflow-user-logging.csv"'})
        shown=entries(q.offset((page-1)*size).limit(size).all())
        return render_template('user_logging.html',title='User Logging',rows=shown,total=total,page=page,pages=pages,size=size,columns=COLUMNS,selected_columns=cols)
    @bp.get('/<int:rid>')
    def details(rid):return render_template('user_log_detail.html',title='Recorded changes',row=entry(db.get_or_404(Audit,rid)))
    app.register_blueprint(bp)
