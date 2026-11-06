# SchoolFlow continuation — 6 November 2026

> Update: A separately deployed connected trial and new 0.2 APK are now available. See [GATE_TRIAL.md](GATE_TRIAL.md) for current verification and setup. The original main deployment remains unchanged. The older APK evidence below is retained as history.

## Preserved source

The existing repository was resumed, not recreated. Reviewed all four remote branches: main, feature/schoolflow-gate-android, upgrade/reference-complete-phase1 and upgrade/report-workflows. Main remains at 66b5747b9d07c6232c7a27db0ac7522a46877e7c (v31). The resumed Android branch was at 5d53ff84f2633cd94cf057faf0276e3546812e63. Earlier Android commits and all server features are retained. No merge, Render deploy, restart, environment change or production-data write was performed.

## Existing work found

| Area | Verified source state |
| --- | --- |
| SaaS | Existing Dashboard, Admissions, Exam & Attendance, HRM, institute setup, staff permissions, payment approvals, certificates and audit history retained. Existing pre-test limitations remain; this report does not certify every reference workflow as complete. |
| Gate backend v31 on main | Campus-scoped gate administration, credentials/rotation, heartbeats, signed QR attendance, explicit IN/OUT, idempotent scan history and opt-in shift-based attendance rules. |
| Native enrollment branch | Exact QR identity verification, institute/gate scope pins and deletion-cascaded person-incarnation bindings. Additive attendance_identity_binding table and explicit institute schema upgrade required. |
| Android | Camera, QR reading, three-sample local enrollment, native YuNet/SFace inference, conservative matching, explicit operator confirmation, Android Keystore encryption and exact pending-event retries. |
| Other four apps | Teacher, Parent, SMS and Owner apps remain separate unfinished scope; SchoolFlow Gate does not complete them. |

## Improvements in this continuation

- 109ce6f418298325cd3c2da4f7073d776fd5cc8a: check every incoming face sample against every stored sample belonging to another person. Ambiguous recognition cannot permit another duplicate enrollment. Enforce the check in encrypted storage as well as the enrollment screen; replacing the same identity remains supported. Added three matching-policy tests and an encrypted-storage duplicate-enrollment regression test.
- Publish camera identity, feature, timestamp and stability in one immutable observation to avoid mixing results across camera/UI threads. Confirmation also rechecks identity binding and direction, and requires the activity to be visible.
- Make the top controls horizontally scrollable on narrow displays. Retain Actions artifacts for 14 days rather than one day.
- 423cc5cfbb6dd73bc191cb76416bf01383ab61e8: explain how to obtain the actual Actions APK and show a clear fail-closed message when the server lacks the native enrollment/scope contract.

## Validation

Local full backend suite: **467 tests passed in 101.356 seconds**. Tests use isolated fictional institutes and do not contact live school databases. This includes prior fee, payroll, attendance, settings, permissions and tenancy protections plus native identity bindings. Diff whitespace checks pass. A targeted current-source scan found no private-key/GitHub-token/AWS-access-key patterns; this is not a full secret-history or penetration audit.

Final [Actions run 42153502588](https://github.com/irfanmehmood5703-web/SchoolFlow/actions/runs/42153502588) **succeeded** for source commit 423cc5cfbb6dd73bc191cb76416bf01383ab61e8.

| Check | Result |
| --- | --- |
| Backend integration suite | 467 passed locally; final CI backend job succeeded |
| Android matching/endpoint unit tests | 18 passed; 0 failures or ignored tests |
| Android emulator instrumentation | 9 passed; 0 failures, errors or skipped tests |
| Android compilation and APK packaging | Passed |
| Android lint | 0 errors; 21 warnings (target/dependency/API, backup-rule and localization cleanup remains) |
| Downloaded artifact integrity | Both archive digests match GitHub metadata; APK checksum matches its manifest |
| Packaged recognition models | YuNet and SFace sizes/hashes verified against model provenance |
| APK source identity | SOURCE-COMMIT.txt matches the final tested source commit |

The delivered **SchoolFlow-Gate-test.apk** is 119,187,865 bytes (approximately 114 MiB). It includes ARM64 and emulator x86_64 native libraries. Its SHA-256 is:

`5d7e0b2a94b1c361516bf17ad4d27715b079cd666fc6c6ecfd0a88aff91ebefc`

The APK is available in that Actions run's SchoolFlow-Gate-test artifact and is supplied directly with this report. The feature-branch build deliberately skipped publishing a main-branch prerelease. The emulator exercised native inference on synthetic pixels, synthetic QR decoding, encrypted round trips, tamper failure, school-scope clearing, protected app launch, cleartext/backup restrictions and duplicate-enrollment refusal. These results do not certify physical ARM64 camera compatibility or human face accuracy.

## Server compatibility and release limits

The native enrollment backend is still on the feature branch. Main v31 does not include its scope/identity endpoint contract, so this APK cannot yet complete native enrollment against that server. Downloading or building the APK does not deploy the backend. Main and Render were deliberately preserved. The direct live health request timed out; live availability is not certified by this session, and Render management state could not be inspected because no workspace was selected.

Before a future reviewed rollout: preserve existing institute data, confirm durable storage/backups, deploy the compatible backend and explicitly upgrade private institute schemas. The current free-host storage was previously documented as ephemeral; a restart is not an appropriate way to enable enrollment without protecting data.

## Remaining physical and production checks

1. Install on an ARM64 Android 8+ test phone/tablet with a device PIN/pattern/password, initially using fictional identities. Verify camera permission, front-camera orientation, QR reading and compact-screen controls.
2. After a compatible test server is available, provision a private fictional institute/gate. Validate exact-card enrollment, three consistent samples, duplicate refusal, unknown/ambiguous/multiple faces and recognized-person confirmation.
3. Verify web scan history for IN, repeated IN, OUT, suspension/removal, foreign campus/institute, token rotation, network loss/retry and scope resets. Automated backend tests already cover these protocol safeguards; physical end-to-end verification remains pending.
4. Evaluate representative consented face accuracy, false accepts/rejects and spoof attacks. Native synthetic-image inference tests are not proof of face accuracy or liveness. Keep explicit human confirmation; no certified liveness is claimed.
5. Prepare production signing under the software owner's own protected key, owner-controlled distribution, durable hosting, backups and an operational/security review. The delivered APK is debug-signed for attended testing, not a production release.

## Installing and opening the test APK

Download the APK supplied with this report, allow installation from the app/browser used to download it, and open SchoolFlow Gate (Test). Set a device screen lock before changing Connection, enrollment or local faces. Grant camera access only on the test device. Android 8+ ARM64 is the phone/tablet target; x86_64 libraries are included for emulator verification.

This build uses the Android debug signing identity generated by its CI runner. A previously installed build from another runner may require uninstalling first; uninstalling destroys local enrollment, connection and pending-event storage. Resolve/check any previous pending attendance in web scan history before removing an existing test installation. Production updates must use the software owner's persistent protected signing key.

No school key, account or face template is supplied in the APK. Native connection/enrollment remains unavailable until the compatible backend is safely deployed. Operator confirmation is mandatory after a stable recognized face.
