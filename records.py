"""Reference-based admissions and employee records.

Extends the starter database with separate tables, preserving legacy records.
No outgoing SMS is sent: requested communication is recorded as unconfigured.
"""
import csv
import hashlib
import hmac
import io
import json
import re
import secrets
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation

from flask import Blueprint, abort, flash, jsonify, redirect, render_template, request, send_file, session, url_for
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from werkzeug.security import generate_password_hash
from werkzeug.utils import secure_filename

from record_schema import (CATEGORIES, DEMO_CHOICES, EMPLOYEE_SECTIONS, FAMILY_KEYS,
                           STUDENT_COMMUNICATION, STUDENT_SECTIONS)

MAX_FILE = 5 * 1024 * 1024
MAX_ATTACHMENTS = 20
ALLOWED_DOCUMENTS = {"pdf", "png", "jpg", "jpeg", "webp", "doc", "docx", "xls", "xlsx", "txt"}


def configure_records(app, db, Student, Employee):
    bp = Blueprint("records", __name__, url_prefix="/records")
    if app.config.get("MAX_CONTENT_LENGTH") is None:
        app.config["MAX_CONTENT_LENGTH"] = 25 * 1024 * 1024

    class RecordSettings(db.Model):
        __tablename__ = "record_settings"
        id = db.Column(db.Integer, primary_key=True)
        category = db.Column(db.String(60), nullable=False)
        value = db.Column(db.String(160), nullable=False)
        class_name = db.Column(db.String(160), nullable=False, default="")
        __table_args__ = (db.UniqueConstraint("category", "value", "class_name"),)

    class RecordFamily(db.Model):
        __tablename__ = "record_family"
        id = db.Column(db.Integer, primary_key=True)
        number = db.Column(db.String(60), unique=True, nullable=False)
        data = db.Column(db.JSON, nullable=False, default=dict)

    class StudentDetails(db.Model):
        __tablename__ = "student_details"
        id = db.Column(db.Integer, primary_key=True)
        student_id = db.Column(db.Integer, db.ForeignKey("student.id"), unique=True, nullable=False)
        family_id = db.Column(db.Integer, db.ForeignKey("record_family.id"))
        data = db.Column(db.JSON, nullable=False, default=dict)
        updated_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

    class EmployeeDetails(db.Model):
        __tablename__ = "employee_details"
        id = db.Column(db.Integer, primary_key=True)
        employee_id = db.Column(db.Integer, db.ForeignKey("employee.id"), unique=True, nullable=False)
        data = db.Column(db.JSON, nullable=False, default=dict)
        username = db.Column(db.String(120), unique=True)
        password_hash = db.Column(db.String(300))
        app_active = db.Column(db.Boolean, nullable=False, default=True)
        updated_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

    class RecordFile(db.Model):
        __tablename__ = "record_file"
        id = db.Column(db.Integer, primary_key=True)
        owner_kind = db.Column(db.String(10), nullable=False)
        owner_id = db.Column(db.Integer, nullable=False)
        title = db.Column(db.String(180), nullable=False)
        filename = db.Column(db.String(180), nullable=False)
        mime = db.Column(db.String(100), nullable=False)
        photo = db.Column(db.Boolean, nullable=False, default=False)
        content = db.Column(db.LargeBinary, nullable=False)
        sha256 = db.Column(db.String(64), nullable=False)

    class RecordEvent(db.Model):
        __tablename__ = "record_event"
        id = db.Column(db.Integer, primary_key=True)
        owner_kind = db.Column(db.String(10), nullable=False)
        owner_id = db.Column(db.Integer, nullable=False)
        action = db.Column(db.String(60), nullable=False)
        created_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

    class CommunicationRequest(db.Model):
        __tablename__ = "communication_request"
        id = db.Column(db.Integer, primary_key=True)
        student_id = db.Column(db.Integer, db.ForeignKey("student.id"), nullable=False)
        preferences = db.Column(db.JSON, nullable=False)
        status = db.Column(db.String(40), nullable=False, default="Provider not configured")
        created_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

    app.extensions["record_models"] = dict(settings=RecordSettings, family=RecordFamily,
        student=StudentDetails, employee=EmployeeDetails, file=RecordFile,
        event=RecordEvent, communication=CommunicationRequest)

    @app.context_processor
    def record_context():
        if "record_csrf" not in session:
            session["record_csrf"] = secrets.token_urlsafe(32)
        return {"record_csrf": session["record_csrf"]}

    @bp.before_request
    def validate_csrf():
        if request.method == "POST":
            token = request.form.get("_csrf", "")
            if not hmac.compare_digest(session.get("record_csrf", "").encode(), token.encode()) or not token:
                abort(400, "Your form session expired. Reload the page and try again.")

    def setup_choices():
        result = {k: [] for k in CATEGORIES}
        for row in RecordSettings.query.order_by(RecordSettings.value).all():
            result.setdefault(row.category, []).append((row.value, row.value, row.class_name))
        return result

    def defaults(kind):
        if kind == "student":
            data = dict(admission_date=date.today().isoformat(), family_mode="new", religion="Islam",
                nationality="Pakistani", guardian_relation="Father", status="Active", subjects=[],
                visitors=[{} for _ in range(3)], father_contact=True, app_sms=True, parent_notification=True)
        else:
            highest = db.session.query(db.func.max(Employee.id)).scalar() or 0
            candidate = str(highest + 1)
            while Employee.query.filter_by(employee_no=candidate).first():
                highest += 1
                candidate = str(highest + 1)
            data = dict(employee_no=candidate, marital_status="Married", joining_date=date.today().isoformat(),
                lecture_assigned="0", app_active=True, diary_approval="required", award_permission="update",
                attendance_permission="update", contact_absentee="not_allowed", fee_access="not_allowed",
                salary_access="not_allowed")
        return data

    def read_data(kind, obj):
        model = StudentDetails if kind == "student" else EmployeeDetails
        key = "student_id" if kind == "student" else "employee_id"
        detail = model.query.filter_by(**{key: obj.id}).first()
        data = defaults(kind)
        if detail:
            data.update(detail.data or {})
        base = ("name", "admission_no", "father", "class_name", "phone", "status") if kind == "student" else ("name", "employee_no", "role", "phone", "status")
        for key in base:
            data[key] = getattr(obj, key)
        if kind == "student":
            data["bio_id"] = data.get("bio_id") or str(obj.id)
            if detail and detail.family_id:
                family = db.session.get(RecordFamily, detail.family_id)
                if family:
                    data.update(family.data)
                    data.update(family_no=family.number, family_id=str(family.id), family_mode="existing")
        else:
            data["username"] = detail.username if detail else ""
            data["app_active"] = detail.app_active if detail else False
            data.pop("password", None)
        return data

    def validate_form(kind, obj):
        sections = STUDENT_SECTIONS if kind == "student" else EMPLOYEE_SECTIONS
        errors, data = {}, {}
        choices = setup_choices()
        for _, fields in sections:
            for f in fields:
                key = f["key"]
                value = request.form.get(key, "").strip()
                if f["kind"] == "checkbox":
                    data[key] = key in request.form
                    continue
                if f["kind"] == "subjects":
                    data[key] = request.form.getlist(key)
                    continue
                data[key] = value
                if f["required"] and not value:
                    errors[key] = "This field is required."
                if len(value) > (5000 if f["kind"] == "textarea" else 160):
                    errors[key] = "This value is too long."
                if value and f["kind"] == "date":
                    try:
                        date.fromisoformat(value)
                    except ValueError:
                        errors[key] = "Enter a valid date."
                if value and f["kind"] == "email" and not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
                    errors[key] = "Enter a valid email address."
                if value and f["kind"] == "digits" and not re.fullmatch(r"[0-9]+", value):
                    errors[key] = "Use digits only."
                if value and f["kind"] in ("number", "integer"):
                    try:
                        num = Decimal(value)
                        if not num.is_finite() or num < 0 or (f["kind"] == "integer" and num != num.to_integral_value()):
                            raise InvalidOperation
                    except InvalidOperation:
                        errors[key] = "Enter a non-negative " + ("whole number." if f["kind"] == "integer" else "number.")
                if value and (f["options"] or f["category"]):
                    allowed = {str(o[0]) for o in f["options"]} if f["options"] else {o[0] for o in choices.get(f["category"], [])}
                    # Preserve a legacy value on update even if a setting was removed.
                    if obj:
                        allowed.add(str(read_data(kind, obj).get(key, "")))
                    if value not in allowed:
                        errors[key] = "Select a configured value."
        if kind == "student":
            # The reference makes Admission No optional. The starter schema does not.
            if not data["admission_no"]:
                data["admission_no"] = obj.admission_no if obj else "SF-" + secrets.token_hex(6).upper()
            if Student.query.filter(Student.admission_no == data["admission_no"], Student.id != (obj.id if obj else 0)).first():
                errors["admission_no"] = "This admission number is already in use."
            if data["family_mode"] == "existing":
                family = db.session.get(RecordFamily, int(data["family_id"])) if data.get("family_id", "").isdigit() else None
                if not family:
                    errors["family_id"] = "Select an existing family."
                elif data.get("family_no") and data["family_no"] != family.number:
                    errors["family_no"] = "Family number must match the selected existing family."
            elif data["family_mode"] == "new" and data.get("family_no") and RecordFamily.query.filter_by(number=data["family_no"]).first():
                errors["family_no"] = "This family exists. Select Existing Family to link siblings."
            data["visitors"] = [{k: request.form.get(f"visitor_{i}_{k}", "").strip()[:500]
                for k in ["name", "phone", "relation", "address", "notes"]} for i in range(3)]
            for key, _ in STUDENT_COMMUNICATION:
                data[key] = key in request.form
            valid_subjects = {x[0] for x in choices.get("subject", []) if not x[2] or x[2] == data.get("class_name")}
            if any(s not in valid_subjects for s in data["subjects"]):
                errors["subjects"] = "Choose subjects assigned to the selected class."
            if data.get("leaving_date") and data.get("admission_date") and data["leaving_date"] < data["admission_date"]:
                errors["leaving_date"] = "Leaving date cannot be before admission date."
            if data.get("birth_date") and data.get("admission_date") and data["birth_date"] > data["admission_date"]:
                errors["birth_date"] = "Date of birth cannot be after admission date."
            if data.get("board_obtained") and not errors.get("board_obtained"):
                if not data.get("board_total"):
                    errors["board_total"] = "Total marks are required when obtained marks are entered."
                elif not errors.get("board_total") and Decimal(data["board_obtained"]) > Decimal(data["board_total"]):
                    errors["board_obtained"] = "Obtained marks cannot exceed total marks."
        else:
            if Employee.query.filter(Employee.employee_no == data["employee_no"], Employee.id != (obj.id if obj else 0)).first():
                errors["employee_no"] = "This employee code is already in use."
            username = data.get("username", "").casefold()
            data["username"] = username
            if username and not re.fullmatch(r"[a-z0-9_.@+-]{3,120}", username):
                errors["username"] = "Use 3–120 letters, numbers or _.@+- characters."
            if username and EmployeeDetails.query.filter(EmployeeDetails.username == username, EmployeeDetails.employee_id != (obj.id if obj else 0)).first():
                errors["username"] = "This username is already in use."
            old = EmployeeDetails.query.filter_by(employee_id=obj.id).first() if obj else None
            if data.get("password") and len(data["password"]) < 10:
                errors["password"] = "Use a password with at least 10 characters."
            if username and not data.get("password") and not (old and old.password_hash):
                errors["password"] = "Set a password for this new username."
            if data.get("password") and not username:
                errors["username"] = "Enter a username for these credentials."
        pairs = [("qualification_from", "qualification_to"), ("probation_from", "probation_to")]
        for start, end in pairs:
            if data.get(start) and data.get(end) and data[start] > data[end]:
                errors[end] = "End date cannot be before start date."
        return data, errors

    def incoming_files():
        errors, result = {}, []
        photo = request.files.get("photo")
        docs = request.files.getlist("documents")
        titles = request.form.getlist("document_title")
        if len(docs) > MAX_ATTACHMENTS:
            errors["documents"] = "A maximum of 20 documents can be added at once."
        for i, item in enumerate(([photo] if photo and photo.filename else []) + [d for d in docs if d.filename]):
            is_photo = item is photo
            content = item.read(MAX_FILE + 1)
            filename = secure_filename(item.filename)[:180]
            ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
            if not filename or not content or len(content) > MAX_FILE:
                errors["photo" if is_photo else "documents"] = "Use non-empty files up to 5 MB each."
                continue
            if ext not in ALLOWED_DOCUMENTS:
                errors["documents"] = "This file type is not supported."
                continue
            mime = "application/octet-stream"
            if is_photo:
                if ext not in {"jpg", "jpeg", "png", "webp"}:
                    errors["photo"] = "Use a JPG, PNG or WebP image."
                    continue
                if content.startswith(b"\x89PNG\r\n\x1a\n"):
                    mime = "image/png"
                elif content[:3] == b"\xff\xd8\xff":
                    mime = "image/jpeg"
                elif content[:4] == b"RIFF" and content[8:12] == b"WEBP":
                    mime = "image/webp"
                else:
                    errors["photo"] = "Use a JPG, PNG or WebP image."
                    continue
            doc_index = docs.index(item) if not is_photo else None
            title = "Profile Photo" if is_photo else (titles[doc_index].strip() if doc_index < len(titles) else "")
            if not title:
                errors["documents"] = "Enter an attachment title for each selected document."
                continue
            result.append(dict(title=title[:180], filename=filename, mime=mime, photo=is_photo,
                content=content, sha256=hashlib.sha256(content).hexdigest()))
        return result, errors

    def get_obj(kind, id):
        return db.get_or_404(Student if kind == "student" else Employee, id)

    def render_form(kind, obj=None, data=None, errors=None, response_status=200):
        data = data if data is not None else (read_data(kind, obj) if obj else defaults(kind))
        files = RecordFile.query.filter_by(owner_kind=kind, owner_id=obj.id).all() if obj else []
        photo = next((f for f in files if f.photo), None)
        families = RecordFamily.query.order_by(RecordFamily.number).all()
        return render_template("record_form.html", kind=kind, obj=obj, data=data, errors=errors or {},
            sections=STUDENT_SECTIONS if kind == "student" else EMPLOYEE_SECTIONS,
            choices=setup_choices(), families=families, photo=photo, files=[f for f in files if not f.photo],
            communication=STUDENT_COMMUNICATION, title=("Update " if obj else "Add ")+kind.title()), response_status

    def save_record(kind, obj=None):
        data, errors = validate_form(kind, obj)
        files, file_errors = incoming_files()
        errors.update(file_errors)
        if errors:
            data.pop("password", None)
            return render_form(kind, obj, data, errors, 422)
        created = obj is None
        try:
            if kind == "student":
                obj = obj or Student()
                for key in ("name", "admission_no", "father", "class_name", "phone", "status"):
                    setattr(obj, key, data[key])
                db.session.add(obj)
                db.session.flush()
                if not data.get("bio_id"):
                    data["bio_id"] = str(obj.id)
                if data["family_mode"] == "existing":
                    family = db.session.get(RecordFamily, int(data["family_id"]))
                    # Existing-family details are authoritative. Editing one sibling
                    # must not silently rewrite every other sibling's family.
                    data.update(family.data)
                    obj.father, obj.phone = data["father"], data["phone"]
                else:
                    number = data.get("family_no") or "F-" + secrets.token_hex(5).upper()
                    family = RecordFamily(number=number, data={k: data.get(k, "") for k in FAMILY_KEYS})
                    db.session.add(family)
                    db.session.flush()
                data.update(family_id=str(family.id), family_no=family.number)
                detail = StudentDetails.query.filter_by(student_id=obj.id).first() or StudentDetails(student_id=obj.id)
                detail.family_id = family.id
                detail.data = data
                if data.get("send_sms") or data.get("parent_notification"):
                    db.session.add(CommunicationRequest(student_id=obj.id,
                        preferences={k: data[k] for k, _ in STUDENT_COMMUNICATION}))
            else:
                obj = obj or Employee()
                for key in ("name", "employee_no", "role", "phone"):
                    setattr(obj, key, data[key])
                if created:
                    obj.salary, obj.status = 0, "Active"
                db.session.add(obj)
                db.session.flush()
                detail = EmployeeDetails.query.filter_by(employee_id=obj.id).first() or EmployeeDetails(employee_id=obj.id)
                detail.username = data.get("username") or None
                if data.get("password"):
                    detail.password_hash = generate_password_hash(data.pop("password"))
                else:
                    data.pop("password", None)
                detail.app_active = bool(data.get("app_active"))
                detail.data = data
            detail.updated_at = datetime.now(timezone.utc)
            db.session.add(detail)
            remove_ids = request.form.getlist("remove_document")
            for fid in remove_ids:
                if not fid.isdigit():
                    continue
                f = RecordFile.query.filter_by(id=int(fid), owner_kind=kind, owner_id=obj.id, photo=False).first()
                if f:
                    db.session.delete(f)
            if request.form.get("remove_photo") or any(f["photo"] for f in files):
                RecordFile.query.filter_by(owner_kind=kind, owner_id=obj.id, photo=True).delete()
            for f in files:
                db.session.add(RecordFile(owner_kind=kind, owner_id=obj.id, **f))
            db.session.add(RecordEvent(owner_kind=kind, owner_id=obj.id, action="Created" if created else "Updated"))
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            errors["form"] = "A record with that number or username was just added. Review the values and retry."
            data.pop("password", None)
            return render_form(kind, obj if not created else None, data, errors, 409)
        flash(kind.title()+" record saved successfully.", "success")
        if kind == "student" and (data.get("send_sms") or data.get("parent_notification")):
            flash("Communication preferences saved. No message was sent: delivery integration is not configured.", "info")
        action = request.form.get("save_action", "back")
        if action == "new":
            return redirect(url_for("records.new_record", kind=kind))
        if action == "view":
            return redirect(url_for("records.record_detail", kind=kind, id=obj.id))
        if kind == "employee" and action == "salary":
            return redirect(url_for("records.salary_handoff", id=obj.id))
        return redirect(url_for("records.record_list", kind=kind))

    @bp.route("/<kind>/new", methods=["GET", "POST"])
    def new_record(kind):
        if kind not in ("student", "employee"):
            abort(404)
        return save_record(kind) if request.method == "POST" else render_form(kind)

    @bp.route("/<kind>/<int:id>/edit", methods=["GET", "POST"])
    def edit_record(kind, id):
        if kind not in ("student", "employee"):
            abort(404)
        obj = get_obj(kind, id)
        return save_record(kind, obj) if request.method == "POST" else render_form(kind, obj)

    def filtered_rows(kind):
        model = Student if kind == "student" else Employee
        q = request.args.get("q", "").strip()[:160]
        query = model.query
        if q:
            pattern = "%"+q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")+"%"
            number = model.admission_no if kind == "student" else model.employee_no
            query = query.filter(or_(model.name.ilike(pattern, escape="\\"), number.ilike(pattern, escape="\\"), model.phone.ilike(pattern, escape="\\")))
        status = request.args.get("status", "Active")
        if status:
            query = query.filter(model.status == status)
        result = [(obj, read_data(kind, obj)) for obj in query.order_by(model.id.desc()).all()]
        for key in ("campus", "class_name", "section", "gender", "role"):
            value = request.args.get(key, "")
            if value:
                result = [(o, d) for o, d in result if d.get(key) == value]
        return result

    @bp.route("/<kind>")
    def record_list(kind):
        if kind not in ("student", "employee"):
            abort(404)
        result = filtered_rows(kind)
        model = Student if kind == "student" else Employee
        try:
            page = max(1, int(request.args.get("page", 1)))
            limit = min(100, max(10, int(request.args.get("limit", 25))))
        except ValueError:
            abort(400)
        total = len(result)
        page = min(page, max(1, (total + limit - 1)//limit))
        return render_template("record_list.html", title="Manage "+("Students" if kind == "student" else "Employees"),
            kind=kind, rows=result[(page-1)*limit:page*limit], total=total, page=page, limit=limit,
            pages=max(1, (total+limit-1)//limit), choices=setup_choices(),
            active=model.query.filter_by(status="Active").count(), all_count=model.query.count())

    @bp.route("/<kind>/<int:id>")
    def record_detail(kind, id):
        if kind not in ("student", "employee"):
            abort(404)
        obj = get_obj(kind, id)
        data = read_data(kind, obj)
        sections = STUDENT_SECTIONS if kind == "student" else EMPLOYEE_SECTIONS
        files = RecordFile.query.filter_by(owner_kind=kind, owner_id=id).all()
        events = RecordEvent.query.filter_by(owner_kind=kind, owner_id=id).order_by(RecordEvent.id.desc()).limit(20).all()
        return render_template("record_detail.html", title=obj.name, kind=kind, obj=obj, data=data,
            sections=sections, files=files, events=events)

    @bp.route("/employee/<int:id>/salary-plan")
    def salary_handoff(id):
        obj = get_obj("employee", id)
        # Do not invent salary deductions or make the old basic-salary field
        # masquerade as the full reference payroll workflow.
        return redirect(url_for("ops.plans", employee_id=obj.id))

    @bp.route("/families/<int:id>")
    def family_data(id):
        family = db.get_or_404(RecordFamily, id)
        return jsonify({**family.data, "family_no": family.number})

    @bp.route("/files/<int:id>")
    def record_file(id):
        f = db.get_or_404(RecordFile, id)
        response = send_file(io.BytesIO(f.content), mimetype=f.mime,
            as_attachment=not f.photo, download_name=f.filename, max_age=0)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Cache-Control"] = "private, no-store"
        return response

    @bp.route("/<kind>/export.csv")
    def export(kind):
        if kind not in ("student", "employee"):
            abort(404)
        fields = [f for _, fs in (STUDENT_SECTIONS if kind == "student" else EMPLOYEE_SECTIONS)
                  for f in fs if f["kind"] != "password"]
        stream = io.StringIO(newline="")
        writer = csv.writer(stream)
        writer.writerow(["SID" if kind == "student" else "ID"]+[f["label"] for f in fields])
        def cell(value):
            text = ", ".join(str(v) for v in value) if isinstance(value, list) else str(value or "")
            return "'"+text if text.lstrip().startswith(("=", "+", "-", "@", "\t", "\r")) else text
        for obj, data in filtered_rows(kind):
            writer.writerow([obj.id]+[cell(data.get(f["key"], "")) for f in fields])
        response = app.response_class("\ufeff"+stream.getvalue(), mimetype="text/csv")
        response.headers["Content-Disposition"] = f'attachment; filename="schoolflow-{kind}-records.csv"'
        return response

    @bp.route("/settings", methods=["GET", "POST"])
    def settings():
        errors = {}
        if request.method == "POST":
            category = request.form.get("category", "")
            value = request.form.get("value", "").strip()[:160]
            class_name = request.form.get("class_name", "").strip()[:160] if category == "subject" else ""
            if category not in CATEGORIES or not value:
                errors["form"] = "Choose a category and enter a value."
            elif RecordSettings.query.filter_by(category=category, value=value, class_name=class_name).first():
                errors["form"] = "That option is already configured."
            else:
                db.session.add(RecordSettings(category=category, value=value, class_name=class_name))
                db.session.commit()
                flash("Record option added.", "success")
                return redirect(url_for("records.settings"))
        return render_template("record_settings.html", title="Record Settings", categories=CATEGORIES,
            choices=setup_choices(), errors=errors), 422 if errors else 200

    app.register_blueprint(bp)

    @app.cli.command("seed-record-demo-options")
    def seed_demo_options():
        """Add editable, fictional demo dropdown values; never real reference data."""
        for category, values in DEMO_CHOICES.items():
            for value in values:
                if not RecordSettings.query.filter_by(category=category, value=value, class_name="").first():
                    db.session.add(RecordSettings(category=category, value=value, class_name=""))
        db.session.commit()
        print("Fictional demo dropdown options configured.")

    return bp
