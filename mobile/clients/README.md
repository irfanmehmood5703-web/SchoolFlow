# SchoolFlow Android clients — test release

Four installable Android clients connect to the original SchoolFlow host and
its existing institute databases. No records, passwords, device keys or signing
secrets are bundled. These do not replace the separate attended Face Gate app.

Parents, Teacher and Owner are Android **portal clients**, using the actual
existing web workflows inside a restricted HTTPS WebView. They are not a
complete native rewrite, offline client or push-notification implementation.
The parent app uses family-bound OTP access; staff permissions and campus
restrictions are enforced by the server, not by choosing an app flavour.
Owner/Teacher accounts use Institute Code then username/password. The parent
login code is currently handed over by the verified school office; it is not
silently sent by the school-SIM outbox.

Portal clients provide Android file selection, save exports to the user-selected
location, printing, back/reload and local session clearing. File/content URL
loading, cleartext, third-party cookies, WebView permission grants, native
JavaScript bridges and foreign-origin navigation are blocked. TLS errors stop
navigation. Backup is disabled and screenshots are protected. Download requests
carry the current same-origin session cookie without following redirects.

## School SIM sender

1. Owner opens App Links → Connect school SIM SMS, chooses a campus and registers
   the school phone. A private connection key is shown once.
2. Install the SMS test APK on a school-owned Android 8+ phone with an active SIM.
   Enter Institute Code, phone ID and connection key. Enable SMS/phone-state
   permission and select the intended school SIM.
3. Save an App SMS communication request in the web portal. On Communication
   Requests, choose Review for school SIM. Preview exact saved texts, recipients
   and phone campus, then explicitly approve the SIM charges. Other channels
   (WhatsApp, branded SMS and push) are not converted to SIM sends.
4. Tap Review next queued SMS on the phone, read the recipient/text, then confirm
   Send once. Multipart messages display the part count before confirmation.
5. Upload the phone result to the outbox. This request never sends another SMS.

A server-side dispatch starts only once. A claimed but not-started lease may
expire; a started/unknown message is never automatically re-queued. A duplicate
result is idempotent. Pending state and connection credentials are encrypted
with an Android Keystore key in backup-excluded private storage. The phone
persists uncertainty *before* requesting dispatch; a lost network response or
process restart cannot trigger an automatic resend. Multipart errors are
reported as unknown because some parts may already have been sent.

A “sent” result means Android reported successful submission to its network,
not verified recipient delivery or a remaining SIM balance. Uncertain sends
require checking phone history and the outbox. No unattended/background sender,
queue backfill or automatic sending of old requests is enabled. Key rotation
invalidates the old device connection and leaves old queued jobs for explicit
owner cancellation/review; it does not transfer them to a new phone.

Android/Google Play may restrict SMS permission distribution. This project
provides **sideloadable, debug-signed test APKs**, not a published Play Store or
production-signed release. Only the SMS flavour requests SEND_SMS and
READ_PHONE_STATE. Portal flavours do not require SMS permissions.

## Build

Java17, Gradle8.9, Android SDK35, AGP8.7.3:

    gradle --no-daemon :app:testParentsDebugUnitTest :app:lintParentsDebug :app:assembleParentsDebug :app:testTeacherDebugUnitTest :app:lintTeacherDebug :app:assembleTeacherDebug :app:testOwnerDebugUnitTest :app:lintOwnerDebug :app:assembleOwnerDebug :app:testSmsDebugUnitTest :app:lintSmsDebug :app:assembleSmsDebug

CI tests all four flavours, packages APKs with source SHA/checksums, and publishes
a prerelease only after backend and Android checks pass on main. Each build uses
the runner's debug signing key; installing a later test build may require
uninstalling a prior one (which clears sessions/local SMS state). Review pending
SMS before uninstalling. Production signing must use the software owner's
protected key, never a key generated into source or chat.

Physical phone camera/file chooser/printing tests, consented real-SIM delivery,
network-loss/restart trials and production signing remain operator/device
verification steps; a compile or synthetic test is not proof of these outcomes.

## Portal microphone and acceptance packages

Parents, Teacher and Owner portal clients declare audio-recording permission. A foreground SchoolFlow page may request audio capture only from the exact original HTTPS origin; foreign origins, camera/mixed resources, background/cancelled requests and denied OS permission are refused. App pause stops/prepares an in-progress voice note for explicit review; it never sends a recording. Finished voice previews remain usable on return. Android permission timing may require pressing Record again after the first grant. Physical WebView/microphone checks remain necessary. SMS does not declare or request microphone permission.

Default downloadable acceptance packages use a separate `.acceptance` suffix and can coexist with earlier `.test` packages. Existing school-specific builds keep their debug/signing path. Do not erase an old SMS app’s uncertain pending submission just to install a new test app; review server/phone state first. Test packages are not production-signed releases.
