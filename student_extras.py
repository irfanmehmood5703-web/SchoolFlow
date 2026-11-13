"""Durable student notices and diaries; no external delivery is implied."""
import hmac
import io
import secrets
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo
from flask import Blueprint, abort, flash, g, redirect, render_template, request, send_file, session, url_for, jsonify
from sqlalchemy.exc import IntegrityError
from werkzeug.utils import secure_filename


def configure_student_extras(app, db, Student):
    bp = Blueprint('student_extras', __name__, url_prefix='/workspace/general')
    rm = app.extensions['record_models']
    Audit = app.extensions['ops_models']['audit']

    class Entry(db.Model):
        __tablename__ = 'student_extra_entry'
        id = db.Column(db.Integer, primary_key=True)
        kind = db.Column(db.String(20), nullable=False, index=True)
        campus = db.Column(db.String(160), nullable=False, default='')
        title = db.Column(db.String(180), nullable=False)
        body = db.Column(db.Text, nullable=False)
        starts = db.Column(db.Date, nullable=False, index=True)
        ends = db.Column(db.Date, nullable=False)
        data = db.Column(db.JSON, nullable=False, default=dict)
        token = db.Column(db.String(64), nullable=False, unique=True)
        created = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

    class Attachment(db.Model):
        __tablename__ = 'student_extra_attachment'
        id = db.Column(db.Integer, primary_key=True)
        entry_id = db.Column(db.Integer, db.ForeignKey(Entry.id), nullable=False, index=True)
        filename = db.Column(db.String(180), nullable=False)
        mime = db.Column(db.String(100), nullable=False)
        content = db.deferred(db.Column(db.LargeBinary, nullable=False))

    app.extensions['student_extras_models'] = dict(entry=Entry, attachment=Attachment)

    def choices(category):
        return sorted({r.value for r in rm['settings'].query.filter_by(category=category).all()})

    def today():
        return datetime.now(ZoneInfo('Asia/Karachi')).date().isoformat()

    def scope_ok(campus):
        allowed = getattr(g, 'access_campuses', None)
        if allowed is not None and (campus not in allowed if campus else set(app.extensions['staff_access_helpers']['campuses']()) != set(allowed)):
            abort(403, 'All-campus publishing requires access to every campus.')

    def text(key, limit, required=False):
        value = request.form.get(key, '').strip()
        if len(value) > limit or (required and not value):
            raise ValueError('Check '+key.replace('_', ' ')+'.')
        return value

    def day(raw):
        try:
            result = date.fromisoformat(raw)
            if result.isoformat() != raw: raise ValueError()
            return result
        except ValueError:
            raise ValueError('Choose valid From and To dates.')

    def choice(key, required=False):
        value = text(key, 160, required)
        category = 'class_name' if key == 'class_name' else key
        if value and value not in choices(category):
            raise ValueError('Choose a configured '+key.replace('_', ' ')+'.')
        return value

    @bp.before_request
    def protect():
        if request.method == 'POST':
            if request.content_length and request.content_length>20*1024*1024:abort(413,'Diary/notice upload exceeds 20 MB.')
            token = request.form.get('_csrf', '')
            if not token or not hmac.compare_digest(token, session.get('record_csrf', '')):
                abort(400, 'Reload this form before saving.')

    @bp.errorhandler(ValueError)
    def invalid(error):
        db.session.rollback()
        return render_template('operation_error.html', title='Check student extras', error=str(error)), 422

    @bp.errorhandler(IntegrityError)
    def duplicate(error):
        db.session.rollback()
        return render_template('operation_error.html', title='Reload this form', error='This submission was already saved. Return to the list before adding another.'), 409

    def uploads(field='attachments'):
        files = [f for f in request.files.getlist(field) if f.filename]
        if len(files) > 5: raise ValueError('Attach at most five files.')
        result = []
        total = 0
        for f in files:
            name = secure_filename(f.filename)[:180]
            ext = name.rsplit('.', 1)[-1].lower()
            content = f.read(5 * 1024 * 1024 + 1)
            total += len(content)
            if not content or len(content) > 5 * 1024 * 1024 or total > 15 * 1024 * 1024:
                raise ValueError('Files must be nonempty, up to 5 MB each and 15 MB combined.')
            mime = {'jpg':'image/jpeg','jpeg':'image/jpeg','png':'image/png','webp':'image/webp','pdf':'application/pdf','mp3':'audio/mpeg','mp4':'video/mp4'}.get(ext)
            valid = False
            if ext in ('jpg','jpeg','png','webp'):
                from PIL import Image, UnidentifiedImageError
                try:
                    with Image.open(io.BytesIO(content)) as image:
                        valid = image.format == {'jpg':'JPEG','jpeg':'JPEG','png':'PNG','webp':'WEBP'}[ext]
                        image.verify()
                except (OSError, ValueError, UnidentifiedImageError, Image.DecompressionBombError): pass
            elif ext == 'pdf': valid = content.startswith(b'%PDF-')
            elif ext == 'mp3': valid = content.startswith(b'ID3') or (len(content)>1 and content[0]==255 and content[1]&224==224)
            elif ext == 'mp4': valid = len(content)>12 and content[4:8]==b'ftyp'
            if not mime or not valid: raise ValueError('Use valid JPG, PNG, WebP, PDF, MP3 or MP4 attachments.')
            result.append((name,mime,content))
        return result

    @bp.route('/<kind>', methods=['GET','POST'])
    def index(kind):
        if kind not in ('notices','diary'): abort(404)
        creating = request.args.get('new') == '1'
        if request.method == 'POST':
            if kind=='diary' and request.form.get('format')=='subject-work':return app.extensions['diary_work_helpers']['save'](choices,scope_ok,day,uploads)
            token = text('submission', 64, True)
            if len(token) != 43: raise ValueError('Reload this form before saving.')
            existing = Entry.query.filter_by(token=token).first()
            if existing:
                scope_ok(existing.campus)
                return redirect(url_for('student_extras.index', kind=existing.kind))
            campus = choice('campus', kind=='diary')
            scope_ok(campus)
            starts = day(request.form.get('starts',''))
            ends = day(request.form.get('ends','')) if kind=='notices' else starts
            if ends < starts: raise ValueError('To must be on or after From.')
            body = text('description', 20000, True)
            data = {}
            files = []
            if kind == 'notices':
                title = text('title', 180, True)
                all_students = request.form.get('all_students') == '1'
                classes = list(dict.fromkeys(request.form.getlist('classes')))
                if any(c not in choices('class_name') for c in classes): raise ValueError('Choose configured classes.')
                if not all_students and not classes: raise ValueError('Select All Students or at least one class.')
                data = dict(all_students=all_students, classes=[] if all_students else classes)
                files = uploads()
            else:
                cls = choice('class_name', True)
                section = choice('section', True)
                sections = rm['settings'].query.filter_by(category='section',value=section).all()
                if not any(not r.class_name or r.class_name == cls for r in sections): raise ValueError('Section does not belong to the selected class.')
                subject = choice('subject', True)
                if not app.extensions['school_settings_helpers']['subject_allowed'](campus,cls,subject): raise ValueError('Subject is not assigned to this class.')
                title = (subject+' — '+cls)[:180]
                action = request.form.get('action','')
                if action not in ('save','save-send'): raise ValueError('Choose Save or Save and Send SMS.')
                channel = request.form.get('channel','')
                if channel not in ('branded','app','whatsapp'): raise ValueError('Choose a message channel.')
                contacts = [c for c in ('father','mother','student') if request.form.get(c)=='1']
                if action=='save-send' and not contacts: raise ValueError('Select at least one contact for the message request.')
                data = dict(class_name=cls,section=section,subject=subject,channel=channel,contacts=contacts,
                    parent_notification=request.form.get('parent_notification')=='1',
                    message_status='Provider not configured' if action=='save-send' else 'Not requested',
                    notification_status='Provider not configured' if request.form.get('parent_notification')=='1' else 'Not requested')
            row = Entry(kind=kind,campus=campus,title=title,body=body,starts=starts,ends=ends,data=data,token=token)
            db.session.add(row); db.session.flush()
            for name,mime,content in files: db.session.add(Attachment(entry_id=row.id,filename=name,mime=mime,content=content))
            db.session.add(Audit(action='Create student '+kind,data=dict(entry_id=row.id,campus=campus,owner_id=session.get('owner_id'),staff_id=session.get('staff_id'))))
            db.session.commit()
            flash('Saved. Message delivery is unavailable until a provider is connected.' if kind=='diary' and (data['message_status']!='Not requested' or data['parent_notification']) else 'Saved successfully.', 'success')
            return redirect(url_for('student_extras.index',kind=kind))
        query = Entry.query.filter_by(kind=kind)
        # A campus-limited user must not read all-campus posts authored outside their scope.
        allowed = getattr(g,'access_campuses',None)
        if allowed is not None and set(allowed)!=set(app.extensions['staff_access_helpers']['campuses']()): query=query.filter(Entry.campus.in_(allowed))
        for field in ('campus','class_name','section','subject'):
            value = request.args.get(field,'')
            if value:
                if value not in choices(field): raise ValueError('Choose a configured '+field+'.')
                if field=='campus': query=query.filter(Entry.campus.in_(['',value]))
                elif kind=='diary': query=query.filter(Entry.data[field].as_string()==value)
        if request.args.get('from'): query=query.filter(Entry.ends>=day(request.args['from']))
        if request.args.get('to'): query=query.filter(Entry.starts<=day(request.args['to']))
        if request.args.get('from') and request.args.get('to') and day(request.args['from'])>day(request.args['to']): raise ValueError('To must be on or after From.')
        if request.args.get('q'): query=query.filter(Entry.title.ilike('%'+request.args['q'][:180]+'%'))
        try: page = max(1,int(request.args.get('page','1')))
        except ValueError: raise ValueError('Choose a valid page.')
        total=query.count(); rows=query.order_by(Entry.starts.desc(),Entry.id.desc()).offset((page-1)*25).limit(25).all()
        attachments={r.id:Attachment.query.filter_by(entry_id=r.id).all() for r in rows}
        seen_counts={}
        Seen=app.extensions.get('parent_models',{}).get('seen')
        if Seen is not None and rows:
            seen_counts=dict(db.session.query(Seen.entry_id,db.func.count(Seen.id)).filter(Seen.entry_id.in_([r.id for r in rows])).group_by(Seen.entry_id).all())
        section_rows=rm['settings'].query.filter_by(category='section').all()
        return render_template('student_extras.html',title='Student Notice Board' if kind=='notices' else 'Student Diary',kind=kind,creating=creating,rows=rows,attachments=attachments,
            choices={k:choices(k) for k in ('campus','class_name','section','subject')},section_rows=section_rows,
            submission=secrets.token_urlsafe(32),today=today(),page=page,total=total,seen_counts=seen_counts)

    @bp.get('/diary/options')
    def diary_options():
        campus=request.args.get('campus','');cls=request.args.get('class_name','')
        if campus and campus not in choices('campus'):raise ValueError('Choose a configured campus.')
        scope_ok(campus)
        maps=app.extensions['institute_setup_models']['mapping'].query.filter_by(campus=campus).all() if campus else []
        classes=[c for c in choices('class_name') if not maps or any(m.class_name==c and m.active for m in maps)]
        if cls and cls not in classes:raise ValueError('Choose a class at this campus.')
        sections=sorted({r.value for r in rm['settings'].query.filter_by(category='section').all() if not r.class_name or r.class_name==cls}) if cls else []
        subjects=sorted({r.value for r in rm['settings'].query.filter_by(category='subject').all() if cls and (not r.class_name or r.class_name==cls) and app.extensions['school_settings_helpers']['subject_allowed'](campus,cls,r.value)})
        return jsonify(classes=classes,sections=sections,subjects=subjects)

    @bp.get('/attachments/<int:aid>')
    def attachment(aid):
        item=db.get_or_404(Attachment,aid)
        entry=db.get_or_404(Entry,item.entry_id)
        scope_ok(entry.campus)
        response=send_file(io.BytesIO(item.content),mimetype=item.mime,download_name=item.filename,as_attachment=True)
        response.headers['Content-Security-Policy']="default-src 'none'; sandbox"
        return response

    app.register_blueprint(bp)
