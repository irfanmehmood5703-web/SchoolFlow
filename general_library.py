"""SchoolFlow General > Library foundation.

Opt-in registration only. Do not expose routes without a verified institute context
and a role/permission check supplied by the host application.
"""
from datetime import datetime, timezone
from flask import Blueprint, jsonify, request, abort, session
import hmac
from datetime import timedelta
from sqlalchemy import UniqueConstraint, Index, text

def configure_library(app, db, resolve_institute, require_permission):
    """Wire with trusted callbacks from the existing identity/permissions layer.

    resolve_institute() -> stable tenant ID from authenticated server session.
    require_permission(permission_name) -> raise/abort unless authorized.
    """
    class LibraryBook(db.Model):
        __tablename__ = "sf_library_books"
        id = db.Column(db.Integer, primary_key=True)
        institute_id = db.Column(db.String(100), nullable=False, index=True)
        isbn = db.Column(db.String(32))
        title = db.Column(db.String(240), nullable=False)
        author = db.Column(db.String(160))
        category = db.Column(db.String(100))
        __table_args__ = (UniqueConstraint("id", "institute_id"),)

    class LibraryCopy(db.Model):
        __tablename__ = "sf_library_copies"
        id = db.Column(db.Integer, primary_key=True)
        institute_id = db.Column(db.String(100), nullable=False, index=True)
        book_id = db.Column(db.Integer, nullable=False)
        accession = db.Column(db.String(100), nullable=False)
        condition = db.Column(db.String(30), nullable=False, default="Good")
        __table_args__ = (UniqueConstraint("institute_id", "accession"),)

    class LibraryLoan(db.Model):
        __tablename__ = "sf_library_loans"
        id = db.Column(db.Integer, primary_key=True)
        institute_id = db.Column(db.String(100), nullable=False, index=True)
        copy_id = db.Column(db.Integer, nullable=False)
        borrower_type = db.Column(db.String(20), nullable=False)
        borrower_id = db.Column(db.String(100), nullable=False)
        issued_at = db.Column(db.DateTime(timezone=True), nullable=False)
        due_at = db.Column(db.DateTime(timezone=True), nullable=False)
        returned_at = db.Column(db.DateTime(timezone=True))
        status = db.Column(db.String(20), nullable=False, default="Issued")
        __table_args__ = (Index("ix_sf_library_one_open_loan", "institute_id", "copy_id", unique=True, sqlite_where=text("returned_at IS NULL"), postgresql_where=text("returned_at IS NULL")),)

    class LibrarySettings(db.Model):
        __tablename__ = "sf_library_settings"
        institute_id = db.Column(db.String(100), primary_key=True)
        max_student_loans = db.Column(db.Integer, nullable=False, default=3)
        max_employee_loans = db.Column(db.Integer, nullable=False, default=5)
        default_loan_days = db.Column(db.Integer, nullable=False, default=14)
        fine_per_day = db.Column(db.Numeric(10, 2), nullable=False, default=0)

    bp = Blueprint("sf_library", __name__, url_prefix="/api/general/library")

    def guard(permission):
        tenant = resolve_institute()
        if not tenant:
            abort(401)
        require_permission(permission)
        if request.method not in ("GET", "HEAD"):
            expected = session.get("record_csrf", "")
            supplied = request.headers.get("X-CSRF-Token", "")
            if not expected or not hmac.compare_digest(expected, supplied):
                abort(400, "CSRF validation failed")
        return str(tenant)

    @bp.get("/settings")
    def settings():
        tenant = guard("library.view")
        row = db.session.get(LibrarySettings, tenant)
        return jsonify(max_student_loans=row.max_student_loans if row else 3,
                       max_employee_loans=row.max_employee_loans if row else 5,
                       default_loan_days=row.default_loan_days if row else 14,
                       fine_per_day=str(row.fine_per_day) if row else "0.00")

    @bp.put("/settings")
    def save_settings():
        tenant = guard("library.manage")
        data = request.get_json(silent=True) or {}
        from decimal import Decimal, InvalidOperation
        try:
            student = int(data["max_student_loans"])
            employee = int(data["max_employee_loans"])
            days = int(data["default_loan_days"])
            fine = Decimal(str(data["fine_per_day"]))
        except (KeyError, ValueError, TypeError, InvalidOperation):
            return jsonify(error="Invalid lending settings"), 400
        if not (1 <= student <= 50 and 1 <= employee <= 50 and 1 <= days <= 90 and
                fine.is_finite() and Decimal("0") <= fine <= Decimal("10000") and
                fine.as_tuple().exponent >= -2):
            return jsonify(error="Settings outside permitted limits"), 400
        row = db.session.get(LibrarySettings, tenant)
        if row is None:
            row = LibrarySettings(institute_id=tenant)
            db.session.add(row)
        row.max_student_loans = student
        row.max_employee_loans = employee
        row.default_loan_days = days
        row.fine_per_day = fine
        db.session.commit()
        return jsonify(saved=True)

    @bp.get("/reports/summary")
    def summary():
        tenant = guard("library.view")
        from sqlalchemy import func
        books = db.session.query(func.count(LibraryBook.id)).filter_by(institute_id=tenant).scalar()
        copies = db.session.query(func.count(LibraryCopy.id)).filter_by(institute_id=tenant).scalar()
        active = db.session.query(func.count(LibraryLoan.id)).filter_by(institute_id=tenant, returned_at=None).scalar()
        overdue = db.session.query(func.count(LibraryLoan.id)).filter(
            LibraryLoan.institute_id == tenant, LibraryLoan.returned_at.is_(None),
            LibraryLoan.due_at < datetime.now(timezone.utc)).scalar()
        return jsonify(titles=books, copies=copies, issued=active, overdue=overdue)

    @bp.get("/catalogue")
    def catalogue():
        tenant = guard("library.view")
        term = request.args.get("q", "").strip()[:120]
        query = LibraryBook.query.filter_by(institute_id=tenant)
        if term:
            query = query.filter(LibraryBook.title.ilike("%" + term.replace("%", r"\%").replace("_", r"\_") + "%"))
        rows = query.order_by(LibraryBook.id.desc()).limit(100).all()
        return jsonify([{"id": b.id, "title": b.title, "author": b.author,
                         "isbn": b.isbn, "category": b.category} for b in rows])

    @bp.post("/catalogue")
    def add_book():
        tenant = guard("library.manage")
        payload = request.get_json(silent=True) or {}
        title = str(payload.get("title", "")).strip()
        if not 1 <= len(title) <= 240:
            return jsonify(error="Title required (max 240 characters)"), 400
        book = LibraryBook(institute_id=tenant, title=title,
                           author=str(payload.get("author", ""))[:160],
                           isbn=str(payload.get("isbn", ""))[:32],
                           category=str(payload.get("category", ""))[:100])
        db.session.add(book)
        db.session.commit()
        return jsonify(id=book.id), 201

    @bp.get("/loans")
    def loans():
        tenant = guard("library.view")
        rows = LibraryLoan.query.filter_by(institute_id=tenant).order_by(
            LibraryLoan.id.desc()).limit(100).all()
        return jsonify([{"id": x.id, "copy_id": x.copy_id,
                         "borrower_type": x.borrower_type, "borrower_id": x.borrower_id,
                         "status": x.status, "due_at": x.due_at.isoformat()} for x in rows])

    @bp.post("/return/<int:loan_id>")
    def return_book(loan_id):
        tenant = guard("library.issue_return")
        loan = LibraryLoan.query.filter_by(id=loan_id, institute_id=tenant).first_or_404()
        if loan.returned_at is not None:
            return jsonify(error="Already returned"), 409
        loan.returned_at = datetime.now(timezone.utc)
        loan.status = "Returned"
        db.session.commit()
        return jsonify(id=loan.id, status=loan.status)


    @bp.post("/copies")
    def add_copy():
        tenant = guard("library.manage")
        data = request.get_json(silent=True) or {}
        try:
            book_id = int(data.get("book_id"))
        except (ValueError, TypeError):
            return jsonify(error="Valid book_id required"), 400
        book = LibraryBook.query.filter_by(id=book_id, institute_id=tenant).first()
        accession = str(data.get("accession", "")).strip()
        if not book or not 1 <= len(accession) <= 100:
            return jsonify(error="Book or accession invalid"), 400
        if LibraryCopy.query.filter_by(institute_id=tenant, accession=accession).first():
            return jsonify(error="Accession already exists"), 409
        copy = LibraryCopy(institute_id=tenant, book_id=book.id, accession=accession)
        db.session.add(copy)
        db.session.commit()
        return jsonify(id=copy.id, accession=copy.accession), 201

    @bp.post("/issue")
    def issue_book():
        tenant = guard("library.issue_return")
        data = request.get_json(silent=True) or {}
        try:
            copy_id = int(data.get("copy_id"))
            days = int(data.get("days", 14))
        except (ValueError, TypeError):
            return jsonify(error="Invalid copy or loan duration"), 400
        kind = data.get("borrower_type")
        borrower_id = str(data.get("borrower_id", "")).strip()
        if kind not in ("student", "employee") or not 1 <= len(borrower_id) <= 100 or not 1 <= days <= 90:
            return jsonify(error="Invalid borrower or loan duration"), 400
        # Borrowers must exist in the current institute database.\n        from flask import current_app\n        model = current_app.extensions.get("schoolflow_library_borrower_models", {}).get(kind)\n        if model is None:\n            return jsonify(error="Borrower directory not configured"), 503\n        try:\n            borrower_pk = int(borrower_id)\n        except ValueError:\n            return jsonify(error="Borrower ID must be numeric"), 400\n        if db.session.get(model, borrower_pk) is None:\n            return jsonify(error="Borrower not found"), 404\n        copy = LibraryCopy.query.filter_by(id=copy_id, institute_id=tenant).first()
        if not copy or copy.condition not in ("Good", "Fair"):
            return jsonify(error="Copy unavailable"), 404
        # Serialize competing issue requests on supported SQL backends.
        active = LibraryLoan.query.filter_by(institute_id=tenant, copy_id=copy_id, returned_at=None).first()
        if active:
            return jsonify(error="Copy is already issued"), 409
        now = datetime.now(timezone.utc)
        loan = LibraryLoan(institute_id=tenant, copy_id=copy_id, borrower_type=kind,
                           borrower_id=borrower_id, issued_at=now,
                           due_at=now + timedelta(days=days), status="Issued")
        db.session.add(loan)
        try:
            db.session.commit()
        except Exception as exc:
            db.session.rollback()
            from sqlalchemy.exc import IntegrityError
            if isinstance(exc, IntegrityError):
                return jsonify(error="Copy is already issued"), 409
            raise
        return jsonify(id=loan.id, status="Issued", due_at=loan.due_at.isoformat()), 201

    @bp.post("/renew/<int:loan_id>")
    def renew_book(loan_id):
        tenant = guard("library.issue_return")
        loan = LibraryLoan.query.filter_by(id=loan_id, institute_id=tenant).first_or_404()
        if loan.returned_at is not None:
            return jsonify(error="Returned loans cannot be renewed"), 409
        data = request.get_json(silent=True) or {}
        try:
            days = int(data.get("days", 7))
        except (TypeError, ValueError):
            return jsonify(error="Invalid renewal days"), 400
        if not 1 <= days <= 30:
            return jsonify(error="Renewal must be 1–30 days"), 400
        now = datetime.now(timezone.utc)
        due = loan.due_at
        if due.tzinfo is None:
            due = due.replace(tzinfo=timezone.utc)
        loan.due_at = max(now, due) + timedelta(days=days)
        db.session.commit()
        return jsonify(id=loan.id, status=loan.status, due_at=loan.due_at.isoformat())

    @bp.get("/reports/overdue")
    def overdue_report():
        tenant = guard("library.view")
        now = datetime.now(timezone.utc)
        rows = LibraryLoan.query.filter(
            LibraryLoan.institute_id == tenant,
            LibraryLoan.returned_at.is_(None),
            LibraryLoan.due_at < now
        ).order_by(LibraryLoan.due_at.asc()).limit(200).all()
        return jsonify(items=[dict(id=x.id, copy_id=x.copy_id,
                                   borrower_type=x.borrower_type,
                                   borrower_id=x.borrower_id,
                                   due_at=x.due_at.isoformat()) for x in rows])

    @bp.get("/copies")
    def list_copies():
        tenant = guard("library.view")
        rows = LibraryCopy.query.filter_by(institute_id=tenant).order_by(LibraryCopy.id.desc()).limit(100).all()
        return jsonify([dict(id=x.id, book_id=x.book_id, accession=x.accession, condition=x.condition) for x in rows])

    app.register_blueprint(bp)
    return {"Book": LibraryBook, "Copy": LibraryCopy, "Loan": LibraryLoan, "Settings": LibrarySettings}
