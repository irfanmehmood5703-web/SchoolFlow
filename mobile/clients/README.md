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
loading, cleartext, third-party cookies, unreviewed WebView permission grants, native
JavaScript bridges and foreign-origin WebView navigation are blocked. User-tapped
HTTPS, telephone and email links can open in another app after confirmation;
no SchoolFlow session cookies are passed to those apps. TLS errors stop
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
4. Tap **Send Messages** on the phone. Choose the school SIM and a 15, 20 or
   25-second interval, then confirm the approved queue once. Default: 20 seconds.
   Keep the app open. Pause or leaving the app stops further dispatch.
5. Successful phone results upload automatically before the next message. If
   upload fails, use **Upload saved result**; this never resends an SMS. Manual
   single-message review remains available. Multipart messages use more than
   one SIM SMS credit, and recipient delivery is not verified.

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

## School-name installs and connected updates

General → App Links builds four APKs for each private school. Android displays
the school name followed by Parents, Teacher, Owner or SMS, with the school's
logo (or initials). A generic APK cannot rename its launcher after sign-in;
school-specific packages provide the actual installed name. Each school/role
has a separate immutable package and a retained private signing key so an
update installs over its previous school build. No pupil records are bundled.

Client source version 2 queues updates for previously built active schools
when the central worker next runs. The Prepare updated school apps button
also requests a new numbered build without changing the school's package/key.
Duplicate queued/building requests reuse the same job. Old workers cannot
claim new-version jobs. Brand/logo changes still require the school's chosen
branding to be prepared. Download status and SHA checksums are in App Links.

Branded portal entry validates the school code against its immutable identity.
A signed HttpOnly routing cookie keeps login, parent links and subsequent
workspace requests within that school; normal login permissions remain the
authority. Owner and Teacher builds accept their respective account types.
Home reuses a valid school session. Parents use the family-bound portal and
cannot open the staff workspace. The SMS client verifies the server's school
identity before saving its connection and retains the attended send-once flow.

Owner and Teacher use the current live web routes, navigation and settings,
including the latest inquiry, fee-plan, challan, partial-payment and reversal
flows when permitted. Parents use the existing family-visible fee, result,
attendance, diary, notice and messaging pages subject to school privileges.
These clients share server workflows rather than maintaining copies of forms.
Android alert, confirmation and text dialogs support web actions; page Print
buttons use the native print service after loading;
the toolbar scrolls on small screens and shows the installed school app name.


## Dedicated Teacher workspace

The Teacher client opens `/teacher-app`. An active Teacher staff account and
linked employee are required. HRM assigns campus/class/section/subject; Users &
Privileges grants each action. No permission is granted by installing an APK.
`attendance.own`, `payroll.self` and `hrm.self_requests` allow personal records
and pending requests without giving campus-wide HRM/payroll access. Separate
`teacher.leave_view` and `teacher.leave_approve` grants control student leave.

Teachers can change only assigned class attendance and paper marks. Unchanged
attendance and gate time-in/out remain intact. Today’s own diary is editable;
previous days are read-only. Published study resources, assignment reviews,
student leave responses and scheduled notices use the existing Parent records.
The school continues to control report publication. Scheduled notices appear
in Parent App notifications from the selected Pakistan time, provided the
teacher, grant and class assignment remain active. Personal reminders are
shown in-app; background push and offline alarms are not implemented.

Owner-issued Teacher QR links expire after ten minutes, are single-use and
are invalidated by new issuance or account revocation. Scan with a phone QR
camera or paste the school-issued link on the Teacher QR sign-in page. Username
remembrance never saves the password. Normal session expiry/revocation applies.

Only the Teacher flavour declares coarse/fine location permissions. A trusted
foreground page may request precise location for the existing self-attendance
geofence flow. Permission is not retained across navigations; pausing or leaving
the page denies pending requests. Android installation, real GPS accuracy,
precise-location permission denial and real campus check-in/out still require
physical-device acceptance. Do not create real attendance as part of CI.

### Teacher lecture reminders when the app is closed

The authenticated Teacher notification feed supplies dated lecture occurrences
for the next 48 hours, excluding holidays and inactive assignments. The
teacher client caches them privately and schedules the next alarm using
Android AlarmManager. Normal app closure does not cancel the alarm; it can
deliver a notification locally without contacting the server at alarm time.
The client restores the cache after reboot and refreshes it through normal
background jobs and foreground navigation. Logout clears the cached alarms.
Android 12+ needs the Alarms & reminders access for exact timing and Android
13+ needs notification permission; without exact access, timing is best
effort. Device force-stop and manufacturer battery restrictions can prevent or
delay delivery. Schedule changes become effective at the next successful
sync, and offline cache expires after 48 hours. This is not a push service.

### Native school opening screen
All school-branded Android apps show their locally packaged school logo and name
while connecting. Only a successful, marked SchoolFlow JSON health response
allows startup. Owner, Parent and Teacher WebViews remain covered until a
SchoolFlow document is actually rendered; upstream HTML, including a successful
HTTP 200 hosting wake-up page, is never accepted as a school page. Health
checks retry for a bounded 105 seconds with a manual retry on failure. Native
SMS/attendance tools may open their local screen after a connection timeout,
subject to their existing connection and permission rules. Automatic retries
never replay a business POST, SMS or new attendance action. Existing device
state, cookies and signed app identities are preserved.
