# SchoolFlow

Original green/white Flask school-management **pre-test** build. Top menus follow the supplied Admissions, Exam & Attendance and HRM reference sequence. Includes full student/employee record forms and initial fee, attendance, exam and payroll workflows.

**Not a completed reference-equivalent or production-ready release. Use fictional test records only.** Read [the build report](docs/PRETEST_BUILD.md) and the in-app Build Status page for incomplete workflows.

## Run

```sh
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
export SECRET_KEY='replace-with-a-long-random-value'
python app.py
```

Open the dashboard and click **Set up test dropdowns**, then create fictional student/staff records. School choices are editable under School Settings. This build has no institution login or tenant isolation.

## Tests

```sh
python -m unittest discover -s tests -v
```

Tests use an isolated in-memory database. Deployment uses `DATABASE_URL` if configured, otherwise SQLite. Existing starter tables are retained; old attendance/exam rows are readable at `/workspace/legacy-data`. `GET /healthz` reports database readiness.

The existing Render service uses free ephemeral SQLite storage; restarts/redeploys can reset test data. A durable database and authentication are required before real use. All communication requests are logged without delivery. Four mobile apps are not connected.
