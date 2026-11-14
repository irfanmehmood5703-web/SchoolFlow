# Challan bank account, student photo and QR layout

Requested 14 November 2026. Existing bank account fields and photo controls are retained and made easier to find in Challan Branding.

- Bank name, account title, account number and IBAN print immediately below the school heading on every selected copy. Empty bank details omit the block. Settings still support institute defaults and full campus overrides; previews do not save a configuration or modify bills.
- The Show student photo option uses the student's saved Admissions photo. No saved photo produces a labelled empty area. A bill-scoped authenticated image route allows the campus's fee-print staff to print a photo without granting access to unrelated Admissions records or documents. Turning the photo option off disables that image route.
- Show challan-reference QR is a separate setting (default on). Its PNG is embedded in the print document. The payload contains the SchoolFlow challan type, bill number and existing internal consumer reference. It contains no student name, contact, amount, login credential or payment authority. Family copies retain a separate QR per bill even when the consumer reference is shared.
- The existing optional school payment-link QR remains separate and requires a school-supplied HTTPS payment link. Neither QR establishes a bank integration or confirms a payment. School-SIM, payment and account storage are unchanged.
- Saved amounts, plan concessions, payments and receipt discounts are not recalculated by layout/preview/printing. Existing tables and secrets are unchanged; the additional flag uses the existing JSON settings.

Location: Admissions → Fee Challans → Print settings → Configure copies, colors, bank details and campus branding. Direct authenticated route: `/workspace/core/fees/challan-branding`. Student photos are uploaded through Admissions → Manage Students → Edit student → Photo.

## Checks

19 challan tests and 38 staff tests passed locally. They include bank placement and escaped text, missing/hidden photos, exact saved amounts, campus overrides, PNG/payload validation, optional payment QR and campus-specific fee-print permission. Full regression and hosted deployment evidence are recorded below after verification.

An isolated sample was rendered through the actual print route and stylesheet to a one-page A4 landscape PDF. All three QR codes were decoded independently from the rendered page; each matched the same saved sample bill/reference. The three-copy image was visually inspected for clipping and overlaps. Bank details and the photo in the shared preview are explicitly labelled samples. No bank data was guessed or saved into a real school.


## Verified release — 14 November 2026

- Full backend suite: **698 tests passed** (79.492 seconds). Diff checks passed.
- PostgreSQL private-account, tenant-isolation, 19 challan and 38 staff-scope checks, restart persistence and existing browser regression checks passed in Actions run **43555212269**.
- Runtime commit `24f6da9b86c34c66a6d5a3b2a33242fc0e572d96`; original Render service `srv-dbi3dqks728c73c7snv0`, deployment `dep-dbrtvfc9v7es73b9v6l0`: **live**.
- The provided sample PDF has one A4 landscape page; all three printed QR codes decoded successfully from its raster image. It is a print preview from the actual print route and stylesheet, not a live-browser screenshot or physical-device test.
- **9 hosted checks passed**: demo entry, live settings, all three unsaved preview copies, bank-above-student layout, embedded QR copies, missing-photo label, unchanged saved account/version after preview, new stylesheet and HTTP200 health. Hosted verification used only the unsaved preview and did not save sample bank details or change student bills.

## Boxed detail layout — 14 November 2026

Bank name/title/account/IBAN and student name/guardian/ID/class/family/consumer/challan/month/due date now print as bordered two-column label/value tables. Table headings use the selected primary theme and label cells use the selected secondary color. Photo/QR controls and all financial values are retained. Nineteen existing challan tests passed after this layout-only edit; the single-page three-copy PDF was inspected and all three reference QR codes decoded from its image.
