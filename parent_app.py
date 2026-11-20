"""Family-scoped parent summaries and actions; never infer publication or delivery."""
import calendar,hashlib,hmac,io,json,re,secrets,time
from collections import Counter
from datetime import date,datetime,timedelta,timezone
from decimal import Decimal
from zoneinfo import ZoneInfo
from flask import abort,flash,g,redirect,render_template,request,send_file,session,url_for
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import StaleDataError
from school_clock import school_today

TABS=('home','academics','attendance','fees','connect')
STUDY=('learning','notes','assignments','vacation')
FEATURES={'academics':'marks','results':'results','attendance':'attendance','fees':'fees','profile':'profile','overview':'overview','dates':'dates','rollslip':'rollslip','leave':'leave','complaints':'complaints','ptm':'talk','notifications':'messages','announcements':'notice','learning':'diary','notes':'diary','assignments':'diary','vacation':'quizzes'}

def configure_parent_app(app,db,Student,bp,principal,access,rate):
    rm=app.extensions['record_models'];ops=app.extensions['ops_models'];D=rm['student'];tz=ZoneInfo('Asia/Karachi')
    class Action(db.Model):
        __tablename__='parent_app_action'
        token=db.Column(db.String(43),primary_key=True)
        family_id=db.Column(db.Integer,nullable=False,index=True)
        student_id=db.Column(db.Integer,nullable=False)
        kind=db.Column(db.String(30),nullable=False)
        target_id=db.Column(db.Integer,nullable=False)
        fingerprint=db.Column(db.String(64),nullable=False)
    class NoticeState(db.Model):
        __tablename__='parent_app_notice'
        family_id=db.Column(db.Integer,primary_key=True)
        student_id=db.Column(db.Integer,primary_key=True)
        source=db.Column(db.String(100),primary_key=True)
        revision=db.Column(db.String(64),nullable=False)
    app.extensions['parent_app_models']=dict(action=Action,notice=NoticeState)
    def family_rows():
        f=principal()
        if not f:return None,[]
        rows=app.extensions['record_helpers']['read_many']('student',Student.query.join(D,D.student_id==Student.id).filter(D.family_id==f.id,Student.status=='Active').order_by(Student.name,Student.id).all())
        return f,rows
    def selected(rows,sid=None):
        raw=sid if sid is not None else request.args.get('sid')
        if raw is not None:
            if not str(raw).isdigit():abort(404)
            item=next(((s,d) for s,d in rows if s.id==int(raw)),None)
            if not item:abort(404)
        else:item=next(((s,d) for s,d in rows if s.id==session.get('parent_selected')),rows[0] if rows else (None,{}))
        if item[0]:session['parent_selected']=item[0].id
        return item
    def allowed(s,d,feature):return access(s.id,d.get('campus',''),feature)['effective']!='block'
    def check(s,d,feature):
        decision=access(s.id,d.get('campus',''),feature)
        if decision['effective']=='block':return render_template('parent_portal.html',view='blocked',title='Contact the school office',student=s,school=g.parent_school),403
        g.parent_warn=decision['effective']=='warn'
    def link(view='home',sid=None,**values):
        if view=='home':return url_for('parent_portal.home',code=g.parent_school.code)
        return url_for('parent_portal.app_view',code=g.parent_school.code,view=view,**({'sid':sid} if sid else {}),**values)
    def feature_link(sid,feature):return url_for('parent_portal.feature',code=g.parent_school.code,sid=sid,feature=feature)
    def results(sid):
        R=app.extensions['parent_exam_release_model'];out=[]
        for r in R.query.filter_by(published=True).order_by(R.updated.desc(),R.award_id.desc()).all():
            value=r.snapshot.get('children',{}).get(str(sid))
            if value:out.append(dict(**{**value,'student_name':value.get('name',''),'name':r.snapshot.get('exam_name','Exam'),'id':r.award_id,'updated':r.updated}))
        return out
    def attendance(sid,month=None):
        month=month or school_today().strftime('%Y-%m')
        try:
            if not re.fullmatch(r'\d{4}-\d{2}',month):raise ValueError()
            start=date.fromisoformat(month+'-01');end=date(start.year,start.month,calendar.monthrange(start.year,start.month)[1])
        except ValueError:abort(422,'Choose a valid month.')
        rows=ops['daily'].query.filter_by(kind='student',person_id=sid).filter(ops['daily'].day<=school_today()).order_by(ops['daily'].day.desc()).all()
        chosen=[r for r in rows if start<=r.day<=end];counts=Counter(r.status for r in chosen)
        def percent(items):
            marked=[r for r in items if r.status not in ('Off Day','Unmarked')]
            return round(100*sum(r.status in ('Present','Late') for r in marked)/len(marked),1) if marked else None
        return dict(rows=chosen,counts=counts,percent=percent(chosen),overall=percent(rows),today=next((r.status for r in rows if r.day==school_today()),'Not marked'),weeks=calendar.Calendar(firstweekday=6).monthdatescalendar(start.year,start.month),days={r.day:r for r in chosen},start=start,end=end,previous=(start-timedelta(days=1)).strftime('%Y-%m'),next=(end+timedelta(days=1)).strftime('%Y-%m'))
    def fees(sid):
        bills=ops['bill'].query.filter_by(student_id=sid).order_by(ops['bill'].month.desc(),ops['bill'].id.desc()).all();receipts=ops['receipt'].query.filter_by(student_id=sid,voided=False).order_by(ops['receipt'].day.desc(),ops['receipt'].id.desc()).all()
        month=school_today().strftime('%Y-%m');current=[b for b in bills if b.month==month];due=sum(b.remaining for b in current)
        status='Not billed yet' if not current else 'Paid' if due==0 else 'Partly paid' if any(b.paid or b.discount for b in current) else 'Unpaid'
        plan=app.extensions['student_fee_plan_model'].query.filter_by(student_id=sid).filter(app.extensions['student_fee_plan_model'].effective<=month).order_by(app.extensions['student_fee_plan_model'].effective.desc()).first()
        names={'tuition','tuitionfee'};policy=db.session.get(app.extensions['general_tools_models']['policy'],1)
        if policy and policy.data.get('tuition_head'):
            head=db.session.get(app.extensions['fee_setup_models']['head'],policy.data['tuition_head'])
            if head:names.add(''.join(c for c in head.label.casefold() if c.isalnum()))
        tuition=[l for l in (plan.data.get('lines',[]) if plan else []) if ''.join(c for c in l['particular'].casefold() if c.isalnum()) in names]
        return dict(bills=bills,receipts=receipts,by_bill={b.id:[r for r in receipts if r.bill_id==b.id] for b in bills},status=status,current_due=due,total_due=sum(b.remaining for b in bills),tuition=sum(l['net'] for l in tuition) if tuition else None)
    def summary(s,d):
        a=attendance(s.id) if allowed(s,d,'attendance') else None;f=fees(s.id);r=results(s.id) if allowed(s,d,'marks') and allowed(s,d,'results') else []
        photo=rm['file'].query.filter_by(owner_kind='student',owner_id=s.id,photo=True).order_by(rm['file'].id.desc()).first()
        return dict(student=s,data=d,attendance=a,fees=f,result=r[0] if r else None,photo=bool(photo))
    def render(view,student=None,data=None,**values):return render_template('parent_app.html',pview=view,title=view.replace('-',' ').title(),school=g.parent_school,student=student,data=data or {},**values)
    @bp.context_processor
    def context():
        f,rows=family_rows();s,d=selected(rows,(request.view_args or {}).get('sid')) if rows else (None,{})
        profile=db.session.get(app.extensions['institute_setup_models']['profile'],1);profile=profile.data if profile else {}
        phone=re.sub(r'[^+0-9]','',str(profile.get('contact') or profile.get('phone') or ''));whatsapp=re.sub(r'[^0-9]','',str(profile.get('whatsapp') or ''))
        return dict(school_contact=dict(phone=phone,whatsapp=whatsapp,address=profile.get('address','')),parent_link=link,parent_feature=feature_link,parent_children=rows,parent_selected=s,parent_family=f,parent_today=school_today(),parent_now=datetime.now(tz).strftime('%d %b %Y, %I:%M %p'),parent_token=secrets.token_urlsafe(32),parent_money=lambda n:'Rs '+f'{n/100:,.2f}' if n is not None else 'Not set',parent_number=lambda n:format(Decimal(str(n)),'f').rstrip('0').rstrip('.') if '.' in str(n) else str(n),parent_warn=getattr(g,'parent_warn',False))
    @app.context_processor
    def message_context():
        return dict(context(),pview='connect') if request.blueprint=='parent_messages' else {}
    def home(code):
        f,rows=family_rows()
        if not f:return redirect(url_for('parent_portal.login',code=code))
        return render('home',cards=[summary(s,d) for s,d in rows])
    def entries(s,d,kind):
        E=app.extensions['student_extras_models']['entry'];q=E.query.filter(E.kind==kind,E.campus.in_(['',d.get('campus','')]),E.starts<=school_today())
        if kind=='notices':q=q.filter(E.ends>=school_today())
        rows=[]
        for e in q.order_by(E.starts.desc(),E.id.desc()).all():
            if kind=='notices' and not(e.data.get('all_students') or s.class_name in e.data.get('classes',[])):continue
            if kind=='diary' and not(e.data.get('class_name')==s.class_name and e.data.get('section')==d.get('section') and (not d.get('subjects') or e.data.get('subject') in d['subjects'])):continue
            rows.append(e)
        return rows
    def notifications(s,d,f):
        out=[]
        def add(key,revision,title,body,url,when):out.append(dict(key=key,revision=hashlib.sha256(str(revision).encode()).hexdigest(),title=title,body=body,url=url,when=str(when)))
        if allowed(s,d,'attendance'):
            for r in attendance(s.id)['rows'][:12]:add('attendance:'+str(r.id),r.status,'Attendance · '+str(r.day),r.status,link('attendance',s.id),r.day)
        fee=fees(s.id)
        for r in fee['receipts'][:12]:add('receipt:'+str(r.id),(r.amount,r.discount,r.voided),'Fee payment · '+str(r.day),'Paid '+f'{r.amount/100:,.2f}'+' · Discount '+f'{r.discount/100:,.2f}',link('fees',s.id),r.day)
        for b in fee['bills'][:12]:add('bill:'+str(b.id),(b.version,b.remaining),'Challan · '+b.month,'Remaining '+f'{b.remaining/100:,.2f}',link('fees',s.id),b.month+'-01')
        for kind,feature in [('notices','notice'),('diary','diary')]:
            if allowed(s,d,feature):
                for e in entries(s,d,kind)[:8]:add(kind+':'+str(e.id),(e.title,e.body,e.data),e.title,'Published '+str(e.starts),feature_link(s.id,feature),e.starts)
        if allowed(s,d,'results') and allowed(s,d,'marks'):
            for r in results(s.id)[:5]:add('result:'+str(r['id']),r['updated'],'Published result · '+r['name'],'Your child’s published report is available.',link('results',s.id),r['updated'])
        states={r.source:r.revision for r in NoticeState.query.filter_by(family_id=f.id,student_id=s.id).all()}
        for e in out:e['read']=states.get(e['key'])==e['revision']
        return sorted(out,key=lambda e:(e['when'],e['key']),reverse=True)[:40]
    def fingerprint(data):return hashlib.sha256(json.dumps(data,sort_keys=True).encode()).hexdigest()
    def save_action(f,s,kind,data,create):
        token=request.form.get('token','')
        if not re.fullmatch(r'[A-Za-z0-9_-]{43}',token):abort(422,'Reload this form.')
        digest=fingerprint(data);old=db.session.get(Action,token)
        if old:
            if (old.family_id,old.student_id,old.kind,old.fingerprint)!=(f.id,s.id,kind,digest):abort(409,'This form was already used. Reload before submitting again.')
            return
        rate('app:'+str(f.id)+':'+str(s.id),40)
        row=create();db.session.add(row);db.session.flush();db.session.add(Action(token=token,family_id=f.id,student_id=s.id,kind=kind,target_id=row.id,fingerprint=digest));db.session.add(ops['audit'](action='Parent '+kind,data=dict(family_id=f.id,student_id=s.id,target_id=row.id)));db.session.commit()
    @bp.get('/app/<view>')
    def app_view(code,view,selected_sid=None):
        f,rows=family_rows()
        if not f:return redirect(url_for('parent_portal.login',code=code))
        if view not in set(TABS)|set(FEATURES)|{'student','contact'}:abort(404)
        s,d=selected(rows,selected_sid)
        if not s:return render('home',cards=[])
        if view in FEATURES:
            blocked=check(s,d,FEATURES[view])
            if blocked:return blocked
        if view in ('student','overview'):return render(view,s,d,card=summary(s,d))
        if view=='academics':return render(view,s,d,results=results(s.id) if allowed(s,d,'results') else [])
        if view=='results':return render(view,s,d,results=results(s.id))
        if view=='attendance':return render(view,s,d,attendance=attendance(s.id,request.args.get('month')))
        if view=='fees':return render(view,s,d,fees=fees(s.id))
        if view=='connect':return render(view,s,d)
        if view=='notifications':return render(view,s,d,events=notifications(s,d,f))
        if view=='announcements':return redirect(feature_link(s.id,'notice'))
        if view=='profile':return render(view,s,d)
        if view=='contact':return render(view,s,d)
        if view=='leave':
            L=app.extensions['general_leave_model'];return render(view,s,d,leaves=L.query.filter_by(institute_scope=g.parent_school.storage_key,student_id=s.id).order_by(L.id.desc()).limit(100).all())
        if view=='complaints':
            ids=[r.target_id for r in Action.query.filter_by(family_id=f.id,student_id=s.id,kind='feedback').all()];F=app.extensions['general_feedback_model'];return render(view,s,d,feedback=F.query.filter(F.id.in_(ids),F.institute_scope==g.parent_school.storage_key).order_by(F.id.desc()).all())
        if view=='ptm':
            M=app.extensions['ptm_models']['meeting'];meetings=M.query.filter_by(student_id=s.id,campus=d.get('campus','')).order_by(M.day.desc(),M.time).all();return render(view,s,d,meetings=meetings,events={e.id:e for e in app.extensions['ptm_models']['event'].query.all()})
        if view in STUDY or view in ('dates','rollslip'):return app.extensions['parent_study_helpers']['parent_page'](view,s,d,render)
        abort(404)
    @bp.post('/app/students/<int:sid>/<action>')
    def app_action(code,sid,action):
        f,rows=family_rows()
        if not f:return redirect(url_for('parent_portal.login',code=code))
        s,d=selected(rows,sid);feature={'leave':'leave','feedback':'complaints','read':'messages','ptm':'talk','submission':'diary'}.get(action)
        if not feature:abort(404)
        blocked=check(s,d,feature)
        if blocked:return blocked
        if action=='leave':
            try:start=date.fromisoformat(request.form.get('from',''));end=date.fromisoformat(request.form.get('to',''))
            except ValueError:abort(422,'Choose valid leave dates.')
            reason=request.form.get('reason','').strip();typ=request.form.get('type','').strip()
            if end<start or (end-start).days>365 or not 1<=len(reason)<=2000 or typ not in ('Sick Leave','Family Leave','Other'):abort(422)
            values=dict(institute_scope=g.parent_school.storage_key,student_id=sid,from_date=start.isoformat(),to_date=end.isoformat(),reason=reason,leave_type=typ)
            save_action(f,s,'leave',values,lambda:app.extensions['general_leave_model'](**{**values,'from_date':start,'to_date':end}));flash('Leave request sent to the school.','success');return redirect(link('leave',sid))
        if action=='feedback':
            message=request.form.get('message','').strip();kind=request.form.get('kind');category=request.form.get('category')
            if kind not in ('complaint','suggestion') or category not in ('Academic','Non Academic') or not 1<=len(message)<=5000:abort(422)
            values=dict(institute_scope=g.parent_school.storage_key,kind=kind,category=category,campus=d.get('campus',''),message=message,submitted_by=('Parent family '+f.number)[:120])
            save_action(f,s,'feedback',values,lambda:app.extensions['general_feedback_model'](**values));flash('Your feedback was sent to the school.','success');return redirect(link('complaints',sid))
        if action=='read':
            try:items=json.loads(request.form.get('items','[]'))
            except ValueError:abort(422)
            if not isinstance(items,list) or len(items)>40 or any(not isinstance(e,dict) for e in items):abort(422)
            for e in notifications(s,d,f):
                if not any(i.get('key')==e['key'] and i.get('revision')==e['revision'] for i in items):continue
                state=db.session.get(NoticeState,(f.id,sid,e['key']))
                if state:state.revision=e['revision']
                else:db.session.add(NoticeState(family_id=f.id,student_id=sid,source=e['key'],revision=e['revision']))
            db.session.commit();return '',204
        if action=='ptm':
            raw=request.form.get('id','');text=request.form.get('feedback','').strip()
            if not raw.isdigit() or not 1<=len(text)<=2000:abort(422)
            M=app.extensions['ptm_models']['meeting'];meeting=M.query.filter_by(id=int(raw),student_id=sid,campus=d.get('campus','')).first_or_404()
            if request.form.get('version')!=str(meeting.version):abort(409,'Meeting changed. Reload before sending feedback.')
            meeting.feedback=text;db.session.add(ops['audit'](action='Parent PTM feedback',data=dict(student_id=sid,family_id=f.id,meeting_id=meeting.id)));db.session.commit();return redirect(link('ptm',sid))
        if action=='submission':return app.extensions['parent_study_helpers']['submit'](f,s,d,save_action,link)
    @bp.get('/app/students/<int:sid>/photo')
    def app_photo(code,sid):
        f,rows=family_rows()
        if not f:abort(403)
        s,d=selected(rows,sid);row=rm['file'].query.filter_by(owner_kind='student',owner_id=sid,photo=True).order_by(rm['file'].id.desc()).first_or_404()
        if row.mime not in ('image/jpeg','image/png','image/webp'):abort(404)
        return send_file(io.BytesIO(row.content),mimetype=row.mime)
    @bp.get('/app/students/<int:sid>/challans/<int:bid>')
    def app_challan(code,sid,bid):
        f,rows=family_rows()
        if not f:abort(403)
        s,d=selected(rows,sid);bill=ops['bill'].query.filter_by(id=bid,student_id=sid).first_or_404()
        return render('challan',s,d,bill=bill)
    @bp.get('/app/logo')
    def app_logo(code):
        if not principal():abort(403)
        profile=db.session.get(app.extensions['institute_setup_models']['profile'],1)
        if not profile or not profile.logo or profile.logo_mime not in ('image/png','image/jpeg','image/webp'):abort(404)
        return send_file(io.BytesIO(profile.logo),mimetype=profile.logo_mime)
    @bp.errorhandler(StaleDataError)
    @bp.errorhandler(IntegrityError)
    def conflict(error):db.session.rollback();return 'This request changed. Reload before trying again.',409
    def intercept(sid,feature):
        mapping={'profile':'profile','attendance':'attendance','fees':'fees','marks':'academics','results':'results','dates':'dates','rollslip':'rollslip','leave':'leave','complaints':'complaints','overview':'overview','talk':'ptm','help':'contact'}
        return app_view(g.parent_school.code,mapping[feature],sid) if feature in mapping else None
    app.extensions['parent_app_helpers']=dict(home=home,intercept=intercept,rows=family_rows,selected=selected,summary=summary,allowed=allowed,check=check,link=link)
    from parent_study import configure_parent_study
    configure_parent_study(app,db,Student,bp,principal,access,render,link,selected,family_rows)
