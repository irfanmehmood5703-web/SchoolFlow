"""Certificate template directory, custom designs and protected reuse."""
import hmac,io,csv,secrets
from datetime import timezone
from zoneinfo import ZoneInfo
from flask import Blueprint,abort,flash,redirect,render_template,request,session,url_for
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import StaleDataError
from certificates import TAGS,clean_html
from report_exports import report_xlsx

def configure_certificate_manager(app,db):
    bp=Blueprint('certificate_manager',__name__,url_prefix='/workspace/core/certificates')
    models=app.extensions['certificate_models'];T=models['template'];C=models['campus'];Batch=models['batch'];Issue=models['issue'];Audit=app.extensions['ops_models']['audit'];Settings=app.extensions['record_models']['settings']
    def campuses():return sorted({r.value for r in Settings.query.filter_by(category='campus').all()}|{r[0] for r in db.session.query(C.campus).filter(C.campus!='').all()})
    def commit():
        try:db.session.commit()
        except (IntegrityError,StaleDataError):db.session.rollback();raise ValueError('This template changed or already exists. Reload before saving.')
    @bp.before_request
    def protect():
        if request.method=='POST':
            if not request.form.get('_csrf') or not hmac.compare_digest(request.form['_csrf'],session.get('record_csrf','')):abort(400,'Reload the template form.')
            app.extensions['admission_capacity']['lock']()
    @bp.errorhandler(ValueError)
    def invalid(error):db.session.rollback();return render_template('operation_error.html',title='Check certificate template',error=str(error)),422
    def metadata(t):
        events=Audit.query.filter(Audit.data['template_id'].as_integer()==t.id).order_by(Audit.created,Audit.id).all()
        made=next((e for e in events if e.action=='Create certificate template'),None);updated=events[-1] if events else None
        def who(e):return (e.data.get('_activity_actor') or {}).get('label','Not recorded') if e else 'Not recorded'
        return dict(created=made.created if made else None,updated=updated.created if updated else None,creator=who(made),updater=who(updated))
    @bp.get('')
    def index():
        query=T.query.join(C,C.id==T.campus_id);campus=request.args.get('campus','');text=request.args.get('q','').strip();sort=request.args.get('sort','name');direction=request.args.get('direction','asc')
        if len(text)>160:raise ValueError('Use a search up to 160 characters.')
        if campus and campus!='__default__' and campus not in campuses():raise ValueError('Choose a configured campus.')
        if campus:query=query.filter(C.campus==('' if campus=='__default__' else campus))
        if text:query=query.filter(T.name.contains(text,autoescape=True))
        order={'name':T.name,'campus':C.campus,'id':T.id}.get(sort)
        if order is None or direction not in ('asc','desc'):raise ValueError('Choose a valid sort order.')
        query=query.order_by(order.desc() if direction=='desc' else order.asc(),T.id)
        prefs=app.extensions['staff_access_helpers']['grid_preferences']('certificates')
        try:page=int(request.args.get('page','1'));size=int(request.args.get('size',prefs.get('size',50)))
        except ValueError:raise ValueError('Choose valid pagination.')
        if page<1 or size not in (25,50,100):raise ValueError('Choose 25, 50 or 100 rows.')
        total=query.count();pages=max(1,(total+size-1)//size);page=min(page,pages)
        selected=request.args.getlist('columns') or prefs.get('columns') or ['id','campus','name','created','updated','creator','updater']
        columns=dict(id='No.',campus='Campus',name='Name',created='Created at',updated='Updated at',creator='Created by',updater='Updated by')
        if len(set(selected))!=len(selected) or any(k not in columns for k in selected):raise ValueError('Choose valid export columns.')
        exporting=request.args.get('export','')
        if exporting and (exporting not in ('xlsx','csv') or total>50000):raise ValueError('Choose Excel/CSV and at most 50,000 rows. Use Print for PDF.')
        templates=query.all() if exporting else query.offset((page-1)*size).limit(size).all();bycampus={c.id:c for c in C.query.all()}
        # One audit query for the complete displayed/exported selection.
        ids=[t.id for t in templates];events=Audit.query.filter(Audit.data['template_id'].as_integer().in_(ids)).order_by(Audit.created,Audit.id).all() if ids else [];meta={}
        for t in templates:
            own=[e for e in events if e.data.get('template_id')==t.id];made=next((e for e in own if e.action=='Create certificate template'),None);last=own[-1] if own else None
            def when(e):return e.created.replace(tzinfo=timezone.utc).astimezone(ZoneInfo('Asia/Karachi')).strftime('%d-%b-%Y %I:%M:%S %p') if e and e.created else 'Not recorded'
            def who(e):return (e.data.get('_activity_actor') or {}).get('label','Not recorded') if e else 'Not recorded'
            meta[t.id]=dict(id=t.id,campus=bycampus[t.campus_id].campus or 'Default / copy to a campus',name=t.name,created=when(made),updated=when(last),creator=who(made),updater=who(last))
        if exporting:
            headers=[columns[k] for k in selected];rows=[[meta[t.id][k] for k in selected] for t in templates]
            if exporting=='xlsx':return report_xlsx(headers,rows,'certificate-templates')
            output=io.StringIO();writer=csv.writer(output);writer.writerow(headers);writer.writerows([["'"+str(v) if str(v).lstrip().startswith(('=','+','-','@')) else v for v in row] for row in rows]);return app.response_class('\ufeff'+output.getvalue(),mimetype='text/csv',headers={'Content-Disposition':'attachment; filename="schoolflow-certificate-templates.csv"'})
        return render_template('certificate_manager.html',title='Manage Certificates',rows=templates,meta=meta,campuses=campuses(),total=total,page=page,pages=pages,size=size,columns=columns,selected=selected)
    @bp.after_request
    def private(response):response.headers['Cache-Control']='private, no-store';return response
    @bp.route('/new',methods=['GET','POST'])
    @bp.route('/<int:tid>/edit',methods=['GET','POST'])
    def editor(tid=None):
        t=db.get_or_404(T,tid) if tid else None;c=db.session.get(C,t.campus_id) if t else None
        if request.method=='POST':
            if request.form.get('version')!=str(t.version if t else 0):raise ValueError('The template changed. Reload first.')
            name=request.form.get('name','').strip();campus=request.form.get('campus','');content={key:request.form.get(key,'') for key in ('header','body','footer')}
            if not name or len(name)>160 or any(len(v)>150000 for v in content.values()):raise ValueError('Use a name up to 160 characters and sections up to 150,000 characters.')
            if campus and campus not in campuses():raise ValueError('Choose a configured campus or Default.')
            content={key:clean_html(v) for key,v in content.items()}
            if not content['body'].strip():raise ValueError('Add document body content.')
            action=request.form.get('action','save')
            if action not in ('save','preview'):raise ValueError('Choose Preview or Save.')
            if action=='preview':
                preview=render_template('certificate_document.html',sections=content,layout='certificate')
                response=render_template('certificate_manager_editor.html',title='Unsaved certificate preview',template=t,campus=campus,campuses=campuses(),tags=TAGS,content=content,name=name,preview=preview)
                db.session.rollback();return response
            target=C.query.filter_by(campus=campus).first()
            if not target:
                Profile=app.extensions['institute_setup_models']['profile'];profile=db.session.get(Profile,1);target=C(campus=campus,data=dict(profile.data) if profile else {});db.session.add(target);db.session.flush()
            duplicate=T.query.filter_by(campus_id=target.id,name=name).filter(T.id!=(t.id if t else 0)).first()
            if duplicate:raise ValueError('That template name already exists in this campus.')
            if t:
                if target.id!=t.campus_id and (Batch.query.filter_by(template_id=t.id).first() or Issue.query.filter_by(template_id=t.id).first()):raise ValueError('An issued template cannot move campuses. Create a copy instead.')
                before={k:getattr(t,k) for k in ('name','header','body','footer')};t.campus_id=target.id;t.name=name
                for k,v in content.items():setattr(t,k,v)
            else:
                before={};t=T(campus_id=target.id,key='custom-'+secrets.token_hex(12),name=name,**content);db.session.add(t)
            db.session.flush();db.session.add(Audit(action=('Create' if not tid else 'Update')+' certificate template',data=dict(template_id=t.id,campus=campus,before=before,after=dict(name=name,**content))));commit();flash('Template saved. Existing issued documents keep their saved snapshots.','success');return redirect(url_for('certificate_manager.view',tid=t.id))
        return render_template('certificate_manager_editor.html',title='Update Certificate Template' if t else 'Create Certificate Template',template=t,campus=c.campus if c else '',campuses=campuses(),tags=TAGS,content={k:clean_html(getattr(t,k)) if t else '' for k in ('header','body','footer')})
    @bp.get('/<int:tid>')
    def view(tid):
        t=db.get_or_404(T,tid);c=db.get_or_404(C,t.campus_id)
        return render_template('certificate_manager_view.html',title='View Certificate Template',template=t,campus=c.campus,meta=metadata(t),campuses=campuses())
    @bp.post('/<int:tid>/delete')
    def delete(tid):
        t=db.get_or_404(T,tid)
        if request.form.get('version')!=str(t.version) or request.form.get('confirm')!='yes':raise ValueError('Reload and confirm deletion of this unused template.')
        if Batch.query.filter_by(template_id=t.id).first() or Issue.query.filter_by(template_id=t.id).first():raise ValueError('This template has issued documents or print batches. Its history must be retained.')
        db.session.add(Audit(action='Delete certificate template',data=dict(template_id=t.id,name=t.name)));db.session.delete(t);commit();return redirect(url_for('certificate_manager.index'))
    @bp.post('/<int:tid>/copy')
    def copy(tid):
        t=db.get_or_404(T,tid);campus=request.form.get('campus','')
        if campus not in campuses() or request.form.get('version')!=str(t.version):raise ValueError('Choose a configured destination campus and reload the source template.')
        target=C.query.filter_by(campus=campus).first()
        if not target:
            Profile=app.extensions['institute_setup_models']['profile'];profile=db.session.get(Profile,1);target=C(campus=campus,data=dict(profile.data) if profile else {});db.session.add(target);db.session.flush()
        if T.query.filter_by(campus_id=target.id,name=t.name).first():raise ValueError('A template with this name already exists there. Edit it explicitly.')
        clone=T(campus_id=target.id,key='custom-'+secrets.token_hex(12),name=t.name,header=t.header,body=t.body,footer=t.footer);db.session.add(clone);db.session.flush();db.session.add(Audit(action='Create certificate template',data=dict(template_id=clone.id,copied_from=t.id,campus=campus)));commit();return redirect(url_for('certificate_manager.view',tid=clone.id))
    app.register_blueprint(bp)
