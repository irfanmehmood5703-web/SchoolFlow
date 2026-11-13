# Shareholder workflow completion

The user authorized original SchoolFlow workflows without further reference
screenshots. This extends the existing directory/profile; it does not seed a
real shareholder or copy EDUBase's data or unpublished behavior.

Each saved shareholder opens Record / view transactions. The following actions
use the institute ledger and require an open Accounting Period and configured
cash/bank and Equity accounts:

| Action | Debit | Credit |
| --- | --- | --- |
| Capital contribution | Selected cash/bank | Partner's linked capital Equity |
| Capital withdrawal | Partner's linked capital Equity | Selected cash/bank |
| Approved profit payout | Selected distribution Equity | Selected cash/bank |

The distribution Equity account must be separate from every partner capital
account and hold sufficient recorded credit in the selected campus. The
current-percentage estimated share does not itself authorize payouts, close
income into retained earnings or create a payable. Payouts are not expenses.
These actions record agreed money movements; they do not initiate bank transfers.
Withdrawals cannot exceed the partner's recorded capital in the selected campus.
The selected date cannot precede the latest capital/source-account activity,
preventing backdated withdrawals/payouts from overdrawing later balances.

New money requires an active partner, matching scope/profile version, active
accounts/campus, positive integer-paisa amounts and CSRF. Exact actor-bound token
retries return the same voucher; changed payloads are refused. The institute
write gate serializes balance checks and postings. Any validation failure rolls
back the entire source record and journal.

Reverse requires Finance delete permission, a reason, explicit confirmation and
an open period on the selected reversal date. It creates an equal opposite
voucher while retaining the original amounts/snapshots. A second reversal is
blocked, and contributions cannot be reversed after their capital was withdrawn.
Reversals retain historical account names even if an account is retired. Journal
Inquiry uses the normal journal-change record to recognize reversed originals.
System shareholder entries cannot be manually corrected/voided through generic
journal editors. Undo dependent withdrawals first when correcting contributions.

Staff need all-campus Finance grants. Create, delete, export and print are
separate permissions; recorded cash/bank accounts must also be granted. Staff
requiring two-step payment approval cannot post outbound shareholder money here;
the school owner can record an approved transaction. No approval is fabricated.

The dated statement shows linked-account activity plus dedicated payout/reversal
records, opening/closing capital, references, original vouchers and reversal
links. CSV neutralizes spreadsheet-formula prefixes in text; print/PDF uses the
school branding and the same date scope. Dedicated movements are counted once,
not once per debit/credit line. Profile edits create dated before/after snapshots;
this starts history going forward and does not invent earlier ownership changes.
Current-percentage estimates remain labelled; automatic historical/prorated profit
distributions are not inferred. Posted partner scope cannot be replaced.

Schema changes are additive shareholder_movement and shareholder_revision
workspace tables. Existing school namespaces receive missing tables through
the normal startup upgrade; no business records are deleted or seeded. Private
account database URLs, session keys and APK signing keys are not changed.

Targeted tests cover balanced contributions/withdrawals/payouts, insufficient
capital/distribution balance, shared-pool backdating, closed periods, stale forms,
exact retry/changed-payload refusal, append-only reversals, partner mismatch,
private-school persistence/isolation, staff grants/account/two-step restrictions,
CSV safety and profile history. Full regression and hosted deployment results
are recorded after completion. No real-school transaction or SMS was sent.
