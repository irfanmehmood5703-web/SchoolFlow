# SchoolFlow

Original green/white school-management web software with horizontal menus, private institute login, campus permissions and separate school data. The current build is for controlled user acceptance testing; automated checks do not certify a production launch or physical Android/hardware behavior.

## Implemented scope

- Dashboard and 37 configurable widgets.
- Admissions: student/family records, reviewed imports, approvals, certificates, fee plans, discounts/increments, challans, payments/reversals and reports.
- Exam & Attendance: attendance/registers/reports, date sheets, halls/roll slips, marks, results and teacher performance.
- HRM: employees, shifts, leave, working calendars, salary plans, approved manual increments, lecture records, payroll and reports. Sandwich leave and recurring automatic annual increases stay disabled as requested.
- Finance: chart/accounts/periods, balanced journals and reversals, trial balance, profit/loss, cash/shareholders, requisitions, historical fee audits and daily snapshots. Fee-receipt ledger posting is optional and requires explicit account mappings; payroll-to-GL automatic posting is not connected.
- General: App Links, Widgets, family-scoped Parent portal, notices, PTM, subject diary, owner-only leave/feedback/Library workflows.
- How To, built-in free SchoolFlow Guide, private Messages, central human Support tickets and the in-app notification bell. No external AI model, key or AI billing is needed by the Guide.
- Institute/Exam/HRM configuration, staff grants and audit logs. Front Desk is deferred; Student 360° is excluded from the menu.

Teacher/Parent/Owner Android portal test packages and an attended school-SIM SMS package are published under App Links. They share the existing backend and authentication. Actual phone installation, SIM/network behavior and owner-controlled production signing require device acceptance checks. The separately published attended Gate trial APK uses the isolated fictional Gate trial host; it is not automatically an original-host production app.

## Private data versus demo

**Use a private Institute Code for school data. Never enter real pupil/staff data in public DEMO.** Public demo/default SQLite storage can reset on Render restart or deployment. With `IDENTITY_DATABASE_URL` on PostgreSQL, private accounts and their isolated school schemas remain in PostgreSQL independently of the demo filesystem. The original Render service uses that separate private-account configuration; do not overwrite its database URLs or existing signing/session keys.

The in-app **System Check** page shows the active workspace dialect, separate private-account dialect, current connections/limits and the order for testing one option at a time. Configure Institute Setup before adding school records. Test one student/family, fee cycle, attendance/result and employee/payroll cycle before a bulk import.

## Run locally

```sh
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
export SECRET_KEY='replace-with-a-long-random-value'
python app.py
```

Local defaults are development SQLite. Private-school login and central provisioning are documented in [IDENTITY.md](docs/IDENTITY.md) and [PRIVATE_ACCOUNT_PANEL.md](docs/PRIVATE_ACCOUNT_PANEL.md). No email mailbox or external notification is created by generating a login.

## Verification

```sh
python -W ignore -m unittest discover -s tests -q
```

Tests use disposable fictional schools and records. CI checks the complete backend suite, PostgreSQL identity/tenant behavior, menu/inner-form traversal, process restart persistence, typed logical recovery in an isolated QA schema, and mobile/desktop browser workflows. `scripts/verify_private_storage.py` refuses to run outside the exact disposable CI database; it is not a production backup command.

See [SYSTEM_ACCEPTANCE_AUDIT.md](docs/SYSTEM_ACCEPTANCE_AUDIT.md) for audit findings and the option-by-option handoff. Earlier milestone documents retain historical statements; this README and the latest audit take precedence for current implementation scope.

## External and operational checks

Saving a message request does not send it. School-SIM delivery requires explicit owner release and phone confirmation. WhatsApp/branded SMS requires its actual provider; native push, automatic bank collection, offline synchronization and always-awake timers are not implied. No real SMS, payment, salary transfer or journal is performed by an audit. Production backup retention/recovery, protected release signing, physical device/face-recognition accuracy and final school acceptance remain operational launch work.
