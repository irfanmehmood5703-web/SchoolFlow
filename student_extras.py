"""Durable student notices and diaries; no external delivery is implied."""
import hmac
import io
import secrets
import zipfile
import zlib
from xml.etree import ElementTree
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo
from flask import Blueprint, abort, flash, g, redirect, render_template, request, send_file, session, url_for, jsonify
from sqlalchemy.exc import IntegrityError
from werkzeug.utils import secure_filename


DOCX_MIME='application/vnd.openxmlformats-officedocument.wordprocessingml.document'
DOCX_MAIN=DOCX_MIME+'.main+xml'
DOCX_TYPES='{http://schemas.openxmlformats.org/package/2006/content-types}'
DOCX_DOCUMENTS={'{http://schemas.openxmlformats.org/wordprocessingml/2006/main}document','{http://purl.oclc.org/ooxml/wordprocessingml/main}document'}


def valid_word_document(content):
    """Verify a bounded, ordinary OOXML Word document, not an arbitrary ZIP."""
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as document:
            parts=document.infolist()
            if not 1<=len(parts)<=1024 or sum(part.file_size for part in parts)>50*1024*1024:
                return False
            seen=set()
            for part in parts:
                name=part.filename.casefold()
                if (not name or name.startswith('/') or '\\' in name or ':' in name
                        or '..' in name.split('/') or name in seen or part.flag_bits&1
                        or part.compress_type not in (zipfile.ZIP_STORED,zipfile.ZIP_DEFLATED)
                        or 'vbaproject' in name or name.startswith(('word/activex/','word/embeddings/'))):
                    return False
                seen.add(name)
            def xml_part(name,limit):
                info=document.getinfo(name)
                if not 0<info.file_size<=limit:raise ValueError('Word part is too large.')
                with document.open(info) as stream:
                    data=stream.read(limit+1)
                if len(data)>limit or b'\x00' in data or b'<!DOCTYPE' in data.upper() or b'<!ENTITY' in data.upper():
                    raise ValueError('Unsafe Word XML.')
                return ElementTree.fromstring(data)
            types=xml_part('[Content_Types].xml',512*1024)
            if types.tag!=DOCX_TYPES+'Types':return False
            if any('macroenabled' in item.get('ContentType','').casefold() or 'vba' in item.get('ContentType','').casefold() for item in types):
                return False
            if not any(item.tag==DOCX_TYPES+'Override' and item.get('PartName')=='/word/document.xml' and item.get('ContentType')==DOCX_MAIN for item in types):
                return False
            relationship_tag='{http://schemas.openxmlformats.org/package/2006/relationships}'
            rels=xml_part('_rels/.rels',512*1024)
            if rels.tag!=relationship_tag+'Relationships' or not any(
                    r.tag==relationship_tag+'Relationship' and r.get('Type','').endswith('/officeDocument')
                    and r.get('Target','').lstrip('/')=='word/document.xml' and r.get('TargetMode')!='External'
                    for r in rels):
                return False
            # Ordinary hyperlinks are fine; reject external templates and other
            # automatically fetched relationships in a school worksheet.
            for part in parts:
                if part.filename.endswith('.rels'):
                    relationships=xml_part(part.filename,512*1024)
                    if relationships.tag!=relationship_tag+'Relationships' or any(
                            r.get('TargetMode','').casefold()=='external' and not r.get('Type','').endswith('/hyperlink')
                            for r in relationships):
                        return False
            return xml_part('word/document.xml',8*1024*1024).tag in DOCX_DOCUMENTS
    except (zipfile.BadZipFile,KeyError,ValueError,RuntimeError,OSError,NotImplementedError,ElementTree.ParseError,EOFError,zlib.error,OverflowError):
        return False


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
            # Get the suffix before sanitising or shortening the name so long
            # or Urdu filenames keep their original, validated file type.
            raw_name = f.filename.replace('\\','/').rsplit('/',1)[-1]
            stem, dot, suffix = raw_name.rpartition('.')
            ext = suffix.lower() if dot else ''
            safe_stem = secure_filename(stem if dot else raw_name) or 'attachment-'+str(len(result)+1)
            name = safe_stem[:179-len(ext)]+'.'+ext if ext else safe_stem[:180]
            content = f.read(5 * 1024 * 1024 + 1)
            total += len(content)
            if not content or len(content) > 5 * 1024 * 1024 or total > 15 * 1024 * 1024:
                raise ValueError('Files must be nonempty, up to 5 MB each and 15 MB combined.')
            mime = {'jpg':'image/jpeg','jpeg':'image/jpeg','png':'image/png','webp':'image/webp','pdf':'application/pdf','mp3':'audio/mpeg','mp4':'video/mp4','docx':DOCX_MIME}.get(ext)
            valid = False
            if ext in ('jpg','jpeg','png','webp'):
                from PIL import Image, UnidentifiedImageError
                try:
                    with Image.open(io.BytesIO(content)) as image:
                        expected = image.format == {'jpg':'JPEG','jpeg':'JPEG','png':'PNG','webp':'WEBP'}[ext]
                        image.verify()
                        valid = expected
                except (OSError, ValueError, UnidentifiedImageError, Image.DecompressionBombError): pass
            elif ext == 'pdf': valid = content.startswith(b'%PDF-')
            elif ext == 'mp3': valid = content.startswith(b'ID3') or (len(content)>1 and content[0]==255 and content[1]&224==224)
            elif ext == 'mp4': valid = len(content)>12 and content[4:8]==b'ftyp'
            elif ext == 'docx': valid = valid_word_document(content)
            if not mime or not valid: raise ValueError(f'Attachment {name[:100]} was not accepted. Use valid JPG, PNG, WebP, PDF, Word (.docx), MP3 or MP4 attachments. Older .doc and macro-enabled Word files are not supported.')
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

    app.extensions['student_extra_uploads']=uploads
    app.register_blueprint(bp)
