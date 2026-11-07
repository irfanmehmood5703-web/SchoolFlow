# Remaining web workflows — 7 November 2026

This revision implements the three remaining web items identified in the system
review. It does not claim connected mobile apps or SMS/bank delivery.

## Student Fee Sheet

Admissions → Student Fee Sheet opens a real student/month matrix. Choose up to
12 challan months and show Payable, Paid, Discount or Remaining. Campus, class,
section, session, status/enrolment and student filters use the existing report
scope. CSV, Excel and landscape print use the same data. A dash means no challan;
zero means saved challans have zero of the selected metric. Paid/discount values
are lifetime receipt totals against the chosen bill months, not cash collected
only during that calendar range. No per-head allocation is inferred.

## Lecture Delivery

HRM → Lecture Delivery shows actual lecture-register rows by date, employee,
campus, class, section, subject and approval status, with CSV and print. Its Add /
Import link uses the same existing register and attendance-import flow. Approve
and Reject use the canonical payroll approval endpoint and permissions. Salary
links point to saved salary snapshots. A register entry captured in a salary can
no longer be approved/rejected/voided through the web; its saved payroll amounts
are not recalculated by this report. Consecutive carry-forward remains separate.

## Automatic fee ledger posting

Finance → Ledger → Ledger Setup → Automatic Fee Ledger Posting configures this
opt-in connection. It defaults OFF so existing schools are not assigned invented
accounts or silently double-posted. Map exact Receiving Account names to active
Asset accounts and select an Income account and a discount Expense account.
Enable after defining an open accounting period.

New individual, direct and family receipt payments then post atomically with the
challan update: debit cash/bank for cash received, debit discounts for waived
amounts, credit fee income for their combined value. This is cash-basis gross
income with an explicit discount expense, not accrual recognition at challan
creation. All fee heads use the selected income account. Receipt and GL commit
or roll back together. Unmapped receiving names, retired accounts or missing/
closed periods reject the whole payment; no unposted cash receipt is saved.

The existing payment token prevents duplicate receipts; a unique receipt link
prevents duplicate source journals. System fee vouchers cannot be manually
edited/deleted. General Ledger's Payment ID filter now resolves actual receipt
IDs and includes their posting/reversal journals.

Reversing a linked receipt creates an equal opposite journal on today's school
date using original account/name/class snapshots, even if auto posting is later
disabled or mappings/accounts change. Today's period must be open; the original
period can remain closed. The receipt, challan and ledger reversal are atomic.
A staff member also needs reversal access to the original posting campus if the
student has moved; a scope filter cannot silently hide and skip the GL reversal.

Earlier receipts are NOT backfilled. Do not manually duplicate receipts already
covered by auto posting. Payroll-to-GL automation is a separate workflow. Account
mappings are operator/school-specific and must not be guessed from account names.
No actual bank transfer or external message is initiated by these postings.

Schema changes are additive tables only: fee_ledger_config and
fee_receipt_posting. They use normal institute provisioning/upgrade helpers;
no existing bill/receipt column or value is rewritten.

## Verification

- 605 regression tests passed; targeted report/receipt/payroll checks also passed
  after print/sort refinements. Tests cover both receipt and GL rollback,
  duplicate submission, cash/discount amounts, direct/family batches, closed
  periods, retired mappings, system-voucher protection and moved-campus reversal.
- 11 local Chrome checks passed: real mapping save, payment/discount submission,
  ledger balance, lecture approval, and all three screens at 390px and 1366px.
  No JavaScript errors or overall horizontal page overflow were found.
- Fee Sheet and Lecture Delivery PDFs were generated and inspected. Their
  landscape tables have no horizontally clipped characters or blank pages.
  A full twelve-month, twenty-student Fee Sheet spans two pages; the sample
  Lecture Delivery fits one. This is viewport emulation, not physical Android.

Hosted rollout verification is recorded after deploying this revision to the
isolated free trial. Main and its live service are not changed by this work.


## Hosted result

Revision `644084afb25e53fca2bfe09eec313742d77a0e7e` is live on the isolated free
trial via deploy `dep-dbnc84nf3r2c73886b10` (live 2026-11-07T06:25:26Z).
**29 hosted workflow checks passed**, using only the private fictional school:
fee-head → scoped schedule → student plan → challan → mapped payment50 and
discount10 → GL income60/cash50/discount10 → remaining40 → reversal; duplicate
payment was refused. Fee Sheet Excel and Lecture Delivery creation/approval/
CSV were also exercised through actual web requests.

Independent Neon reads confirmed three balanced original lines (6000 debit /
6000 credit paisa), three balanced reversal lines, a voided receipt, zero bill
paid/discount after reversal, and zero net Asset/Income/Expense test balances.
The initial error-level server log query returned no entries. The new additive
posting tables exist in the private school schema.

The test mapping was explicitly disabled afterward. Real school accounts must
be selected before enabling this optional connection; no fictional chart was
silently enabled for real use. Earlier receipts were not backfilled. Trial and
main remain separate; this is not a main merge or production release. No bank
transfer, external message or paid plan was activated.
