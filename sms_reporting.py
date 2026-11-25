"""Read-only school SIM report. Historical job text and state are never rewritten."""
from collections import Counter
from datetime import date,datetime,timedelta
from zoneinfo import ZoneInfo
from flask import abort,request,render_template,make_response
import re

STATES={'queued':'Pending','claimed':'Under review','started':'Submission started','sent':'Submitted','failed':'Failed','unknown':'Uncertain','cancelled':'Cancelled'}
CATEGORIES=('Attendance','Fee','Admission','General','Exam','Other')
ZONE=ZoneInfo('Asia/Karachi')

def source_info(source):
    parts=source.split(':')
    try:
        if parts[0]=='attendance':return 'Attendance',int(parts[2]),None,None
        if parts[0]=='workflow':return 'Other',int(parts[2]),int(parts[1]),None
        if parts[0]=='fee-reminder':return 'Fee',int(parts[-1]),None,None
        if parts[0]=='admission-bulk':return 'Admission',None,None,int(parts[-1])
        if parts[0] in ('admission-query','admission-auto'):return 'Admission',None,None,int(parts[1])
    except (ValueError,IndexError):pass
    return 'Other',None,None,None

def report(app,db,Student,Workflow,csv_response):
    from flask import session,g
    if not session.get('owner_id') or session.get('demo') or session.get('staff_id') or getattr(g,'staff_principal',None):abort(403)
    models=app.extensions['sms_models'];Job=models['job'];Device=models['device'];rm=app.extensions['record_models']
    today=datetime.now(ZONE).date()
    f={k:request.args.get(k,'').strip() for k in ('from','to','campus','class_name','section','state','category','q')}
    f['from']=f['from'] or (today-timedelta(days=29)).isoformat();f['to']=f['to'] or today.isoformat()
    try:start=date.fromisoformat(f['from']);end=date.fromisoformat(f['to'])
    except ValueError:raise ValueError('Choose valid report dates.')
    if end<start or (end-start).days>366:raise ValueError('Choose a date range of up to 367 days.')
    if f['state'] and f['state'] not in STATES:raise ValueError('Choose a valid SMS status.')
    if f['category'] and f['category'] not in CATEGORIES:raise ValueError('Choose a valid SMS category.')
    if len(f['q'])>160:raise ValueError('Search up to 160 characters.')
    devices={d.id:d for d in Device.query.all()}
    options={k:sorted({r.value for r in rm['settings'].query.filter_by(category=k).all()}) for k in ('campus','class_name','section')}
    options['campus']=sorted(set(options['campus'])|{d.campus for d in devices.values()})
    q=Job.query.filter(Job.created>=datetime.combine(start,datetime.min.time(),ZONE).timestamp(),Job.created<datetime.combine(end+timedelta(days=1),datetime.min.time(),ZONE).timestamp())
    if f['campus']:q=q.filter(Job.device_id.in_([d.id for d in devices.values() if d.campus==f['campus']]))
    if f['state']:q=q.filter_by(state=f['state'])
    jobs=q.order_by(Job.created.desc(),Job.id.desc()).limit(5001).all()
    if len(jobs)>5000:raise ValueError('More than 5,000 SMS match this range. Narrow the dates, campus or status before reporting.')
    info={j.id:source_info(j.source) for j in jobs}
    sids={v[1] for v in info.values() if v[1] is not None}
    wids={i for v in info.values() for i in (v[2],v[3]) if i is not None}
    pupils={s.id:s for s in Student.query.filter(Student.id.in_(sids)).all()}
    details=app.extensions['record_helpers']['raw_many']('student',list(pupils.values()))
    workflows={w.id:w for w in Workflow.query.filter(Workflow.id.in_(wids)).all()}
    def stamp(t):return datetime.fromtimestamp(t,ZONE).strftime('%Y-%m-%d %I:%M:%S %p') if t else ''
    rows=[]
    for j in jobs:
        category,sid,wid,qid=info[j.id];s=pupils.get(sid);d=details.get(sid,{})
        w=workflows.get(wid);inquiry=workflows.get(qid);idata=inquiry.data if inquiry and inquiry.kind=='queries' else {}
        if w and w.kind=='message':
            subject=str(w.data.get('subject','')).lower()
            category='Attendance' if w.data.get('attendance_day') else 'Fee' if subject.startswith(('fee receipt','fee reminder','fee intimation')) else 'Exam' if subject=='exam marks' else 'General'
        campus=devices[j.device_id].campus if j.device_id in devices else ''
        name=s.name if s else idata.get('name','');father=(s.father or d.get('father','')) if s else idata.get('father','')
        cls=s.class_name if s else idata.get('class_name','');section=d.get('section','') if s else idata.get('section','')
        row=dict(category=category,sid=sid or '',name=name or '',father=father or '',campus=campus,cls=cls or '',section=section or '',phone=j.phone,text=j.text,state=j.state,status=STATES.get(j.state,j.state),created=stamp(j.created),updated=stamp(j.updated),submitted=stamp(j.updated) if j.state=='sent' else '',detail=j.detail)
        if f['class_name'] and cls!=f['class_name'] or f['section'] and section!=f['section'] or f['category'] and category!=f['category']:continue
        if f['q'] and f['q'].casefold() not in ' '.join(str(row[k]) for k in ('sid','name','father','phone','text')).casefold():continue
        rows.append(row)
    counts=Counter(r['state'] for r in rows)
    if request.args.get('export')=='csv':
        response=csv_response(['Created (PKT)','Last updated (PKT)','Submitted (PKT)','Category','Student ID','Student / inquiry','Father','Device campus','Current class','Current section','Recipient','Message','Status','Detail'],[[r[k] for k in ('created','updated','submitted','category','sid','name','father','campus','cls','section','phone','text','status','detail')] for r in rows],'sms-report')
    else:
        try:page=max(1,int(request.args.get('page','1')))
        except ValueError:raise ValueError('Choose a valid page.')
        pages=max(1,(len(rows)+49)//50);page=min(page,pages)
        response=make_response(render_template('sms_report.html',title='SMS Report',rows=rows[(page-1)*50:page*50],total=len(rows),counts=counts,filters=f,options=options,states=STATES,categories=CATEGORIES,page=page,pages=pages))
    response.headers['Cache-Control']='private, no-store'
    return response
