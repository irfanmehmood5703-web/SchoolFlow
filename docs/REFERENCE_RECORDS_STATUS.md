# Reference records implementation — development branch

This branch implements the student and employee record forms supplied on 30 October 2026. It is not the completed four-module release and must not be deployed over the existing test service as a completed upgrade.

## Implemented and tested

- Every visible student personal, visitor, previous qualification, family, office, board, attachment and communication-preference field from `Screenshot_20261030_120005_com.android.chrome.jpg` and `Screenshot_20261030_120012_com.android.chrome.jpg`.
- Three visitor rows; a student photo; repeated titled document uploads; optional admission-number generation; digit-only Bio ID defaulting to SID; class-dependent subjects; house; new/existing family selection; linked sibling family data.
- Student Save and Go Back, Save and Add New, and Save and View destinations.
- Every visible employee personal, contact, notes, office and Teacher App credential/permission field from `Screenshot_20261030_120033_com.android.chrome.jpg` and `Screenshot_20261030_120036_com.android.chrome.jpg`.
- Employee official photo, repeated documents, code uniqueness, probation date checks and hashed password storage. Saved passwords are never returned in forms, details or CSV exports.
- Teacher App permission values are stored; enforcement in a separate Teacher App is not implemented by this branch.
- Searchable/filterable student and employee lists, update pages, read-only details, record history, CSV exports, browser printing and configurable dropdown options.
- New tables extend the existing Student/Employee schema without dropping or rewriting the starter tables. Existing basic salary is preserved when editing an employee.
- CSRF validation on new record/settings POST routes, validation before writes, transactional saves, file size/type constraints, safe download headers and CSV formula-prefix handling.

## Explicit limitations and unresolved reference details

- Save & Create Salary Plan saves the employee and opens an explicitly labelled pending-payroll page. No salary plan, approval or payment is created. The exact payroll form/calculation reference remains required.
- Communication preferences and requests are stored with `Provider not configured` status. No SMS, WhatsApp or app notification is sent.
- The reference dropdowns were closed, so their complete options are not known. Configure school choices in Record Settings. `flask --app app seed-record-demo-options` creates editable fictional demo choices only; it does not claim to reproduce reference options.
- The reference attendance, exam, payroll, financial, certificate and app workflows in the full audit remain outstanding. This branch does not claim those modules are complete.
- Institute login, account provisioning, multi-tenant isolation, authorization, durable production storage and the connected apps remain required before real records are used. Files inherit the starter app's public test access; use fictional data only.
- Existing SQLite deployment storage is not made durable by these new database tables. A production data migration and persistent datastore remain outstanding.
- Server validation adds integrity requirements such as chronological date ranges, non-negative numeric values and password length. These are implementation safeguards, not claimed EDUBase rule transcriptions.
- Screenshots contain fields and visible choices, not every calculation rule. Remaining dialogs and worked examples must be verified instead of guessed.

## Validation

Run from the repository root:

```sh
python -m unittest discover -s tests -v
```

The suite uses an in-memory database and fictional records. It verifies full record roundtrips, family linking, invalid-write rollback, duplicate protection, password storage/redaction, salary preservation on employee update, save-button navigation, attachment download/removal, CSRF, class-subject validation, legacy-record rendering, filtered exports and CSV formula handling.

Local HTTP rendering checks cover Dashboard, legacy Admissions/HRM entry redirects, new list/forms/details/settings, Attendance and Exams. Full browser validation and Render release verification are pending the complete upgrade.

## Next source inputs

1. Create Award List and the actual marks entry/update form.
2. Create/Edit Date Sheet and exam hall/roll-number allocation dialogs.
3. Complete salary-plan editor and one worked example for deduction, proration and rounding rules.
4. Remaining dialogs listed in the reference audit, including fee plans/payments and employee shift/leave/lecture/security operations.

Main branch and the current Render deployment are intentionally unchanged until the complete requested release is ready and verified.
