"""SchoolFlow General > Library foundation.

Opt-in registration only. Do not expose routes without a verified institute context
and a role/permission check supplied by the host application.
"""
from datetime import datetime, timezone
from flask import Blueprint, jsonify, request, abort
from sqlalchemy import UniqueConstraint

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

    bp = Blueprint("sf_library", __name__, url_prefix="/api/general/library")

    def guard(permission):
        tenant = resolve_institute()
        if not tenant:
            abort(401)
        require_permission(permission)
        return str(tenant)

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

    app.register_blueprint(bp)
    return {"Book": LibraryBook, "Copy": LibraryCopy, "Loan": LibraryLoan}
