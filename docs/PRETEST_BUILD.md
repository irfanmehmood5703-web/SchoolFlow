# SchoolFlow pre-test build — 30 October 2026

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

Sandwich leave is disabled at the school’s request, including old plan flags. Generation refuses nonzero jump-step/max-limit, annual salary increments, prorated salary and nonzero all-present bonus eligibility until verified calendar/formula examples are available. Monthly approved advance return amounts are reserved across generated salary records so repeated months cannot exceed the advance principal. The pre-test advance record does not create an accounting-ledger cash disbursement.

## Outstanding work

- Class-wise yearly fee-increment setup, fee-plan deletion, full reusable schedule configuration, original advanced fee generation, advance credit balances, complete print settings, fine calculation, exact report layouts/filters, four remaining reference certificate designs, exact Student 360 reference layout and verified official result weightings.
- Subject-wise student filtering, multi-select section/group/session award filtering, sorting/recheck behavior, return-date permission enforcement, parent-app publishing and complete teacher-performance comparison reports.
- Shift policy enforcement; posting increments/security balances; leave approval to attendance; consecutive lecture editor/carry-forward; full reference salary-report formatting/accounting and verified payroll formulas.
- All 37 dashboard widgets and customization. Current dashboard shows selected database-backed aggregates/charts and links.
- Institute login, tenant isolation, role-scoped app accounts, forgotten-password recovery and all four connected apps. The optional owner-summary endpoint fails closed unless `SCHOOLFLOW_API_TOKEN` is configured; it is not a completed mobile-app backend.
- Durable deployment database, migrations, backups and secure file authorization. Current free service uses ephemeral SQLite. Never put real student, employee or financial data in this public pre-test environment.

## Validation

`python -m unittest discover -s tests -v`

73 integration tests cover complete record persistence, attachments and password redaction, family linking, validation rollback, CSV safety, menu rendering, fee duplicate/overpayment/reversal/atomicity, installment conservation, attendance upserts, marks bounds and A/L, payroll duplicate prevention/snapshots/pay/unpay, unverified-rule refusal, lecture import idempotency, CSRF disabled message delivery, bill-month versus receipt-date reporting, no-challan students, mixed-bill allocation limits, consecutive absence dates and teacher-performance averages, student plan create/update/view, server-controlled actual fees, discount bounds, stale edit protection, effective-month snapshots, once-only arrears, assigned monthly duplicate prevention and atomic batch rollback.

The tests use an isolated in-memory database and fictional data. A passing suite does not verify missing workflows or production suitability.

The school confirmed percentage increments apply to the fee AFTER discount, excluding arrears. Student plans now implement that rule, with half-up paisa rounding. Re-saving the same effective month does not compound; a later effective month starts from the previous result. For example 3,500 minus 1,500 discount gives 2,000; 10% adds 200, so net becomes 2,200. The displayed Actual Fee includes that 200 increment while the source fee and increment basis are retained. Discount reason is currently free text; a configured reference dropdown and class-wise yearly grid are pending. Initial actual amounts come from explicitly configured schedules, not real reference pupils.

UI verification: Flask renders all new forms in integration tests. Local browser viewport checks could not run because Chromium is absent in this runtime; live browser verification is recorded separately after deployment.

## Student 360 performance update

The user's clarification makes academic performance the central Student 360 feature: Weekly, Monthly, First Term and Second Term have separate totals, date-period breakdowns and subject summaries. Weekly periods use ISO weeks; monthly periods use calendar months; terms group by saved academic session, with paper year as fallback. New award lists can select the assessment category; existing lists can be classified from the marks page without changing marks. Existing unclassified results are shown explicitly and are never inferred from names or paper types. Numeric totals use summed obtained / maximum marks; A/L and unmarked papers are counted separately. No official weighting between assessment categories is invented.

The same read-only view links profile, current and scheduled fee plans, challans, receipts, attendance, siblings, attachments and record history. Billing months and payment dates are separate filters; current outstanding balances are labelled as current balances, not historical as-of balances. Legacy starter attendance/results remain separate. The directory searches/paginates saved students and includes inactive pupils.

Eight additional integration tests verify four-category separation, weighted-by-marks arithmetic, absence/leave/unmarked handling, unclassified/other-student isolation, date ranges, receipt dates/voiding, family links, student/staff attendance separation, read-only directory behavior and category changes without marks loss.

## HRM salary reports and eligibility

Employee Salary Report now groups saved salary months by employee and totals earnings, deductions, net, paid and remaining amounts. Lecture-wise Salary Report shows saved per-month lecture count/amount, net, paid and payment status. Both support From/To month, campus, employee, payment-status filters, CSV and printable detail pages. Reports read salary snapshots, never current rate/plan recalculations. Older salary records without a lecture-detail snapshot display "Not captured" rather than reconstructing a potentially edited source register.

New payroll requires every selected employee to have an approved plan and a saved joining date. Generation refuses a month before joining. A joining date after the first day of the month requires a confirmed proration rule for basic/full-plan earnings; pure lecture pay can use approved post-joining lectures only. New salaries capture joining date and per-entry lecture date/class/section/subject/count/amount. Existing salary records are not rewritten.

Six new tests cover missing/future/midmonth joining dates, batch plan eligibility rollback, lecture joining-date bounds, immutable lecture details, employee aggregates/status/campus filters, CSV safety, legacy snapshot limits and invalid report filters. Existing payroll test employees now have explicit fictional joining dates.

## Cards, certificates and QR update

The campus-specific module is now available under Admissions → Student Card and Certificates. Configure a campus, initialise its 15 templates, then set the school heading/logo/colours. Choose a document and students, preview without issuing, edit Header/Body/Footer, and generate selected documents for printing/PDF. Previous/Next preview works over the selected students; without selection a template preview uses the first matching student.

The editor supports rich text, tables, source editing and the supplied student/institute/fee/reference tags. Source previews are sanitised by the server without saving; stale template versions are rejected. Templates and headings are separate per campus. Cross-campus print selections are rejected. Template HTML cannot add scripts, frames, event handlers or external image fetches; personalised text is escaped.

Generation assigns references and saves an immutable rendered snapshot, including embedded photo/logo/QR bytes. Repeat submissions with the same token reuse the batch. Certificate Logs provide saved references, student details, Karachi timestamps and reprints. Logs record generation for printing, not physical printer completion. Fee clearance generation is blocked while any selected student has outstanding challans. Preview never changes enrolment status, issues documents or reserves numbers.

Student QR Code lists active pupils with campus/class/section/gender filters, photos and generated SVG QR codes. Column selection applies to CSV, Excel and selected QR printing/PDF. Payloads contain an opaque HMAC identifier, not names/contacts. Scanning through the Teacher/Parent/Owner apps remains outside this pre-test build. QR views do not create certificate issues.

All 15 document types are functional original editable defaults. Eleven designs have supplied preview/editor references. The older Student Card, Character Certificate, Campus Migration Slip and Rustication Notice still use clearly labelled starter designs because their specific screenshots were not in the 30-image batch. Exact source CSS and text are not claimed to have been recovered from screenshots. See CERTIFICATE_REFERENCE.md.

Paper Total Marks now starts blank, including newly added subject rows; the server requires an explicit positive maximum for each paper. 20/30/50-mark papers are tested independently. Sandwich leave is absent from the salary-plan controls and is never applied, including legacy enabled flags. Other unverified payroll automation remains pending.
