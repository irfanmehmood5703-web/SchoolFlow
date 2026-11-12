# Persistence and mobile/PDF completion

## Completed code and verification

PostgreSQL now stores both control identities and each institute's workspace.
School data uses an immutable random `school_<storage_key>` schema; identities
and the fictional public demo stay in the control/public schema. Tenant engines
share one bounded connection pool with schema translation per bound engine;
there is no per-school pool explosion. Local SQLite isolation remains supported
for development. PostgreSQL URLs explicitly use the installed psycopg2 driver.

Provisioning on PostgreSQL creates the schema, tables, profile and owner in one
transaction. No schema DDL is performed by an arbitrary sign-in request. Owner
routing releases its control session before entering the tenant. The existing
operator upgrade command creates missing tenant schemas/tables. The trial
launcher uses that same helper. `SCHOOLFLOW_REQUIRE_POSTGRES=1` rejects any
SQLite fallback at startup instead of claiming the deployment is persistent.

Validation on 6 November 2026:

- **592 regression tests passed**, 119.984 seconds.
- **17 explicit local PostgreSQL-compatible checks passed** over the PostgreSQL
  wire protocol using PGlite Socket. Two institutes with the same pupil admission
  number remained isolated. Approval, an advance, expense and bytea attachment
  were saved; a separate app process and database-server restart preserved both
  institutes, the attachment and the reconciled ledger. This is local PostgreSQL
  compatibility evidence, not a claim that a Render database restart was tested.
- **30 browser checks passed** using a local Chrome headless renderer at 390px
  and 1366px. Actual web sign-in, issue payment and a split expense bill with
  attachment were submitted. Twelve populated views rendered at both widths;
  no page JavaScript errors or overall horizontal page overflow were found.
- Three real print PDFs were generated and visually inspected: requisition
  register, a 200-challan student fee ledger and General Ledger. Landscape layout,
  repeated table headings, school branding and all loaded rows were checked.
  PDF text bounds found zero clipped characters on all 16 resulting pages.
- Mobile expense rows now stack as usable fields, the attachment label no longer
  overlaps Add Line, header links have readable contrast, wide reports print in
  landscape, monetary values stay intact, and journal narration remains in print.
- Public JSON-schema validation passed for `render.persistence.yaml`; the
  subsequent Render plan is the authoritative platform validation.

The browser check is viewport emulation, not a physical Android device test.
PGlite is used only for development verification, not the hosted database.
The scripts require only fictional/local fixtures and do not point at school data.

## Free hosted storage — 7 November 2026

The user approved free hosting until launch and explicitly authorized storing
this Neon project's private connection credential on the existing isolated
Render trial service. No paid resource was activated.

- Neon organization `org-flat-cell-41119063` reports plan `free`.
- Project `delicate-block-71773937`, branch `br-soft-breeze-azdm3xgu`, database
  `schoolflow`, PostgreSQL 16, AWS Singapore. Compute is fixed at 0.25 CU with
  the Free plan default idle suspension policy. No Auth, Data API, Functions,
  or additional paid backend was provisioned.
- Render trial `srv-dbmkmfutlv9c73ba1eog` remains plan `free`, auto-deploy off.
  Secret `DATABASE_URL` was merged privately through the Render API; unrelated
  environment keys were preserved. `SCHOOLFLOW_REQUIRE_POSTGRES=1` prevents
  silent SQLite fallback. `SCHOOLFLOW_FINE_WORKER=0` avoids continual idle wakeups;
  on-demand actions remain available, unattended schedules are not promised.
- First deployment `dep-dbn8r1rl550s73egh3ag` became live at
  `2026-11-07T02:32:43Z`. Bootstrap used a direct PostgreSQL connection. Neon
  independently showed 79 public/control/demo tables and 72 private school
  tables after provisioning. The web app authenticated its private owner and
  saved a new fictional student through the actual admission form. A fresh
  request and an independent Neon SQL read both found that same record.
- Application traffic subsequently switched to the pooled connection. Second
  deployment `dep-dbn8t1jrjlhs7382que0` became live at
  `2026-11-07T02:36:55Z`, with a new running instance. A new cookie jar and owner
  sign-in found the same student in the listing and detail page. An independent
  Neon SQL read also found it after redeployment. Requisition creation, settings,
  ageing/report and Ledger Setup pages returned 200 over the pooled connection.
- **19 live web checks passed** (10 save/setup, 9 after deployment). This verifies
  actual admission-save persistence across a hosted Render redeployment, not
  just a browser refresh or a local database restart. The post-deploy error-level
  log query returned no entries. Neon organization still reported plan `free`.
  The broader prior regression/browser suite was not rerun for these deployment
  configuration and documentation changes; there were no runtime code edits.

## Historical paid proposal — superseded

The earlier paid Render Blueprint `exs-dbn1km6k1f9s738rd25g` failed planning
with `need_payment_info` and was never approved or applied. The unused free
Render database `dpg-dbn1bi2fngtc738h5djg-a` was not linked to the app; its
6 December 2026 expiry does not govern the separate Neon project. Do not apply
or upgrade that paid proposal. `render.persistence.yaml` now contains only the
existing free web service and a secret placeholder, with no database resource.

The original main service and branch were not changed. Previous ephemeral
fictional fixtures were not imported; records already lost from a prior
SQLite store cannot be recovered by changing the database. This is a private
fictional test deployment, not a production release or approval to import real
school data. Backup/restore operations, physical Android verification and the broader
remaining app scope are not claimed complete by this storage check. The later
Daily Snapshot ledger connection is documented in SYSTEM_REVIEW.md.
