# SchoolFlow acceptance audit — 14 November 2026

## Scope and findings

The audit covers the existing five menu groups (82 menu entries), Dashboard, Configuration and the workspace utilities. All 106 private-owner How To destinations resolve to actual handlers. A two-level traversal of menu and inner-page links initially visited 313 URLs, with no unexpected 404/server error or placeholder menu handler. Owner-only Geo attendance correctly requires an employee login. Disabled roll-number review links initially produced expected validation errors; the UI now stops offering those links until numbering is enabled.

735 backend tests passed at the starting revision. The repair adds eight integration cases for whole-menu traversal, required choice controls, invalid configured choices, primitive input preservation, roll-review availability, reminder days, storage guidance and private/demo boundaries. The same corpus exercises student/family/fee cycles, attendance/exams, payroll, ledger/requisitions, General/Parent/PTM, Messages/Support, staff scope isolation and Guide-only operation.

## Repairs

- Admission/joining dates, attendance/report defaults, Dashboard and the completed payroll month now use the Pakistan school date, including when the UTC host is still on the previous date/month. Audit timestamps remain UTC.
- Register choice lists are cached per request and campus scope, so 60 saved employee-linked rows do not reload the complete employee list 60 times. A subsequent request sees newly saved names/settings.
- Empty configured dropdowns remain selects with an explicit empty-catalog message; they no longer become free-text fields. Ordinary text/date/money fields remain inputs.
- Generic register writes reject unknown campus/class/section/subject choices; reminder schedules accept actual calendar days 1–31.
- Roll-number blank review is offered after automatic numbering is enabled; server review/CSRF/staleness safeguards remain intact.
- Workspace banner distinguishes temporary DEMO from a private school. System Check identifies both workspace and private-account storage, rather than describing the entire service as SQLite when only demo storage is SQLite.
- System Check gives an ordered school-data test handoff and accurately distinguishes web workflows, manual rules, phone/provider setup and physical Gate verification. Historical documentation has been superseded by the current README.
- Persistence QA now saves family/student, attachment, employee, bill/receipt, attendance, exam marks and payroll data. A new process verifies retention. A typed logical snapshot is restored into a newly provisioned disposable schema, all tenant table payloads/relationships/totals are compared, serial IDs are advanced, and a new admission is checked without changing the source school. The script requires the CI-only opt-in and exact `private_account_qa` database name and cannot be used as a production restore command.

## Actual hosting and APK observations

Read-only inspection of the connected `schoolflow_private_accounts` PostgreSQL database confirmed one private school schema, one school owner and one central software owner. No user records, credentials, database URLs or signing keys were changed by this inspection.

The four published Android test APKs were fetched independently and checked against the committed SHA-256 digests and source provenance, including actual AndroidManifest.xml/classes.dex ZIP members. That verifies published packages, not camera, SIM delivery, microphone, notifications or phone installation. The Gate trial APK remains pinned to a separate fictional trial host. The later School Test build targets the original host as described below.

## Option-by-option school-data test order

| Stage | Check before moving on |
| --- | --- |
| Private login and Institute Setup | Correct institute name/code, campuses, session, classes/sections/groups, fee heads and plan mappings; System Check shows private PostgreSQL workspace. |
| One student and family | Photo/documents, all dropdowns, existing-family/sibling links, save, sign out/in, same record retained. |
| Fees | Actual/discount/net values, challan month/due date, payment, remaining amount, receipt, reports, explicit correction/reversal; no duplicate payment. |
| Attendance and exams | Date and class scope, saved attendance, date sheet/hall/roll slip, marks bounds, result/grade and explicit Parent publication. |
| One employee and payroll | Joining date, working calendar, approved plan and optional manual increment, completed salary month, deductions, pay/unpay, slips and reports. |
| Finance | Own account mapping, balanced journal, closed-period guard, ledger/trial balance/P&L/cash; optional fee ledger mapping and reversal; requisition approval/payment/settlement. |
| General and access | Widgets, notices/diary/PTM, own-child Parent visibility, teacher assignments, Library/leave/feedback and limited staff denials. |
| Workspace tools | How To/Guide answer and links, private Messages/files, own Support ticket/human reply and notification read state. |
| Android/hardware | Actual phones, own school login, file/print behavior, attended school SIM with explicitly approved test recipient, separately configured Gate enrollment/recognition and history. |

Use one record/cycle per option first. Preserve real school data; do not seed demo dropdowns into a private institute, reset the database, automatically publish results or send messages to real recipients during the audit. Back up before bulk changes. A missing school-specific field or business rule discovered in acceptance testing must be corrected before broader use.

## Completion boundary

This is a pre-acceptance audit of the implemented web scope, not a claim that every EDUBase module, bank/provider connection, offline feature, production signing, unattended recognition or physical device test exists. Front Desk remains deferred. Recurring automatic annual salary increases and sandwich leave remain off per the user's requirements. A consecutive lecture preference does not implement a recurring timetable or future lecture generation; delivered lectures are entered/approved explicitly. Production backup/restore operations and school/device acceptance are separate from the disposable recovery check.

## Final native acceptance release

Main commit `bb9d0f4f1d9fa6d0cf06aa751139dded21da4ce5` passed the full 743-test backend corpus, PostgreSQL isolation/process-restart/logical recovery checks, 390px/1440px browser checks, four Android client compile/unit/lint checks, school-specific APK signing/callback/update checks, and Gate compile/unit/lint/emulator checks. Release runs: clients `43607765904`, Gate `43607765892`, web `43607765870`, school-specific builds `43607765862`.

Published `clients-test-6` and `gate-test-52` source files identify that exact commit. All six APKs were independently downloaded and matched published SHA-256 sums and sizes. Binary manifests confirm `.acceptance` client IDs, microphone permission in Parents/Teacher/Owner only, and separate `.schooltest`/`.trial` Gate IDs. All DEX files were inspected for the appropriate Gate host. App Links now selects the original-host Gate School Test APK. Completed voice previews survive native pause; active capture stops for explicit review. Physical hardware/phone acceptance remains outstanding.

The audit web deployment was checked on the original host with 13 hosted checks, including health build v38, demo/private storage guidance, actual configured selectors, inactive-roll guards, student/employee/fee/ledger/Support pages and provider-disabled free Guide mode. No original school data or credentials were changed.
