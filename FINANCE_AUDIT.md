# Finance setup and audit reports

Finance retains one accounting engine. The outer menu has Ledger, Journal Inquiry,
General Ledger, Day Wise P & L, Cash Report, Shareholders, Daily Snapshot Report,
the six requisition screens, Fee Audit Report, Voided Transactions and Voided
Challan Transactions. Groups, accounts, chart and periods live inside Ledger.
Existing master URLs remain valid.

Ledger Setup counts actual accounts/periods/journals and checks journal balance,
empty journals and missing chart links. Existing accounts are already canonical;
there is no duplicate Old/New database or pretend migration. Period names and
journal narration use additive metadata tables. Corrections retain the original
narration and create a new header; retry fingerprints include narration. Period
closing still blocks posting and requires approval rights. Closing a period does
not automatically post a year-end profit transfer.

Fee Audit uses challan fee month (inclusive months), generation-time cohort
filters, today's student status, installment inclusion, payment state, summary
and one-challan-per-row student views, CSV and complete print output. The student
expanded detail ignores class/section/session/state filters but retains dates,
campus authorization and selected campus. Active receipts, pending approval
requests, posted discounts and posted remaining balances are distinct. Pending
requests are not deducted from the posted debt. Differences between old paid
balances and actual recorded receipts are surfaced for reconciliation.

New challans retain class/campus/section/session using transaction-local mapper
hooks. Existing bills have no proven generation cohort; they are explicitly
unavailable under historical cohort filters. The app never labels today's class
as a historical class. Single-head bills permit unambiguous payment attribution;
multi-head bills without receipt allocations show unavailable head allocations.
Only observed fine markers/names contribute to the fine subtotal.

Voided Transactions includes original lines of voided journals, with actual
actor/time and immutable chart names. Reversal lines remain in General Ledger.
Voided Challan Transactions records amount changes, deleted bill snapshots and
voided payments/discounts in the same tenant transaction. History remains after
hard deletion and handles reused SQLite bill IDs. Rollbacks discard their audit
changes. Existing incomplete logs are not presented as reconstructed history.
Expiry/source payment IDs stay unavailable when their source has no value.

All these reports require Finance view for every configured campus. CSV and print
require their separate permissions. No screenshots' personal records are seeded.
Additive tables need `flask --app app institute-upgrade` for an existing institute;
the isolated trial bootstrap creates them automatically.

Limitations: physical browser/phone/PDF visual verification is pending. Trial
SQLite storage is ephemeral and must not hold real school data. Durable storage
is unresolved. Requisition issuance/settlement and daily snapshot accounting
bridges remain blocked/unconnected as documented in REQUISITIONS_SNAPSHOTS.md.
This change does not claim the complete Finance module is finished.
