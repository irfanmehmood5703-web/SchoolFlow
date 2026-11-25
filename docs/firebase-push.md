# Optional Firebase Cloud Messaging

SchoolFlow's background polling continues without Firebase. This integration
adds FCM data wake-ups for school-branded Parents, Owner, Teacher and SMS apps.
The server checks existing notification feeds once per enabled scheduler cycle;
Android fetches authorised details from SchoolFlow. Only opaque actor and event
digests are sent through FCM, not school records, balances, student names or
phone numbers. There are no shared topics. Portal push leases expire with the
existing eight-hour sign-in; a revoked account is rechecked before dispatch.
SMS device leases expire after seven days and are rechecked against registration
generation. Push delivery is best effort, not a guaranteed instant alert.

## Activation by platform operator

1. Create a Firebase project, enable the Cloud Messaging HTTP v1 API, and
   register each school's exact four Android package names:
   `com.schoolflow.schools.s<SCHOOL_SCOPE>.<parents|owner|teacher|sms>.test`.
   The existing school signing key and package names must remain unchanged.
2. In the trusted GitHub school app builder, set the secret
   `SCHOOLFLOW_FIREBASE_ANDROID_CONFIG_JSON` to a JSON object keyed by those
   exact package names. Each value contains `app_id` (mobilesdk_app_id),
   `sender_id` (project_number), `project_id`, and `api_key` (current_key)
   from the registered Android app's google-services.json. These are client
   identifiers, never service account keys. Example shape (replace placeholders):
   ```json
   {"com.schoolflow.schools.s<scope>.owner.test":{"app_id":"1:<number>:android:<id>","sender_id":"<number>","project_id":"<project>","api_key":"<android-api-key>"}}
   ```
3. On Render only, set `SCHOOLFLOW_FCM_SERVICE_ACCOUNT_JSON` to the
   service account JSON with the minimum FCM sending permission and set
   `SCHOOLFLOW_FCM_ENABLED=1`. Keep the JSON out of Git, logs, chats and APKs.
   Enable the existing `SCHOOLFLOW_FINE_WORKER=1` scheduler on a reliable
   continuously running host, or run the `flask firebase-push-tick` command
   from a reliable external scheduler. A sleeping host cannot dispatch.
4. Rebuild school APKs after Android config is present. Install the signed
   update, allow notifications, then sign in to the correct account.
   The client registers its FCM token through the existing authenticated
   feed. Without Google Play services or config, polling remains available.
5. Test all four roles with fictional records, including zero fee, approved
   leave, period reminder, SMS pending, logout/account change, denied
   notification permission, network reconnect and closed app. Check that
   FCM delivery never exposes school data on the lock screen or to another
   family/school. Check the new APK signatures before distribution.

FCM submission is not proof of receipt. Notification permission, internet,
Android power policies, force-stop and current session validity affect
delivery. A fully switched-off phone cannot display a live notification.
Do not claim real device delivery until the above tests pass. No external
network calls run in the regression tests.
