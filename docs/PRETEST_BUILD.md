# SchoolFlow pre-test build — 31 October 2026

This is an initial functional pre-test build. It is **not** the complete reference-equivalent release requested by the user. Menu presence does not imply that every referenced workflow is implemented. The application includes an explicit Build Status page.

## Source and layout

- Admissions: 21 reference menu entries; Exam & Attendance: 15; HRM: 22. The order and section headings follow the supplied reference menus.
- Horizontal top navigation, responsive original green/white SchoolFlow UI. Student/employee record sections are navigable from a horizontal section bar.
- The original Student, Employee, Attendance and ExamResult tables are preserved; new workflows use additional tables. Legacy attendance/results remain available at `/workspace/legacy-data` and are not included in the new reports.
- Student/employee fields, family linking, attachments, password hashing, validation and CSV export from the earlier development branch are retained.

## Functional test flows

1. Dashboard → Set up test dropdowns. This creates **fictional configurable choices only**, not real student/staff data. Then add a fictional student and employee using their complete reference forms.
2. Admissions → Manage Fee Plans separates active pupils with and without an assigned plan. Configure fee schedules (one row per particular with the same schedule name/campus/class), then Create / Update a student plan with effective month, year, discount reason, notes, first-time arrears and per-particular discounts. Actual fees are server-sourced snapshots; zero rows remain visible. View includes photo, totals and parent/principal signatures. Generate assigned challans explicitly selects particulars, month and due date, using the dated student plan and its net amounts. First-time arrears are optional and protected by a database unique claim per student/particular. Repeating generation skips the existing student/month; an existing other challan requires review. Earlier challans are unchanged. The legacy generator cannot bypass assigned discounts.
3. Fee Payments → Pay this month / Pay all dues. Payment and discount amounts may not exceed outstanding debt. Duplicate form tokens are rejected. Saved receipts appear in Paid/Discount Challans; reversing them restores the debt and retains the receipt audit record.
4. Direct/family payment loads unpaid bills by SID/roll/challan/family number and saves allocations. Advance balances and multi-row identifier entry are not yet implemented.
5. Installments move selected amounts from an untouched challan to a new month/due date, preserving total debt. Already paid/discounted/frozen bills cannot be split in this build.
6. Student/family history shows totals and per-challan receipts, discounts, particulars and pending amounts. Three basic challan print layouts exist: Horizontal, Vertical, Family. Advanced print settings, school banking/branding configuration and payment QR are pending.
7. Student and staff attendance save one row per person/date; repeated saves update the row. Staff attendance includes time in/out and lecture counts. Combined, day-wise, individual, class summary, absentee/consecutive-day and printable attendance-sheet reports now calculate their own data and export CSV.
8. Date sheets and award lists accept multiple subject rows. Marks enforce totals and A/L states. Exam roll numbers and hall assignments persist; slips print.
9. Employee → Save & Create Salary Plan opens an actual plan editor. Save → Pending → Approve → generate for a completed previous month. Unique employee/month salaries prevent duplicate generation; saved salaries contain plan snapshots. Pay/unpay, guarded unpaid deletion, slip/signature/report/bank views are available.
10. Lecture rates use effective month and most-specific class/section/subject matches. Approved lectures only contribute to lecture-wise payroll. Attendance import skips existing teacher/day entries and creates pending records. Paid lecture entries cannot be changed through approval actions.
11. Auxiliary query, shift, assignment, increment, advance, security, notice and leave forms store reviewable records. Some downstream effects listed below are incomplete.
12. Communication preferences and requests are saved as **Provider not configured**. No external SMS, WhatsApp or app notification is sent.

## Calculation boundaries

Money uses integer paisa. Absolute attendance deductions apply to events over the allowed count; percentage deductions in this pre-test build use basic salary / number of calendar days. Recursive means every excess event, Once means at most one event. These are transparent test calculation choices, not claims of verified EDUBase equivalence.

