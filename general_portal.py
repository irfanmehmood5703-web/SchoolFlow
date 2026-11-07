"""General workspace page. Owner-only until granular staff permissions are available."""
from flask import Blueprint, abort, g, render_template, session
import secrets

def configure_general_portal(app):
    bp = Blueprint("general_portal", __name__, url_prefix="/workspace/general")
    @bp.get("/")
    def index():
        identity = getattr(g, "school_identity", None) or {}
        if not identity.get("scope") or identity.get("demo") or getattr(g, "staff_principal", None) is not None:
            abort(403)
        if not session.get("record_csrf"):
            session["record_csrf"] = secrets.token_urlsafe(32)
        return render_template("general_portal.html", school=identity.get("name", "SchoolFlow"),
                               csrf=session["record_csrf"])
    app.register_blueprint(bp)
