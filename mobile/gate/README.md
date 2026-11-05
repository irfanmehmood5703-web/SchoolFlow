# SchoolFlow Gate — Android attended test app

Native face-attendance companion for SchoolFlow's existing private-institute Face Attendance Gates. This is separate from the planned Teacher, Parent, SMS and Owner apps.

## Test installation

Download **SchoolFlow-Gate-test.apk** from this repository's latest **SchoolFlow Gate test** prerelease. It is a debug-signed test build for fictional identities, not a Play Store or production-signed app. Supported build targets are ARM64 Android 8.0+ and x86_64 for automated emulator tests. Actual camera/device compatibility is still subject to physical testing.

1. Set a PIN, password or pattern on the school device. Install the test APK and grant camera permission.
2. In the SchoolFlow web portal, register a face gate for the correct private school/campus, then use Connect to issue its connection key. In the Android app choose Connection, unlock the device, and enter the private institute code, numeric gate ID and key. DEMO cannot connect. The server address is fixed to https://schoolflow-phase1.onrender.com in this test release.
3. Verify a fictional person's student/staff ID in the portal. Choose Enroll face, unlock the device, enter that ID/name and attest that the identity and permission to enroll are verified. Capture three samples of the same person.
4. Start the camera, select IN or OUT, and show one enrolled person. Matching must be stable and unambiguous. The operator verifies the person and explicitly confirms the mark. Check the web scan history for the actual server result.
5. Test suspension, foreign-campus refusal, repeated IN/OUT, loss of connectivity and key rotation before considering any operational use.

Settings and enrollment require the device's own screen-lock credential. Local templates can be deleted in Manage faces. Changing institute or gate explicitly clears local enrollment and pending submission after confirmation. This does not erase attendance already saved by the server. Do not share a tablet screen-lock credential or connection key with unauthorized people.

## Recognition and privacy

- OpenCV 4.12.0 with official pinned YuNet 2023mar and SFace 2021dec model files performs actual native inference locally. Build and startup verify SHA-256 hashes. License texts ship in the APK's assets.
- Enrollment stores three feature vectors per identity, never a saved camera photograph. AES-GCM uses an Android Keystore key, an app-private backup-excluded file, cloud backup disabled, and protected screens.
- The app sends only the existing person kind/ID, explicit direction, event ID and timestamp to the authenticated device API. No face picture or vector is uploaded.
- Unknown, poor/small/multiple or ambiguous faces are refused. Matching uses a conservative 0.55 cosine threshold with 0.08 margin and repeated stable frames. These are starting parameters, not an accuracy guarantee.
- This app does **not** claim certified liveness or anti-photo-spoofing. It is attended: recognizing a face alone never silently marks attendance. A human verifies the person before confirmation.
- The app does not automatically import school photos or enroll identities from the central roster. An authorized administrator must verify the displayed SchoolFlow ID against the actual person during enrollment.
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

The workflow compiles, runs pure matching/endpoint tests, lints, and runs Android-emulator tests of real native model execution, encrypted storage round trips, tamper failure, scope changes, and backup/cleartext restrictions. The synthetic native-inference check is not a human face-accuracy or liveness test. After a successful main-branch build, a prerelease provides the APK, checksum, source commit and model provenance.

Before real use: physical ARM64 camera/inference/recognition tests, representative consented user validation, false-accept/false-reject review, meaningful anti-spoof/liveness controls where required, production signing under the software owner's key, private-institute provisioning, durable production storage and operational/security review are still needed. Standard fingerprint readers require their own verified adapter; the Android device-unlock biometric is not a student fingerprint recognition feature.