Sandwich leave is disabled at the school’s request, including old plan flags. Generation refuses nonzero jump-step/max-limit, automatic annual increments and nonzero all-present bonus eligibility until those rules are confirmed. Joining-month basic pay now uses the explicitly configured school working calendar; approved manual salary increments are supported as an optional employee-plan setting. Monthly approved advance return amounts are reserved across generated salary records so repeated months cannot exceed the advance principal. The pre-test advance record does not create an accounting-ledger cash disbursement.

## Outstanding work

- Class-wise yearly fee-increment setup, fee-plan deletion, full reusable schedule configuration, original advanced fee generation, advance credit balances, complete print settings, fine calculation, exact report layouts/filters, four remaining reference certificate designs, exact Student 360 reference layout and verified official result weightings.
- Subject-wise student filtering, multi-select section/group/session award filtering, sorting/recheck behavior, return-date permission enforcement, parent-app publishing and complete teacher-performance comparison reports.
- Shift policy enforcement; automatic annual increment/security-balance posting; leave approval to attendance; consecutive lecture editor/carry-forward; full reference salary-report formatting/accounting and verified payroll formulas.
- All 37 reference dashboard widgets. The 14 implemented live-data widgets now support selection, ordering, Expand, Simple Dashboard, advanced appearance settings and personal saved defaults.
- Teacher/Parent/Owner-app role-scoped API accounts, email password recovery and all four connected apps. Institute Code and web-owner login with separate institute SQLite databases are implemented for testing. The optional owner-summary endpoint fails closed unless `SCHOOLFLOW_API_TOKEN` is configured; it is not a completed mobile-app backend.
- Durable deployment database, migrations, backups and role-scoped file permissions. Current free service uses ephemeral SQLite. Never put real student, employee or financial data in this public pre-test environment.

## Validation

`python -m unittest discover -s tests -v`

118 integration tests cover complete record persistence, attachments and password redaction, family linking, validation rollback, CSV safety, menu rendering, fee duplicate/overpayment/reversal/atomicity, installment conservation, attendance upserts, marks bounds and A/L, payroll duplicate prevention/snapshots/pay/unpay, unverified-rule refusal, lecture import idempotency, CSRF disabled message delivery, bill-month versus receipt-date reporting, no-challan students, mixed-bill allocation limits, consecutive absence dates and teacher-performance averages, student plan create/update/view, server-controlled actual fees, discount bounds, stale edit protection, effective-month snapshots, once-only arrears, assigned monthly duplicate prevention and atomic batch rollback.

The tests use an isolated in-memory database and fictional data. A passing suite does not verify missing workflows or production suitability.

The school confirmed percentage increments apply to the fee AFTER discount, excluding arrears. Student plans now implement that rule, with half-up paisa rounding. Re-saving the same effective month does not compound; a later effective month starts from the previous result. For example 3,500 minus 1,500 discount gives 2,000; 10% adds 200, so net becomes 2,200. The displayed Actual Fee includes that 200 increment while the source fee and increment basis are retained. Discount reason is currently free text; a configured reference dropdown and class-wise yearly grid are pending. Initial actual amounts come from explicitly configured schedules, not real reference pupils.

UI verification: Flask renders all new forms in integration tests. Local browser viewport checks could not run because Chromium is absent in this runtime; live browser verification is recorded separately after deployment.

## Student 360 performance update

The user's clarification makes academic performance the central Student 360 feature: Weekly, Monthly, First Term and Second Term have separate totals, date-period breakdowns and subject summaries. Weekly periods use ISO weeks; monthly periods use calendar months; terms group by saved academic session, with paper year as fallback. New award lists can select the assessment category; existing lists can be classified from the marks page without changing marks. Existing unclassified results are shown explicitly and are never inferred from names or paper types. Numeric totals use summed obtained / maximum marks; A/L and unmarked papers are counted separately. No official weighting between assessment categories is invented.

The same read-only view links profile, current and scheduled fee plans, challans, receipts, attendance, siblings, attachments and record history. Billing months and payment dates are separate filters; current outstanding balances are labelled as current balances, not historical as-of balances. Legacy starter attendance/results remain separate. The directory searches/paginates saved students and includes inactive pupils.

