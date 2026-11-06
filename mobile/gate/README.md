# SchoolFlow Gate — Android attended test app

Native face-attendance companion for SchoolFlow's existing private-institute Face Attendance Gates. This is separate from the planned Teacher, Parent, SMS and Owner apps.

## Test installation

Download **SchoolFlow-Gate-test.apk** from a successful **SchoolFlow Gate Android** Actions run's **SchoolFlow-Gate-test** artifact (extract the ZIP first), or from a published **SchoolFlow Gate test** prerelease when available. Check SOURCE-COMMIT.txt and SHA256SUMS.txt against that build. Feature-branch builds do not automatically publish a prerelease or deploy the website. It is a debug-signed test build for fictional identities, not a Play Store or production-signed app. Supported build targets are ARM64 Android 8.0+ and x86_64 for automated emulator tests. Actual camera/device compatibility is still subject to physical testing.

**Server prerequisite:** the native enrollment/scope endpoints in this feature branch must be reviewed, deployed and explicitly schema-upgraded before this APK can connect. The v31 server on main does not yet provide that native enrollment contract. Building/downloading the APK does not deploy those endpoints. Until the server is upgraded, the app pauses connection/attendance rather than using an unverified identity. Existing QR-scanner/device workflows remain separate. Do not restart the current ephemeral test deployment solely to install the APK.

1. Set a PIN, password or pattern on the school device. Install the test APK and grant camera permission.
2. In the SchoolFlow web portal, register a face gate for the correct private school/campus, then use Connect to issue its connection key. In the Android app choose Connection, unlock the device, and enter the private institute code, numeric gate ID and key. DEMO cannot connect. The server address is fixed to https://schoolflow-phase1.onrender.com in this test release.
3. Choose Enroll face and unlock the device. Scan or paste a fictional person's SchoolFlow identity-card QR, then press Verify card. The app retrieves that exact active person's name/ID from its gate's campus; no bulk roster is downloaded. Attest that this actual person and enrollment permission are verified. Capture three samples of the same person.
4. Start the camera, select IN or OUT, and show one enrolled person. Matching must be stable and unambiguous. The operator verifies the person and explicitly confirms the mark. Check the web scan history for the actual server result.
5. Test suspension, foreign-campus refusal, repeated IN/OUT, loss of connectivity and key rotation before considering any operational use.

Settings and enrollment require the device's own screen-lock credential. Local templates can be deleted in Manage faces. Changing institute or gate explicitly clears local enrollment and pending submission after confirmation. A changed server-institute incarnation also invalidates old local enrollment, with a visible message; pending events cannot be posted into the new scope. This does not erase attendance already saved by the server. Do not share a tablet screen-lock credential or connection key with unauthorized people.

## Recognition and privacy

- OpenCV 4.12.0 with official pinned YuNet 2023mar and SFace 2021dec model files performs actual native inference locally. Build and startup verify SHA-256 hashes. License texts ship in the APK's assets.
- Enrollment stores three feature vectors per identity, never a saved camera photograph. AES-GCM uses an Android Keystore key, an app-private backup-excluded file, cloud backup disabled, and protected screens.
- The app sends the verified signed identity QR, record-incarnation binding, explicit direction, event ID and timestamp to the authenticated device API. No face picture or vector is uploaded.
- Unknown, poor/small/multiple or ambiguous faces are refused. Matching uses a conservative 0.55 cosine threshold with 0.08 margin and repeated stable frames. These are starting parameters, not an accuracy guarantee.
- New enrollment checks every captured sample against every sample of other local identities. An ambiguous recognition result cannot bypass the duplicate-enrollment guard; replacing the same identity remains possible after device unlock.
- This app does **not** claim certified liveness or anti-photo-spoofing. It is attended: recognizing a face alone never silently marks attendance. A human verifies the person before confirmation.
- The app does not automatically import school photos or enroll identities from the central roster. It resolves only a presented signed identity QR through an authenticated same-campus endpoint. An administrator still verifies the actual person and permission. Record-incarnation bindings are removed by database cascade when a person is deleted; reusing their numeric ID or admission number does not reactivate an old face enrollment. Scope checks bind the app to the institute's storage identity and registered gate, even if a school code or gate number is reused after a reset.
- No templates, school credentials, real identities or production signing keys are included in source, CI fixtures, APK or test reports.

## Delivery behavior

The app uses the existing HTTPS gate heartbeat/events contract in ../../docs/ATTENDANCE_DEVICES.md. It refuses foreign hosts, HTTP and redirects. A heartbeat validates the gate status/direction and checks the phone clock against server time. Suspended/removed/unauthorized or disconnected gates cannot create new confirmations.

Before sending, one pending event is encrypted and persisted. Network failures retry the identical event ID/body, never a new guessed mark. Other submissions pause until it is resolved. Matching replay replies are accepted as the original result. Refused events are shown as refused. Pending events older than 14 minutes expire for manual review; historical offline batch marking is not implied. Cancelling retry does not undo an event that the server may already have received.

The camera and retry polling stop in the background. A currently in-flight request may finish. No always-on/background monitoring or unattended deployment is claimed.

## Build and validation

Use Java 17, Gradle 8.9, Android SDK 35 and Android Gradle Plugin 8.7.3:

```sh
python3 download_models.py
gradle :app:testDebugUnitTest :app:lintDebug :app:assembleDebug
gradle :app:connectedDebugAndroidTest
```

The first command downloads only official OpenCV Zoo model assets at immutable commit 48b10fa505aeb51fbd127fc60a5c660040e823b7 and verifies exact hashes/sizes. Models are not checked into this repository. Build/test dependencies and GitHub Actions are pinned to explicit versions or commit SHAs. CI uses standard public GitHub-hosted Linux runners, no paid cloud recognition provider, no user credentials, and synthetic/fictional tests.

The workflow checks the complete backend suite and native identity-binding contract, compiles Android, runs pure matching/endpoint tests, lints, and runs Android-emulator tests of real native model execution, encrypted storage round trips, tamper failure, scope changes, and backup/cleartext restrictions. The synthetic native-inference check is not a human face-accuracy or liveness test. After a successful main-branch build, a prerelease provides the APK, checksum, source commit and model provenance.

Before real use: physical ARM64 camera/inference/recognition tests, representative consented user validation, false-accept/false-reject review, meaningful anti-spoof/liveness controls where required, production signing under the software owner's key, private-institute provisioning, durable production storage and operational/security review are still needed. Standard fingerprint readers require their own verified adapter; the Android device-unlock biometric is not a student fingerprint recognition feature.
