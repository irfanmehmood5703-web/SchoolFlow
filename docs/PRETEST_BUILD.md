# SchoolFlow pre-test build — 30 October 2026

This is an initial functional pre-test build. It is **not** the complete reference-equivalent release requested by the user. Menu presence does not imply that every referenced workflow is implemented. The application includes an explicit Build Status page.

## Source and layout

- Admissions: 21 reference menu entries; Exam & Attendance: 15; HRM: 22. The order and section headings follow the supplied reference menus.
- Horizontal top navigation, responsive original green/white SchoolFlow UI. Student/employee record sections are navigable from a horizontal section bar.
- The original Student, Employee, Attendance and ExamResult tables are preserved; new workflows use additional tables. Legacy attendance/results remain available at `/workspace/legacy-data` and are not included in the new reports.
- Student/employee fields, family linking, attachments, password hashing, validation and CSV export from the earlier development branch are retained.

## Functional test flows

1. Dashboard → Set up test dropdowns. This creates **fictional configurable choices only**, not real student/staff data. Then add a fictional student and employee using their complete reference forms.
2. Admissions → Manage Fee Plans → create one monthly fee particular. Fee Challans → generate for selected pupils/month. Repeat generation skips duplicates for that plan/student/month.
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

- Full reference fee-plan particulars, original advanced fee generation, advance credit balances, complete print settings, fine calculation, exact report layouts/filters, certificates and Student 360.
- Subject-wise student filtering, multi-select section/group/session award filtering, sorting/recheck behavior, return-date permission enforcement, parent-app publishing and teacher-performance reports.
- Shift policy enforcement; posting increments/security balances; leave approval to attendance; consecutive lecture editor/carry-forward; complete salary reporting/accounting and verified payroll formulas.
- All 37 dashboard widgets and customization. Current dashboard shows selected database-backed aggregates/charts and links.
- Institute login, tenant isolation, role-scoped app accounts, forgotten-password recovery and all four connected apps. The optional owner-summary endpoint fails closed unless `SCHOOLFLOW_API_TOKEN` is configured; it is not a completed mobile-app backend.
- Durable deployment database, migrations, backups and secure file authorization. Current free service uses ephemeral SQLite. Never put real student, employee or financial data in this public pre-test environment.

## Validation

`python -m unittest discover -s tests -v`

30 integration tests cover complete record persistence, attachments and password redaction, family linking, validation rollback, CSV safety, menu rendering, fee duplicate/overpayment/reversal/atomicity, installment conservation, attendance upserts, marks bounds and A/L, payroll duplicate prevention/snapshots/pay/unpay, unverified-rule refusal, lecture import idempotency, CSRF disabled message delivery, bill-month versus receipt-date reporting, no-challan students, mixed-bill allocation limits, consecutive absence dates and teacher-performance averages.

The tests use an isolated in-memory database and fictional data. A passing suite does not verify missing workflows or production suitability.
