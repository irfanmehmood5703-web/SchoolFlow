# SchoolFlow Gate 0.2 — isolated connected trial

The trial server is https://schoolflow-gate-trial-irfan.onrender.com, a separate free Render service in the confirmed workspace. The existing schoolflow-phase1 service and main branch remain unchanged. No existing school database was migrated, copied, restarted or reset.

The explicit launcher scripts/start_gate_trial.py seeds one fictional institute (GATE-TRIAL), a fictional person/staff record, one gate and a fictional all-day student shift. It refuses missing opt-in/secrets, enabled public demo and stores containing other institutes. Credentials come only from this new service's private environment. A normal app:app startup never imports the launcher or runs this seed. Notification channels and automatic absence are disabled in the trial. Do not put real school records here.

The debug APK's package is com.schoolflow.gate.trial, named SchoolFlow Gate (Trial), fixed to this HTTPS trial server. It can coexist with the older app. No host text field, arbitrary endpoint, token or school account is bundled. Release builds retain the original SchoolFlow host. This is attended recognition: explicit operator confirmation remains mandatory.

Owner login and gate connection details are supplied privately. Log in to the trial portal, open Admissions → Student Card and Certificates → Student QR Code, select Fictional Gate Campus and print/show the fictional person's QR. In the Android app, unlock the device to enter the supplied connection, verify that card, attest permission and capture three samples. Use the provided fictional record rather than creating real pupil records. Verify the person and press Confirm identity & mark, then check Face Attendance Gates scan history.

Free storage is ephemeral: sleep/restart may clear the trial. The explicit launcher recreates fictional records with a new storage scope; the app then invalidates old enrollment/pending data instead of attaching them to reused IDs. Reconnect/re-enroll after a reset. This server is for short attended trials, not operational attendance or guaranteed scheduled checks.

A fixed server connection, QR identity verification and API-level attendance are distinct from physical face accuracy. Human face enrollment/recognition, real ARM64 camera orientation/permission/UI behavior, representative false accepts/rejects and spoof tests require the user's phone/tablet. No certified liveness, fingerprint reader integration, production signing or durable production deployment is claimed. The four Teacher/Parent/SMS/Owner apps remain separate work.

## Connected trial verification — 6 November 2026

Server deployment dep-dbmkmg6tlv9c73ba1fo0 became live at ac52f71793abbe2e7be015e83aa2bedea8d8a55a. Its /healthz returned schoolflow-pretest-v32. Later APK source 03b578e33fa05e40236075206266abd8c9291b67 changes only Android/workflow/documentation files; server source is unchanged. The original service remains on live deploy dep-dbmb6cavcj2c738dcl0g / main 66b5747.

471 isolated backend tests pass locally (108.403 seconds); the final CI backend job also succeeded. [Actions run 42157710863](https://github.com/irfanmehmood5703-web/SchoolFlow/actions/runs/42157710863) succeeded for the new trial APK, including Android compilation/lint, matching/endpoint tests and native-model/encryption emulator checks.

The following checks were run over HTTPS against the new deployed server using only its fictional trial institute:

- deployed v32 health endpoint
- private trial institute selection
- owner login to private fictional institute
- authenticated current student QR export
- Android-compatible authenticated heartbeat/scope
- exact QR enrollment identity verification
- IN saved by deployed backend
- uncertain-response exact retry is idempotent
- repeated IN does not duplicate attendance
- explicit OUT saved
- stale enrollment binding refused
- foreign/replaced school scope refused
- invalid gate credential refused
- owner can suspend fictional gate
- suspended gate cannot enroll
- trial gate restored for phone testing
- restored gate is connected and usable
- saved outcomes visible in authenticated web scan history

The successful protocol events are not evidence of camera recognition: these were explicit fictional API test events. Real phone face capture, enrollment and recognition still need physical verification with the supplied APK. Trial credentials are delivered privately and are not recorded in this document or bundled in source/APK.

Render free-host storage limitations are documented at https://render.com/docs/free . No persistent production storage or paid service was added.

Verified APK: SchoolFlow-Gate-Trial.apk, 119,188,033 bytes. SHA-256: `bba89be76a8c12871acd414b28904f139dc774b394d65df0c0f830938ed0fb92`. Packaged source manifest, fixed trial endpoint and both model hashes were verified after download. Android reports show 18 unit tests and 9 emulator tests passing.
