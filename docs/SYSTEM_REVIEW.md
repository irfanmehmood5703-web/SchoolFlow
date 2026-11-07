# SchoolFlow system review — 7 November 2026

Scope: current feature branch and isolated fictional Render trial. Original
main service and its branch are outside this rollout. No paid resources or
external messaging were enabled. Existing unrelated dirty checkout was preserved.

## Repairs

- Daily Snapshot income and expense now aggregate posted journal lines for each
  captured date/campus, using immutable account-class snapshots and integer
  paisa. Income credits less debits, expenses debits less credits. Advances,
  returns, cash and equity transfers are excluded; reversing/refunding a posting
  offsets the appropriate amount. Student fee receipts are not added again.
- Enabled current snapshots refresh after ledger posting, Finance correction/
  void and requisition bill operations. Past snapshots are not rewritten;
  unknown legacy ledger captures remain unavailable rather than becoming zeros.
- Student 360° was removed from the main menu per the user's explicit exclusion.
  Existing internal detail/bookmark endpoints remain available.
- Build Status no longer falsely lists deployment persistence and all staff
  permissions as absent. It identifies the actual server database dialect,
  lists existing Finance/requisition workflows and describes real limitations.

## Verification

- Before changes: 592 regression tests passed.
- After changes: 595 regression tests passed, including actual expense/refund/
  campus totals, prior unknown-history handling and requisition advance/bill/
  return effects on snapshots. Menu tests assert the excluded entry is absent.
- Local GET traversal: 159 navigation/inner-form/settings URLs inspected; 157
  returned 200. Subscription requires a real institute owner, and geo attendance
  requires an employee session; their two 403s in the unbound test client are
  expected. No unexpected 404 or 500 was found. This is route coverage, not a
  claim to have exercised every field/role/dataset manually.
- Student Fee Sheet and Lecture Delivery deliberately return a labelled
  incomplete-workflow page, not a working report. They remain unfinished.
- Hosted rollout verification follows deployment; see the rollout entry below.

## Remaining connections and scope

- Fee receipt/payroll-to-General-Ledger automatic posting is not configured.
  Fee reports use receipt data; journal reports use posted ledger entries.
- Teacher, Parent, SMS and Owner apps are not connected. SMS/WhatsApp delivery,
  registered bank consumer integration and automatic bank collection are not
  claimed active. Physical Android/hardware testing is still separate.
- Free sleeping hosts cannot guarantee continuous scheduled jobs; the trial
  worker remains disabled. Snapshot history can have gaps and is not backfilled.
- Backup/restore verification and production hardening remain launch work.
- General Settings reference screenshots are requested next; no unseen fields
  or workflows are claimed implemented. Current web tests are not a completed
  reference-parity audit or a security certification.
