# SchoolFlow — Phase 1 Test Build

Functional starter build for testing four connected modules:

- Admissions: new student admission + student records
- Attendance: student attendance with Present/Absent/Leave/Late
- Exams: exam/subject marks and percentage
- HRM: employee master records, designation, contact and basic salary

## Local run

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\\Scripts\\activate
pip install -r requirements.txt
python app.py
```

Open `http://127.0.0.1:5000`.

## Free test deployment

The repository includes `render.yaml` and a `Procfile` for a simple Python web deployment. SQLite is used by default for this test build. For production/multi-tenant use, configure PostgreSQL with `DATABASE_URL` and add authentication, institute isolation, permissions, migrations, backups and security hardening.

## Important

This is a functional Phase 1 test build, not yet a production-complete school SaaS. It intentionally establishes the working database/UI foundation before the full multi-tenant and role-based architecture is added.