Eight additional integration tests verify four-category separation, weighted-by-marks arithmetic, absence/leave/unmarked handling, unclassified/other-student isolation, date ranges, receipt dates/voiding, family links, student/staff attendance separation, read-only directory behavior and category changes without marks loss.

## HRM salary reports and eligibility

Employee Salary Report now groups saved salary months by employee and totals earnings, deductions, net, paid and remaining amounts. Lecture-wise Salary Report shows saved per-month lecture count/amount, net, paid and payment status. Both support From/To month, campus, employee, payment-status filters, CSV and printable detail pages. Reports read salary snapshots, never current rate/plan recalculations. Older salary records without a lecture-detail snapshot display "Not captured" rather than reconstructing a potentially edited source register.

New payroll requires every selected employee to have an approved plan and a saved joining date. Generation refuses a month before joining. A joining date after the first day of the month requires a saved working calendar for basic/full-plan earnings; pure lecture pay uses approved post-joining lectures only. New salaries capture joining date and per-entry lecture date/class/section/subject/count/amount. Existing salary records are not rewritten.

Six new tests cover missing/future/midmonth joining dates, batch plan eligibility rollback, lecture joining-date bounds, immutable lecture details, employee aggregates/status/campus filters, CSV safety, legacy snapshot limits and invalid report filters. Existing payroll test employees now have explicit fictional joining dates.

## Cards, certificates and QR update

The campus-specific module is now available under Admissions → Student Card and Certificates. Configure a campus, initialise its 15 templates, then set the school heading/logo/colours. Choose a document and students, preview without issuing, edit Header/Body/Footer, and generate selected documents for printing/PDF. Previous/Next preview works over the selected students; without selection a template preview uses the first matching student.

The editor supports rich text, tables, source editing and the supplied student/institute/fee/reference tags. Source previews are sanitised by the server without saving; stale template versions are rejected. Templates and headings are separate per campus. Cross-campus print selections are rejected. Template HTML cannot add scripts, frames, event handlers or external image fetches; personalised text is escaped.

Generation assigns references and saves an immutable rendered snapshot, including embedded photo/logo/QR bytes. Repeat submissions with the same token reuse the batch. Certificate Logs provide saved references, student details, Karachi timestamps and reprints. Logs record generation for printing, not physical printer completion. Fee clearance generation is blocked while any selected student has outstanding challans. Preview never changes enrolment status, issues documents or reserves numbers.

Student QR Code lists active pupils with campus/class/section/gender filters, photos and generated SVG QR codes. Column selection applies to CSV, Excel and selected QR printing/PDF. Payloads contain an opaque HMAC identifier, not names/contacts. Scanning through the Teacher/Parent/Owner apps remains outside this pre-test build. QR views do not create certificate issues.

All 15 document types are functional original editable defaults. Eleven designs have supplied preview/editor references. The older Student Card, Character Certificate, Campus Migration Slip and Rustication Notice still use clearly labelled starter designs because their specific screenshots were not in the 30-image batch. Exact source CSS and text are not claimed to have been recovered from screenshots. See CERTIFICATE_REFERENCE.md.

Paper Total Marks now starts blank, including newly added subject rows; the server requires an explicit positive maximum for each paper. 20/30/50-mark papers are tested independently. Sandwich leave is absent from the salary-plan controls and is never applied, including legacy enabled flags. Other unverified payroll automation remains pending.

Leaving Date is now an optional field in the student Office Information section and is available to certificate tags. It cannot precede Admission Date and does not automatically change enrolment status. Preview links to the student editor for missing birth/admission/leaving dates and class-of-admission details.


## Institute sign-in and isolation — 31 October

The root now serves an original green/white landing page, followed by Institute Code and a school-specific owner email/password form. All workspace, record, file and API routes require a valid owner session or an explicit public-demo session. Unknown institute codes do not provision databases. No shared admin password or public registration exists. Forgotten password clearly directs users to administrator recovery until email delivery is configured. Operator CLI commands provision owners and reset passwords; owner password revisions and account/school deactivation revoke existing sessions.

