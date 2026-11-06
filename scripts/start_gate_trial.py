"""Start only the separate fictional Gate trial service, never the main app."""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import app, db, Student, Employee
from gate_trial import bootstrap

if __name__ == '__main__':
    with app.app_context():
        bootstrap(app, db, Student, Employee, os.environ)
    # Do not print credentials, identity QR values or environment variables.
    os.execvp('gunicorn', ['gunicorn', 'app:app', '--bind', '0.0.0.0:' + os.environ.get('PORT', '10000')])
