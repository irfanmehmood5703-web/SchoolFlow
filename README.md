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

Open the public landing page and choose **Explore the test demo**, then click **Set up test dropdowns** on the dashboard. Create fictional student/staff records only. School choices are editable under School Settings. Provisioned institutes use a separate owner login and isolated SQLite workspace database; the public demo never selects an institute database. See [Institute login and isolation](docs/IDENTITY.md).

## Tests

```sh
python -m unittest discover -s tests -v
```

Tests use an isolated in-memory database. Deployment uses `DATABASE_URL` if configured, otherwise SQLite. Existing starter tables are retained; old attendance/exam rows are readable at `/workspace/legacy-data`. `GET /healthz` reports database readiness.

The existing Render service uses free ephemeral SQLite storage; restarts/redeploys can reset test data. A durable database and authentication are required before real use. All communication requests are logged without delivery. Four mobile apps are not connected.


### Campus cards and certificates

Admissions → Student Card and Certificates → choose campus → Set up certificate templates. Use School heading, logo & colours for your own school details, then choose a document and students. Preview has no issuance side effects. Edit saves campus-specific Header/Body/Footer content. Generate & Print assigns references and saves immutable documents in Certificate Logs. Print / Save PDF opens the browser print flow. Student QR Code supports active-pupil filters, selected columns, CSV/Excel and printable QR sheets. Use fictional data only on the public pre-test service.
