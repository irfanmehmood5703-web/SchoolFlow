# School-specific Android downloads

Each private institute's App Links page derives launcher labels from its saved
Institute Setup name (or the owner's optional shorter app display name) and its
saved PNG logo. Parent, Teacher, Owner and SMS roles receive independent package
IDs under the institute's immutable storage identity. The shared DEMO continues
to expose generic test APKs; it cannot submit a private school build.

When an owner chooses Prepare this school's apps, the server snapshots only
public branding metadata/logo and queues a build. Generic URLs cannot replace
these four apps for a private school. The first build is asynchronous; the
central worker checks approximately every15minutes, subject to GitHub scheduling.
A ready download is cached and requires no repeat compilation. Saving a new
name/logo invalidates old downloads until the matching build is prepared. A
rename, including a rename back, uses a new versionCode and retains the signing
identity/package IDs. Submit the school's current legal name to follow future
Institute Setup name changes; a different short label remains an explicit override.

The worker runs only from the software owner's exact main-branch workflow. The
server verifies GitHub's RS256 signature, issuer, strict audience, repository ID,
repository, subject, branch, workflow path, event, expiry and run identity. No
long-lived GitHub token is needed in Render. PR/fork/foreign-workflow tokens cannot
claim jobs. The workflow uses short-lived OIDC; the signing password/PKCS12 is
transferred only to that authenticated worker over HTTPS and is never put in
source, APKs, release notes or build artifacts.

Signing identities are unique per institute, encrypted in the control database
using a key derived from the server's SECRET_KEY, and reused for updates. The
worker verifies each actual compiled APK's label, package, version, certificate,
logo pixels and checksum before callback. The server binds completion to the
leased run and school and checks all four metadata records/checksums before
publishing. Only two finished APK revisions are retained; signing identities
are retained. Failed builds can be retried up to three times. Three distinct
school builds per24hours limit unintended build churn.

APK-only opaque share links let the school distribute its Parent/Teacher APK
without sharing a staff login. They grant no access to school records; ordinary
parent/staff/owner authentication remains required. An inactive institute cannot
serve its APKs. Unknown tokens and cross-institute authenticated downloads are
refused. The APK contains the school code/branding as public identifiers, no
passwords, SMS device connection keys, child records or private signing material.

A missing school logo produces an initials icon and a visible instruction to
upload the official logo. It is not an invented official school logo. Existing
installed generic test APKs do not rename themselves: install the corresponding
school-specific APK. This is a test Android client release, not a Play Store
publication, offline-native rewrite, physical-device validation or production
security certification.

## Operation and persistence

Keep the institute/control database and SECRET_KEY durable and backed up. Loss
of the control database/signing material breaks future update continuity.
SchoolFlow's original host was last verified as temporary SQLite development
storage; this change does not migrate or erase it. Existing-data confirmation
and a verified backup/migration remain required before operational school use.
Do not present these tests as proof that temporary hosting preserves keys.

The GitHub workflow uses standard public GitHub-hosted runners; no paid host,
SMS provider or new cloud service is provisioned. Scheduling may be delayed or
disabled by GitHub and consumes the account's existing free resource allowance.
The worker can also be run with GitHub's workflow_dispatch by the software owner.
Protect repository write access: trusted main-branch code is the build authority.
If the native client source changes, increment snapshot source_version so schools
receive a new, monotonically-versioned build under their existing key.

## Verification

664 backend regressions passed in the initial revision. New tests exercise two
real institute login contexts, school naming, absence of generic substitution,
request deduplication, logo invalidation, cross-school isolation, shared APK-only
URLs, inactive-school refusal, encrypted signing storage, signer continuity,
rename-back version increments, OIDC trust rejection and job leases.

The Android verification workflow compiles four actual APKs each for two
fictional schools (ISF School System and Sadia School), then compiles an updated
ISF branding revision to check stable signing/package identity and increased
version. These fixtures and keys are isolated and never become live institutes.
Final build and hosted results are recorded after the verification run completes.