The control database holds hashed owners and institute registrations. Each institute gets a separate SQLite file under a random immutable storage identity. SQLAlchemy routes workspace models, relationships and Core queries to the selected institute engine for that request; identity models stay on the control engine. The ORM identity map is cleared before school selection. The original fictional database remains the demo. No records are automatically copied to a new institute. QR payloads include the institute storage scope.

Twelve identity tests additionally cover the public entry/gates, sign-in normalization and CSRF rotation, two schools with identical pupil IDs/admission numbers/file IDs, reads/edits/exports/settings/files/QR separation, write routing, demo manipulation, expired sessions, account revision and school deactivation, login throttling, operator-only provisioning and accurate password-help messaging. All 118 tests pass. This is a tested owner-login foundation, not completed role-based mobile-app authorization.

Current free deployment remains ephemeral. Real institute accounts have not been provisioned on the public test service. Persistent control AND institute storage, migration/backup operations and full role permissions remain necessary before real school data. See IDENTITY.md for operator commands and limits.


## Personal dashboard controls

Widgets and Simple Dashboard are functional modes. Customise / Add Widgets opens a selector for the 14 implemented data-backed widgets, with up/down ordering, optional quick summaries, one/two/three desktop columns and compact spacing. Apply changes affects the current session; Make this my default dashboard persists the chosen layout/mode to the institute workspace under the signed-in owner ID. Restore reloads that saved default. Stale default saves are rejected with optimistic versions. A GET never creates a preference row. Anonymous demo defaults are session-only, so visitors cannot overwrite each other's layouts or create shared preference records.

Expand increases a widget to full grid width, with expanded chart space, and saves the expand state in browser storage scoped by institute storage identity and owner. If browser storage is unavailable, expansion still works. How calculated explains the source; Open report links to real module pages. Today's attendance report is restricted to today; staff month-to-date excludes future entries. Pending Approvals now opens a read-only listing of all Pending workflows with links to the relevant approval workspace rather than only salary plans.

Nine dashboard tests cover read-only GET, selection/order/appearance, Apply versus Restore, owner persistence and owner isolation, demo session isolation, stale updates, empty/simple mode behavior, CSRF/invalid inputs, saved-record counts/report pages, Pending report consistency and future attendance exclusion. 118 tests pass in total. Additional reference widget data sources (including finance expenses, historical inactive transitions, external app/SMS statistics and complaints) are still outstanding; their values are not fabricated. Existing institute databases need `flask --app app institute-upgrade` for the new preference table. No real institutes have yet been provisioned on the public test service.


## Confirmed SaaS provisioning and payroll rules

SchoolFlow is the product brand. Each client institute is provisioned with that client school’s name and an independent code/database. The vendor can now generate a unique email-style login and a random 32-character password with `institute-create-generated`. A private handover file is created exclusively outside the application checkout with mode 0600; the password is not printed or stored in plaintext in the identity database. Generated .invalid email-style logins are identifiers, not real mailboxes. Creating an actual email inbox requires a mail provider. No real client account has been invented or provisioned on the public demo.

Joining-month basic = monthly basic (including eligible approved manual increments) × eligible working dates from joining through month end / all saved working dates in the salary month, rounded half-up to paisa. There is no assumed Sunday/Saturday or fixed 30-day divisor. HRM salary plans and payroll link to a monthly Working Calendar with weekday-selection shortcuts and individual date checkboxes for holidays. A calendar is required for joining-month monthly-basic pay and percentage-of-daily-basic deductions. Full monthly basic does not require a calendar when no daily percentage calculation is requested. Attendance deductions exclude pre-joining dates and, when a calendar is saved, nonworking dates. Actual approved lecture pay and fixed security return/deduction entries remain separate from basic proration.

