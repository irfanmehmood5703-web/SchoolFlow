# Requisition issue and settlement

The user confirmed no populated reference forms exist and authorized completion
using original SchoolFlow forms. These forms are implementation choices, not
claims about unseen EDUBase fields. They use the one existing SchoolFlow ledger.

## Recorded accounting

| Operation | Debit | Credit |
| --- | --- | --- |
| Issue advance | Staff Advances (Asset) | Selected cash/bank (Asset) |
| Bill up to held funds | Selected Expense account(s) | Staff Advances |
| Bill beyond held funds | Selected Expense account(s) | Staff Advances for held portion; Payable to staff for excess |
| Return unspent money | Selected cash/bank | Staff Advances |
| Reimburse staff | Payable to staff | Selected cash/bank |
| Carry forward | No new ledger entry | Allocation moves between requests for the same person/campus |

Approval does not post money. Partial issues and split expense lines are allowed;
positive amounts, account classes, cumulative funding and approved expense budget
are checked on the server. Carry is limited to a later approved requisition for
the same person/campus and retains the original cash age. Returns cannot exceed
held funds; reimbursements cannot exceed the payable. These record financial
activity only; no bank/SMS API or physical cash transfer is initiated.

Settings now select real active ledger accounts. Advances and cash must differ.
The advance/payable mapping cannot change while its corresponding balances remain
open. Block-open and carry rules are enforced. Settle/overdue day windows label
open advances; FIFO ageing consumes the oldest outstanding funds first.

## Safety and audit

Posting requires a CSRF token, actor-bound content fingerprint, unique submission
token, current request/target versions, campus grants and the tenant write gate.
One transaction saves movement, balanced journal, attachment and audit. Changed
retries fail; exact retries do not duplicate postings. The date cannot be future
or precede that request's latest movement, and an open period is required. System
requisition vouchers cannot be edited/voided through manual Journal Inquiry.

Staff need requisition manage plus pay for issue/reimbursement or update for
bill/return/carry. Cash-account grants and payment-date limits apply. Staff whose
payments require a second approval cannot use these forms to bypass that rule;
the owner or a payment-authorized manager must post the approved request. Print
has its own grant. Attachment downloads require management access to that campus.

Bills accept PDF/PNG/JPEG signatures up to 5 MB, with a bounded request size,
sanitized filenames and attachment-only/no-store/nosniff/sandbox responses. Binary
contents are deferred so list/ageing queries do not load all attachments. Files
live in the same tenant database transaction and survive application restarts
only when that database is persistent.

The register reports actual issues, expenses, returns, carries, staff payables
and reimbursements. As-at money positions use posted dates, including explicitly
backdated entries; approval/status labels remain current. FIFO ageing and ledger
Staff Advances balances are compared for permitted campuses. Manual entries that
break the bridge produce a visible reconciliation difference rather than a false
"books agree" message. No past transactions or vendor data are invented.

This adds only a movement table and reuses request/journal models. Existing tenant
databases need `flask --app app institute-upgrade`; the isolated trial bootstrap
creates new tables automatically. Corrections are not destructive edits; no new
reversal UI is introduced by this batch. Physical browser/PDF layout checks,
durable trial storage and the separate Daily Snapshot income/expense bridge
remain outside this completed posting workflow.

## Local validation

Full automated suite: **592 tests passed in 124.208 seconds**. Includes independent
ledger expectations for issue20/bill15/return5, out-of-pocket expense/reimbursement,
partial issues and retry protection, invalid uploads and amounts, approved-budget
checks, carry allocation/age preservation, stale versions, closed periods,
settings/block-open guards, system-voucher protection and staff campus/cash/date
permissions. Python compilation, JavaScript syntax and whitespace checks passed.

## Isolated live validation — 6 November 2026

**33 live checks passed** in the private fictional Gate institute. Created active
ledger mappings and an open period, approved two fictional requests, issued20,
recorded bill15 with a downloadable PDF attachment, returned3, carried2 to the
same person's next request, recorded bill5 (advance2 plus payable3) and reimbursed3.
Final held/payable positions were zero; Advance Ageing and Register reconciled
with the ledger, the printed register included branding/data, and P&L recognised
expense20. Exact issue retry was safe and a changed retry was rejected.

Runtime commit: `96404bc643ae4ffb5fe45348f2924e8b36090c04`.
Live deployment: `dep-dbn0b3mtlv9c73c5ddj0`, live at 2026-11-06T16:52:36Z on the
separate `schoolflow-gate-trial-irfan` service. The verification-only documentation
commit does not require a redeploy. No real bank operation or school record was
used. Post-deploy runtime error-log query found no Traceback/ERROR/Exception.
Browser/phone/PDF appearance was not visually verified; server print/export and
attachment responses were checked. Trial database persistence remains unresolved.
