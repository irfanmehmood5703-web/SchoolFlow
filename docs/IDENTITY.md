# Institute login and database boundaries

Public entry: `/` → Sign in → `/auth/institute` → `/auth/login` → Dashboard.

Only web **owner** accounts are supported in this release. Employee-form app
passwords are not silently converted into privileged owner accounts. Teacher,
Parent, SMS and Owner mobile-app account permissions remain pending.

## Operator provisioning

Run on the application host with its intended control database, institute data
directory and a stable `SECRET_KEY`. Never use a production password on the
public ephemeral test deployment.

```sh
flask --app app institute-create
```

The interactive command asks for institute code, school name, owner email and a
12–128-character password (hidden, with confirmation). Passwords use Werkzeug
scrypt hashing. No password is printed, committed, or assigned by default.
Codes are case-insensitive, 3–40 letters/numbers/hyphens. `DEMO` is reserved.
The first owner can sign in after the command succeeds. School data starts empty;
configure school dropdowns and campus certificate headings after signing in.

An authorised operator can recover an owner after verifying their identity:

```sh
flask --app app institute-reset-password
```

This updates the password hash and owner revision, revoking previous sessions.
The Forgot password page does **not** claim a reset email has been sent. There
is no email provider or public reset endpoint yet.

## Storage and routing

- `DATABASE_URL` is the control database and the original fictional demo store.
- `INSTITUTE_DATABASE_DIR` is the institute SQLite directory, defaulting to
  `instance/institutes`. It must be persistent **as well as the control DB** for
  durable school accounts. Moving only the control DB to Postgres does not make
  institute files durable.
- Each institute uses a random immutable `storage_key` filename. Numeric row IDs
  are never reused as storage filenames. Selecting a code only looks up an
  existing registration; it cannot create tables or choose a visitor's file path.
- All current workspace models, their relationships, attachments, reports,
  certificate snapshots and financial records route to the selected institute
  engine. The session's institute must agree with the enabled owner membership.
  Query/form institute IDs are ignored for routing. ORM identity maps are reset
  between requests. Control models always remain in the control database.
- The explicit public demo uses only the original fictional store. It does not
  have a real owner membership and cannot select another institute. Set
  `PUBLIC_DEMO_ENABLED=0` to disable it; existing demo sessions then fail closed.
- QR HMACs include the institute storage scope, so matching pupil IDs in different
  schools produce different codes. Previously issued certificate snapshots keep
  their frozen QR bytes; their integrity is not rewritten.
- Runtime database engines are cached per process. This design is a single-host
  SQLite test foundation, not a distributed multi-host storage solution.

Existing tables are preserved; no automatic migration of demo records into a
school occurs. Provisioning creates that institute's current workspace tables.
After adding a new table, operators can run:

```sh
flask --app app institute-upgrade
```

This only creates missing tables. It does not migrate existing columns. Versioned
schema migrations, backup/restore rehearsal, and production storage architecture
remain required before operational use.

## Session controls and limits

Login rotates the session and CSRF token; sessions expire after eight hours.
Pending institute selections expire after 15 minutes. Disabled owners/institutes
and password revision changes invalidate sessions on their next request. Logout
is POST with CSRF. Auth and workspace responses use `no-store`. Cookies are
HttpOnly and SameSite=Lax; `SESSION_COOKIE_SECURE=1` is automatic on Render, and
must be set for HTTPS on another host. Keep the same strong `SECRET_KEY` on all
workers. The application never trusts a visitor's X-Forwarded-For for throttling.

Atomic control-database throttle counters apply ten login attempts per named
account and 100 per server-observed peer per 15-minute window. Reverse-proxy peer
sharing can cause conservative limits; production needs an explicitly trusted
proxy/client-IP policy and operational monitoring. Expired counters are pruned.
Anonymous API requests now fail 401 even if they supply the former aggregate API
token: a signed-in institute owner must also satisfy the endpoint's configured
token requirement. This is not mobile-app authentication.

The free Render service has ephemeral local files. Keep **fictional records only**
until persistent control and school storage, role permissions, migration/backup
operations and email recovery are completed. Real institutes have not been
provisioned on that public test service.