Manual increments are entered per employee as an arbitrary positive amount and effective month, then explicitly approved. The salary plan has an optional Apply approved manual salary increments checkbox, off by default. When enabled, approved amounts effective on/before the payroll month are added to the plan’s pre-increment basic. They carry forward without compounding or annual repetition. Pending, rejected, future and other-employee records do not apply. Basic Salary must exclude those ledger increments to avoid entering the same increase twice. Lecture-only staff use their editable lecture rates instead. Legacy nonzero automatic annual-increment fields remain guarded until the plan is reviewed/resaved.

Repeated increment form submissions reuse a database-backed request token. Replaying changed data is rejected; concurrent duplicate tokens roll back. An increment already captured by a salary cannot be cancelled through the generic approval actions. Saved salaries capture the increment IDs/amounts/effective months, full monthly basic, payable basic, calendar version/dates and eligible/total working days. Calendar/plan/increment edits do not rewrite generated salaries; slips and salary detail show the saved calculation.

Eleven additional tests cover calendar validation/CSRF/versioning, working-day formulas with weekends/holidays/zero eligible days/rounding, mandatory calendars, attendance-date exclusions, opt-in/effective/approved/employee-specific increments, no compounding, repeated form and payroll idempotency, used-source protection, approval flow, plan-option persistence, batch rollback and private generated account credentials. Total: 118 passing tests. Existing institute databases require `flask --app app institute-upgrade` for the new calendar and increment-request tables. Permanent storage, actual mail delivery, role-based connected apps and remaining reference workflows are still outstanding.


## Class seats and admission approvals

Admissions → Admission Approvals now has Waiting, Allowed, Refused and All tabs, search, campus/class/session filters, pagination and selected Allow/Refuse actions. Allowed reflects current Active enrolment, not an invented historical decision. Refused is a distinct new student status; legacy Inactive rows are not inferred to be refused admissions. Other statuses remain visible in All. Student detail data and record history are updated with reviews. Review audits include selected IDs, outcome and the web owner ID when present.

Change the seats for a class opens a per-campus/current-class/academic-session limit across all sections. An unconfigured cohort remains unlimited; an explicit No seat limit is available. Zero seats queues new admissions. Limits cannot be reduced below already active occupancy. Raising/removing a limit never automatically approves the waiting list. Only Active students with matching office scope occupy seats.

New Active admission saves switch to Waiting when the configured cohort is full; manual Waiting/Inactive/other statuses remain as entered. Re-activations also observe limits. Editing an enrolled pupil within their existing cohort does not queue them. A transfer of an enrolled pupil into a full cohort is rejected atomically, preserving their existing class, status and profile. Every HTTP student save and admission review shares a database write gate with capacity changes. Gate upserts acquire a SQLite write lock / PostgreSQL row lock before seat counts, protecting simultaneous admission requests; institute databases remain separate through existing routing.

Selected approvals are all-or-nothing across cohorts: all IDs must still be Waiting and match the submitted filters, and every class needs enough seats. Unknown actions, stale/nonwaiting records, insufficient seats and invalid scopes fail without partial approvals. The dashboard now includes an Admission Capacity widget, taking its live occupancy from the same limits. This makes 14 implemented dashboard widgets; the complete 37-reference-widget set is still not claimed. Existing saved custom layouts can add the new tile through Add Widgets.

Twelve additional integration tests cover read-only GETs, unlimited/zero/full seats, section sharing and independent campus/class/session scopes, atomic approvals, refusal/profile history, stale IDs and filters, CSRF/version/occupied-minimum checks, same-class editing, refused/inactive activation, transfer rollback, withdrawing to free a seat, dashboard counts and two concurrent SQLite connections competing for the last seat. Total: 118 tests. Existing institute databases require `flask --app app institute-upgrade` for the new capacity and write-gate tables.

The record-list non-enrolled summary now links to an explicit non-active filter that includes Waiting, Refused, Inactive and other non-enrolled statuses, matching the displayed count. The exact Inactive filter remains available. CSV uses the same filter. A regression test covers this distinction.
