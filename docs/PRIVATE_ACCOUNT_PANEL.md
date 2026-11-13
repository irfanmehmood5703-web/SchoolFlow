# Central private-school account panel

The software owner uses `/vendor/setup` once with a private setup code whose
password hash is supplied as `VENDOR_SETUP_HASH`. The initial owner chooses an
email and password; a locked singleton prevents reusing the invitation or
racing another setup request. No default password or public school signup is
provided. `/vendor/login` is linked as Software owner in the public header.
School owners, staff and shared demo sessions never authorize vendor actions.

The central owner can list/search private schools, create a school with its
Institute Code/name/owner email/password, reset a school owner's password, and
change the central password. Changes require CSRF, bounded inputs and database
rate limits; sessions expire after one hour and password changes revoke older
sessions. Audit records contain action, actor and school code, never passwords.

Provisioning uses the existing identity service and creates an empty, separately
scoped school workspace/profile. It copies no demo records. The central session
does not impersonate school owners. Each school signs in through the ordinary
Institute Code and login screens, then prepares its own branded Android apps.

`IDENTITY_DATABASE_URL` optionally binds the identities, central owner/audit,
client subscription and APK signing/build tables to durable PostgreSQL. New
school workspaces use separate PostgreSQL schemas on that same private store.
The existing `DATABASE_URL` and its shared demo data are not replaced. A cutover
guard refuses the new binding if the old store already contains private school
identities; those require backup/migration rather than silently hiding them.
No automatic import, erasure or replacement of existing school databases occurs.

`SCHOOLFLOW_SESSION_KEY` is a persistent fallback only when SECRET_KEY is absent.
`SCHOOL_APP_SIGNING_KEY` keeps new private-app encryption independent from
session keys. Keep all these keys and the PostgreSQL store backed up. Do not
rotate signing keys without re-encrypting saved keys. New deployments must
retain the configured private database URL; an unavailable configured database
fails startup instead of falling back to temporary SQLite.

Private setup must be handed over without putting its code in the repository,
query strings or application logs. Once an owner exists, setup is locked even
if the old environment hash remains configured. All vendor responses are
no-store and use a no-referrer policy. There is no automatic email delivery.

Validation: targeted tests cover bootstrap/CSRF/throttling, separation from
school/demo sessions, real school sign-in/branding, duplicate/reserved codes,
password reset/version revocation, central password rotation/expiry, Unicode
passwords and escaped school names. The dedicated CI workflow repeats these,
existing identity tests and APK queue tests against a disposable PostgreSQL16
service, plus a separate-process retained-school/student check. The hosted
setup screen remains unused until the software owner chooses credentials.

Verified on 2026-11-13: 671 backend tests passed locally. PostgreSQL CI run
43376612524 passed seven vendor checks, 31 identity/cross-school checks, seven
APK queue checks and a separate-process school/student persistence check. The
identity seed fixture now uses generated student IDs so PostgreSQL sequences
remain valid when import tests add new pupils. Fourteen operations tests passed
after health checks were extended to include the configured private store.


Activation completed on 2026-11-13 after the software owner explicitly approved
the new private-account database and setup settings. Original Render service
srv-dbi3dqks728c73c7snv0 is live at deploy dep-dbre1qtbedkc73dbbo6g.
IDENTITY_DATABASE_URL now selects the separate schoolflow_private_accounts
database; DATABASE_URL was not changed. The central-owner, institute and APK
signing tables were confirmed in PostgreSQL. The public vendor setup form is
enabled; owner credentials remain for the software owner to choose.
VENDOR_SETUP_HASH, SCHOOLFLOW_SESSION_KEY and SCHOOL_APP_SIGNING_KEY are
configured in the service, without values in source. Do not regenerate or
replace these settings during later continuation work. Once used, the private
setup code cannot create another central owner. The private handover file is
SchoolFlow-Owner-Setup.txt; it must never be committed.
