"""General > Complaints & Suggestions, tenant-scoped backend.

Register only with authenticated identity middleware and CSRF session support.
"""
from datetime import datetime, timezone
from flask import Blueprint, abort, g, jsonify, request, session
import hmac

def configure_general_feedback(app, db):
    class Feedback(db.Model):
        __tablename__ = "sf_general_feedback"
        id = db.Column(db.Integer, primary_key=True)
        institute_scope = db.Column(db.String(100), nullable=False, index=True)
        kind = db.Column(db.String(12), nullable=False)
        category = db.Column(db.String(20), nullable=False)
        submitted_by = db.Column(db.String(120), nullable=False)
        campus = db.Column(db.String(120))
        message = db.Column(db.Text, nullable=False)
        response = db.Column(db.Text)
        attachment_ref = db.Column(db.String(255))
        status = db.Column(db.String(20), nullable=False, default="Open")
        created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
        updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

    bp = Blueprint("general_feedback", __name__, url_prefix="/api/general/feedback")
    def guard(write=False):
        identity = getattr(g, "school_identity", None)
        if not identity or identity.get("demo") or not identity.get("scope"):
            abort(403)
        staff = getattr(g, "staff_principal", None)
        if staff is not None:
            abort(403, "Staff access requires an explicit permission grant")
        if write:
            token = request.headers.get("X-CSRF-Token", "")
            expected = session.get("record_csrf", "")
            if not expected or not hmac.compare_digest(token, expected):
                abort(400, "CSRF token missing or invalid")
        return identity["scope"]

    def serialize(row):
        return dict(id=row.id, kind=row.kind, category=row.category,
                    submitted_by=row.submitted_by, campus=row.campus,
                    message=row.message, response=row.response, status=row.status,
                    attachment_ref=row.attachment_ref, created_at=row.created_at.isoformat())

    @bp.get("/")
    def list_feedback():
        scope = guard()
        kind = request.args.get("kind", "complaint")
        category = request.args.get("category", "All")
        status = request.args.get("status", "Open")
        if kind not in ("complaint", "suggestion") or category not in ("All", "Academic", "Non Academic") or status not in ("Open", "Resolved", "Addressed"):
            return jsonify(error="Invalid filter"), 400
        q = Feedback.query.filter_by(institute_scope=scope, kind=kind, status=status)
        if category != "All":
            q = q.filter_by(category=category)
        page = max(1, min(request.args.get("page", 1, type=int), 100000))
        rows = q.order_by(Feedback.created_at.desc(), Feedback.id.desc()).limit(25).offset((page-1)*25).all()
        return jsonify(items=[serialize(x) for x in rows], page=page)

    @bp.post("/")
    def submit_feedback():
        scope = guard(write=True)
        data = request.get_json(silent=True) or {}
        kind, category = data.get("kind"), data.get("category")
        message = str(data.get("message", "")).strip()
        sender = str(data.get("submitted_by", "")).strip()
        if kind not in ("complaint", "suggestion") or category not in ("Academic", "Non Academic") or not (1 <= len(message) <= 5000) or not (1 <= len(sender) <= 120):
            return jsonify(error="Invalid feedback fields"), 400
        row = Feedback(institute_scope=scope, kind=kind, category=category,
                       message=message, submitted_by=sender,
                       campus=str(data.get("campus", ""))[:120])
        db.session.add(row); db.session.commit()
        return jsonify(serialize(row)), 201

    @bp.patch("/<int:feedback_id>")
    def respond(feedback_id):
        scope = guard(write=True)
        row = Feedback.query.filter_by(id=feedback_id, institute_scope=scope).first_or_404()
        data = request.get_json(silent=True) or {}
        status = data.get("status")
        if status not in ("Open", "Resolved" if row.kind == "complaint" else "Addressed"):
            return jsonify(error="Invalid status"), 400
        response = str(data.get("response", ""))
        if len(response) > 5000:
            return jsonify(error="Response too long"), 400
        row.status = status; row.response = response
        row.updated_at = datetime.now(timezone.utc)
        db.session.commit()
        return jsonify(serialize(row))

    app.register_blueprint(bp)
    return Feedback
