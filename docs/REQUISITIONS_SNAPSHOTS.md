# Daily Snapshot and Requisitions reference batch

Reference: supplied Daily Snapshot history; My Requisitions list/new form/status and category dropdowns; empty Approval, Issue Payment, Settlement, Advance Ageing/Register; Requisition Settings. No vendor pupil records, dates, balances or personal identifiers are copied.

## Observed daily history

A new immutable-past snapshot store records current school state per campus/date. Start/refresh recording is an explicit CSRF-protected POST; a history GET never fabricates records. Source writes refresh enabled current snapshots, and the existing enabled host worker refreshes them every minute. `flask snapshot-capture --code CODE` supports an external always-on scheduler. Sleeping free hosts may have gaps; earlier dates are never filled with today's values. Existing institutes require the normal tenant upgrade before using new tables.

Past saved dates stay frozen; today's state is provisional and has a capture timestamp. The first cohort is a baseline. Joined/left counters measure observed enrolment-status changes between captures, excluding campus transfers; they do not claim to recover missing historical admissions dates. A capture is serialized with the institute write gate and collects the whole institute internally even after a campus-scoped staff write, restoring staff scope before any response. Internal capture failures preserve the already-completed source response and are logged.

Strength counts active pupils. Attendance uses Present/Late over marked statuses excluding Off Day; no marks gives an unknown percentage. Captured fee positions include bills through the captured month, with expected, collected, discounts and outstanding kept separately. Summary closing positions use the latest saved campus positions in the loaded range; movement and attendance cards sum the recorded rows. Campus/date filters, branded print and basic immutable Class/Student drill views are available. Exact reference drill layouts were not supplied.

Daily Snapshot Income/Expense is explicitly unavailable until the New Ledger source is connected. The original manual Ledger is not silently substituted. The history page explains recording coverage and gaps rather than presenting invented zero financial results or historic events.

## Requests and approvals

My Requisitions includes the supplied six categories, campus, needed-by date, purpose and repeated Item/Qty/Unit price/Amount rows. Totals are computed server-side with decimal quantities (up to three decimals), integer-paisa unit prices and rounded paisa line totals; client amounts are ignored. All estimates are bounded. Number prefixes are saved in settings; the institute write gate serializes tenant-wide requisition numbering regardless of staff campus filters. Actor-bound submission fingerprints make exact retries safe and reject changed payloads.

Lists and detail/cancellation are owned by the signed-in actor and campus grants. Separate requisitions approval permission controls the approval queue/decisions; separate management-report permission protects issue/settlement/register pages. Approval supports partial amounts, requires a positive amount no higher than the estimate, records remarks/actor/time and changes state atomically with version and retry safeguards. Rejection requires a reason. Only an owned awaiting-approval request can be cancelled. These are explicit implementation validation choices where the supplied empty lists do not reveal further business policy. Approval never moves money or creates a journal.

## New Ledger dependency — intentionally unresolved

The reference explicitly says requisition accounts belong to **New Ledger, not the original finance module**. That account directory/setup has not yet been supplied or implemented. Requisition Settings therefore shows unavailable New Ledger account choices and rejects arbitrary original Ledger IDs. It saves the supplied prefix, settle/overdue days, block-unsettled, carry-unspent and bill-attachment rules with optimistic versions and Core Settings permissions. Rule enforcement on issued advances is pending the New Ledger bridge; approved/unissued requests are not falsely treated as staff holding money.

Issue Payment and Settlement show the supplied information, warnings and columns. Financial POST endpoints are blocked server-side. No advance, expense, payable, return, bill or bank/cash transaction is invented. Advance Ageing correctly shows no workflow issues and explicitly says book reconciliation is unavailable; it does not claim its zero agrees with unconnected books. The register lists actual request/approval states, with zero issued/billed/returned because no issue posting exists.

Required next reference: New Ledger → Ledger Setup/account directory, plus populated issue/bill/return/carry-forward forms when available. These dependent posting workflows are not claimed complete. Bill attachments, actual payouts, New Ledger reconciliation and full historical ownership/financial integration remain outside this batch. Physical browser/mobile/PDF visual checks and permanent trial storage remain pending.

Validation: full project suite passed 572 tests in 105.643 seconds. Focused tests cover Decimal totals and tamper rejection, independent partial approvals without financial posting, actor-bound retries, cancellation/stale decisions, settings versions, blocking original Ledger IDs, immutable snapshot history and independent fee/attendance totals. Additional tests verify owned/staff campus restrictions, tenant separation and whole-institute internal capture restoring staff scope. Python compilation, JavaScript syntax and git whitespace checks passed. Remote rollout and saved PDF/browser visuals are tracked separately.

Final input validation rejects scientific notation and mismatched precision so server totals match the client decimal display. The final focused requisition/snapshot suite passed 17 tests after the last validation/template refinements.
