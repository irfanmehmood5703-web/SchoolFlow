"""General > Student Leave Approval API (owner-only until staff grants exist)."""
from datetime import date, datetime, timezone
import hmac
from flask import Blueprint, abort, g, jsonify, request, session

def configure_general_leaves(app, db, Student):
    class StudentLeave(db.Model):
        __tablename__ = 'sf_general_student_leave'
        id = db.Column(db.Integer, primary_key=True)
        institute_scope = db.Column(db.String(100), nullable=False, index=True)
        student_id = db.Column(db.Integer, nullable=False, index=True)
        from_date = db.Column(db.Date, nullable=False)
        to_date = db.Column(db.Date, nullable=False)
        leave_type = db.Column(db.String(40), nullable=False)
        reason = db.Column(db.Text, nullable=False)
        comment = db.Column(db.Text)
        status = db.Column(db.String(20), nullable=False, default='Pending')
        created_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

    bp = Blueprint('general_leaves', __name__, url_prefix='/api/general/leaves')
    def guard(write=False):
        identity = getattr(g, 'school_identity', None) or {}
        if identity.get('demo') or not identity.get('scope') or getattr(g, 'staff_principal', None) is not None:
            abort(403)
        if write:
            expected = session.get('record_csrf', '')
            if not expected or not hmac.compare_digest(expected, request.headers.get('X-CSRF-Token', '')):
                abort(400, 'Invalid CSRF token')
        return identity['scope']

    def payload(row):
        return dict(id=row.id, student_id=row.student_id,
                    from_date=row.from_date.isoformat(), to_date=row.to_date.isoformat(),
                    total_days=(row.to_date-row.from_date).days+1,
                    leave_type=row.leave_type, reason=row.reason,
                    comment=row.comment, status=row.status)

    @bp.get('/')
    def listing():
        scope = guard()
        status = request.args.get('status', 'Pending')
        if status not in ('Pending', 'Approved', 'Rejected', 'All'):
            return jsonify(error='Invalid status'), 400
        q = StudentLeave.query.filter_by(institute_scope=scope)
        if status != 'All': q = q.filter_by(status=status)
        return jsonify(items=[payload(x) for x in q.order_by(StudentLeave.id.desc()).limit(100).all()])

    @bp.post('/')
    def submit():
        scope = guard(True)
        data = request.get_json(silent=True) or {}
        try:
            student_id = int(data.get('student_id'))
            start = date.fromisoformat(data.get('from_date', ''))
            end = date.fromisoformat(data.get('to_date', ''))
        except (TypeError, ValueError):
            return jsonify(error='Invalid student or dates'), 400
        reason = str(data.get('reason', '')).strip()
        leave_type = str(data.get('leave_type', '')).strip()
        if not db.session.get(Student, student_id):
            return jsonify(error='Student not found'), 404
        if end < start or (end-start).days > 365 or not 1 <= len(reason) <= 2000 or not 1 <= len(leave_type) <= 40:
            return jsonify(error='Invalid leave details'), 400
        row = StudentLeave(institute_scope=scope, student_id=student_id,
                           from_date=start, to_date=end, reason=reason, leave_type=leave_type)
        db.session.add(row); db.session.commit()
        return jsonify(payload(row)), 201

    @bp.patch('/<int:leave_id>')
    def decide(leave_id):
        scope = guard(True)
        row = StudentLeave.query.filter_by(id=leave_id, institute_scope=scope).first_or_404()
        data = request.get_json(silent=True) or {}
        if row.status != 'Pending' or data.get('status') not in ('Approved', 'Rejected'):
            return jsonify(error='Invalid leave transition'), 409
        comment = str(data.get('comment', ''))
        if len(comment) > 2000:
            return jsonify(error='Comment too long'), 400
        row.status = data['status']; row.comment = comment
        db.session.commit()
        return jsonify(payload(row))

    app.register_blueprint(bp)
    return StudentLeave
