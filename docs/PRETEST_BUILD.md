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

Generation deliberately refuses sandwich-leave rules, nonzero jump-step/max-limit, annual increments, prorated salary and nonzero all-present bonus eligibility until verified calendar/formula examples are available. Monthly approved advance return amounts are reserved across generated salary records so repeated months cannot exceed the advance principal. The pre-test advance record does not create an accounting-ledger cash disbursement.

## Outstanding work

- Yearly fee-increment configuration/application, nonzero percentage increments, fee-plan deletion, full reusable schedule configuration, original advanced fee generation, advance credit balances, complete print settings, fine calculation, exact report layouts/filters, certificates, exact Student 360 reference layout and verified official result weightings.
- Subject-wise student filtering, multi-select section/group/session award filtering, sorting/recheck behavior, return-date permission enforcement, parent-app publishing and complete teacher-performance comparison reports.
- Shift policy enforcement; posting increments/security balances; leave approval to attendance; consecutive lecture editor/carry-forward; complete salary reporting/accounting and verified payroll formulas.
- All 37 dashboard widgets and customization. Current dashboard shows selected database-backed aggregates/charts and links.
- Institute login, tenant isolation, role-scoped app accounts, forgotten-password recovery and all four connected apps. The optional owner-summary endpoint fails closed unless `SCHOOLFLOW_API_TOKEN` is configured; it is not a completed mobile-app backend.
- Durable deployment database, migrations, backups and secure file authorization. Current free service uses ephemeral SQLite. Never put real student, employee or financial data in this public pre-test environment.

## Validation

`python -m unittest discover -s tests -v`

48 integration tests cover complete record persistence, attachments and password redaction, family linking, validation rollback, CSV safety, menu rendering, fee duplicate/overpayment/reversal/atomicity, installment conservation, attendance upserts, marks bounds and A/L, payroll duplicate prevention/snapshots/pay/unpay, unverified-rule refusal, lecture import idempotency, CSRF disabled message delivery, bill-month versus receipt-date reporting, no-challan students, mixed-bill allocation limits, consecutive absence dates and teacher-performance averages, student plan create/update/view, server-controlled actual fees, discount bounds, stale edit protection, effective-month snapshots, once-only arrears, assigned monthly duplicate prevention and atomic batch rollback.

The tests use an isolated in-memory database and fictional data. A passing suite does not verify missing workflows or production suitability.

Student plan percentage increments are deliberately rejected unless 0: the yearly screen has been captured but no per-year amount/percentage rule has been verified. Discount reason is currently free text; a configured reference dropdown is pending. Initial Actual Fee values come from explicitly configured schedules, not from real reference pupils.

UI verification: Flask renders all new forms in integration tests. Local browser viewport checks could not run because Chromium is absent in this runtime; live browser verification is recorded separately after deployment.

## Student 360 performance update

The user's clarification makes academic performance the central Student 360 feature: Weekly, Monthly, First Term and Second Term have separate totals, date-period breakdowns and subject summaries. Weekly periods use ISO weeks; monthly periods use calendar months; terms group by saved academic session, with paper year as fallback. New award lists can select the assessment category; existing lists can be classified from the marks page without changing marks. Existing unclassified results are shown explicitly and are never inferred from names or paper types. Numeric totals use summed obtained / maximum marks; A/L and unmarked papers are counted separately. No official weighting between assessment categories is invented.

The same read-only view links profile, current and scheduled fee plans, challans, receipts, attendance, siblings, attachments and record history. Billing months and payment dates are separate filters; current outstanding balances are labelled as current balances, not historical as-of balances. Legacy starter attendance/results remain separate. The directory searches/paginates saved students and includes inactive pupils.

Eight additional integration tests verify four-category separation, weighted-by-marks arithmetic, absence/leave/unmarked handling, unclassified/other-student isolation, date ranges, receipt dates/voiding, family links, student/staff attendance separation, read-only directory behavior and category changes without marks loss.
