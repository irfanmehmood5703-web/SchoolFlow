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

## Hosting plan awaiting explicit approval

A free `schoolflow-storage-trial` PostgreSQL 16 instance was created in the
existing Singapore workspace with no paid upgrade applied. It expires on
**6 December 2026** and is not a permanent storage solution. The current trial
continues to use temporary SQLite until the reviewed plan is applied.

`render.persistence.yaml` adopts only that database and the existing isolated
`schoolflow-gate-trial-irfan` web service. It leaves main out of the plan. It
upgrades the database to `0.1c-256mb`, requests 1 GB, disables external database
access and injects the internal connection string via `fromDatabase`; no database
credential is copied into source code or chat. Existing service secrets are
preserved. Web compute remains free and auto-deploy remains off.

Published compute is $6/month; expandable storage is listed at $0.30/GB/month
and the current pricing page also lists an included 1 GB. Allow an estimate up to
$6.30/month for this 1 GB plan, before tax and any other account usage. The actual
Render billing/plan should be reviewed before approval. No paid spend is enabled
by merely committing or planning this file.

After approval: apply the reviewed sync, wait for the exact deploy to become live,
then save a fictional sentinel, issue/bill and attachment, redeploy/restart the
web app, sign in again and verify all persisted values. Only after that can the
hosted persistence issue be marked resolved. Existing temporary test records may
reset at the storage switch; do not import real records yet. Recovering records
already lost from an earlier ephemeral database is not possible from this code.

Native PostgreSQL backups/PITR and restore verification are operational follow-ups
once a non-expiring hosted database is activated. The separate Daily Snapshot
income/expense bridge and the broader unfinished SchoolFlow/app scope are not
claimed complete by these checks.

PDF content verification additionally confirmed all 200 pupil/challan rows,
all 200 intact `40.00` payment values, and repeated headings on every student
ledger and General Ledger page. Reports were rerendered after the layout fixes.
