# SchoolFlow Gate 0.2 — isolated connected trial

The trial server is https://schoolflow-gate-trial-irfan.onrender.com, a separate free Render service in the confirmed workspace. The existing schoolflow-phase1 service and main branch remain unchanged. No existing school database was migrated, copied, restarted or reset.

The explicit launcher scripts/start_gate_trial.py seeds one fictional institute (GATE-TRIAL), a fictional person/staff record, one gate and a fictional all-day student shift. It refuses missing opt-in/secrets, enabled public demo and stores containing other institutes. Credentials come only from this new service's private environment. A normal app:app startup never imports the launcher or runs this seed. Notification channels and automatic absence are disabled in the trial. Do not put real school records here.

The debug APK's package is com.schoolflow.gate.trial, named SchoolFlow Gate (Trial), fixed to this HTTPS trial server. It can coexist with the older app. No host text field, arbitrary endpoint, token or school account is bundled. Release builds retain the original SchoolFlow host. This is attended recognition: explicit operator confirmation remains mandatory.

Owner login and gate connection details are supplied privately. Log in to the trial portal, open Admissions → Student Card and Certificates → Student QR Code, select Fictional Gate Campus and print/show the fictional person's QR. In the Android app, unlock the device to enter the supplied connection, verify that card, attest permission and capture three samples. Use the provided fictional record rather than creating real pupil records. Verify the person and press Confirm identity & mark, then check Face Attendance Gates scan history.

Free storage is ephemeral: sleep/restart may clear the trial. The explicit launcher recreates fictional records with a new storage scope; the app then invalidates old enrollment/pending data instead of attaching them to reused IDs. Reconnect/re-enroll after a reset. This server is for short attended trials, not operational attendance or guaranteed scheduled checks.

A fixed server connection, QR identity verification and API-level attendance are distinct from physical face accuracy. Human face enrollment/recognition, real ARM64 camera orientation/permission/UI behavior, representative false accepts/rejects and spoof tests require the user's phone/tablet. No certified liveness, fingerprint reader integration, production signing or durable production deployment is claimed. The four Teacher/Parent/SMS/Owner apps remain separate work.
