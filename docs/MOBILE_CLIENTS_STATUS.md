# Connected Android clients and school-SIM outbox — 13 November 2026

This release supplies four separate Android test packages, targeting the original
SchoolFlow HTTPS host. Parents, Teacher and Owner are restricted native portal
clients over existing real web workflows, not independent offline/native rewrites.
The SMS client uses Android's actual selected SIM API with explicit per-message
confirmation, multipart count, encrypted connection/pending state and no automatic
resend after the server's dispatch transition. No real SMS was sent during work.

General → App Links → Connect school SIM SMS registers owner-controlled campus
phones. Communication Requests → Review for school SIM previews exact prepared
App SMS snapshots and contacts before explicit release. Existing requests are
not silently backfilled or sent. WhatsApp, branded SMS, push notifications,
parent invitation requests and automatic parent OTP delivery are not claimed
connected by this release. A school-office verified parent code continues to
work in the Parent client. A phone result reports network submission rather
than proof of recipient delivery or remaining SIM balance.

656 backend regressions passed locally. New tests exercise real institute login,
owner CSRF, source release deduplication, campus validation, two-school colliding
device IDs, key rotation, suspension, expiring pre-dispatch claims, single dispatch
and idempotent results. Synthetic numbers/messages only; no external sends.

Initial Android build rejected ambiguous flavour task names. Explicit tasks for
Parents, Teacher, Owner and SMS then passed all four compile/unit/lint builds in
CI at ae04bf21498c752bba5bff50e363ff139875f7ff (run43348656570). The subsequent
lifecycle guard stops a not-yet-submitted SMS when the app has left the foreground;
the main release pipeline verifies that final build before publishing APKs.

Test APKs are debug-signed, exclude credentials/data, include checksums and exact
source provenance, and are published only after both Android and backend CI pass.
Production signing must remain under the software owner's protected key. A test
build is not a Play Store release or a production security certification.

Remaining physical steps: installation on actual Android phones, representative
file upload/download/printing checks, school SIM permission/subscription/network
checks, received-message and multipart tests with approved test recipients, and
process-death/network-loss trials. These cannot be proved by server tests or an
APK compile. Native push, offline synchronisation and broader provider/bank
integrations remain separate work. Original hosting storage configuration is
unchanged; this revision does not establish durable production database storage.
