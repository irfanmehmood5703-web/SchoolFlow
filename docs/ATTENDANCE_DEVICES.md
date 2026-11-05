# Attendance devices and QR scanning (v31)

## What is implemented

Configuration → QR Biometric Attendance manages registered biometric serials, live heartbeat state, student/staff notification preferences, explicit late/absent minute limits, selected campus/class auto-absence, staff missing-IN/missing-OUT rules and optional early-departure Short Leave. Rules use saved student/staff shifts and the holiday calendar; they preserve manual attendance, approved leave/off statuses and HRM attendance locks. Overnight shifts are refused for automated marking and require manual attendance. No holiday, unconfigured shift or untouched class is assumed to be absent.

Configuration → Face Attendance Gates manages gate names, direction, Pending/Approved/Suspended status, one-time device credentials and removal with retained history. Pending and Approved both accept authenticated marks; Suspended stops them without discarding history. First seen and Last seen reflect actual authenticated contacts. Last marked reflects only an event that changed attendance. Registration alone does not make a device live. A removed device loses its credential but its gate/scan history stays available.

Which gate marked whom supplies inclusive Pakistan-date filters, gate and row limits, a name search over loaded rows, and a server query for one selected student/staff identity. Results distinguish Marked, Already marked and Not marked, with a reason. Scoped staff cannot read other-campus gates or scans. Device administration requires institute-wide Core Settings rights; viewing scan history/scanner uses attendance view permission.

Open QR scanner supports a browser camera when its QR detection API is available, plus USB scanner/pasted token input. It reads the existing SchoolFlow signed student/employee QR codes. QR camera frames stay local and no camera image is uploaded. The key is kept only in the current page, never saved to local storage or a URL. Explicit IN/OUT prevents a repeated scan from changing an arrival into a departure. Browser/hardware camera behavior still requires physical verification.

## Physical integrations that remain external

The server does not perform face recognition, take biometric templates, connect an EDUBase tablet, or speak an unspecified fingerprint terminal protocol. A compatible trusted client must recognize a person and send a SchoolFlow identity event. Device type/name is not evidence that a face was actually recognized. A vendor adapter must map that device's own identifiers to the correct SchoolFlow student/staff ID. No face image, fingerprint template or confidence payload is accepted or stored by this interface. A real tablet/reader/recognition client must be connected and tested before claiming physical biometric attendance works.

Android SMS, branded SMS, WhatsApp and Teacher App notification choices create queued requests marked Provider not configured; this release sends no message and does not connect the mobile apps. Free sleeping hosting cannot guarantee clock-time automation.

## Private institute setup

1. Back up the private database and run the existing explicit `flask --app app institute-upgrade` operator procedure. New additive tables are `attendance_device`, `attendance_device_scan`, and `attendance_device_mark`; no destructive migration is performed.
2. Configure active campus/classes and real student/staff shifts. Save attendance rules. Auto-absence starts only for selected classes/enabled staff rules; it checks today only.
3. Register a biometric serial or face gate. Open Connect and confirm issuing its connection key. The plaintext key is displayed once; only a SHA-256 digest is stored. A new key immediately revokes the old one. Keep it private and out of repository files, screenshots and URLs.
4. Supply the institute code, numeric SchoolFlow device ID and key to the QR scanner or compatible integration. Each device is bound to one campus. These credentials do not provide a roster-read API or owner/staff web access.
5. Verify real heartbeat, IN, repeated IN, OUT, suspension and a cross-campus refusal with fictional identities before use. Pending requires no approval; set Suspended to pause marking. Removed devices retain history and cannot be reactivated by merely changing their status.

## Device protocol

Use HTTPS. All requests are JSON, at most 8 KiB, and require:

- `X-Institute-Code`: the private institute's code.
- `Authorization`: `Bearer <device connection key>`.

Do not transmit credentials in query strings. Web session cookies and CSRF tokens do not substitute for a device credential.

`POST /api/attendance/devices/<device_id>/heartbeat` accepts only optional `model` (80 characters) and `client_version` (40 characters). It returns device status, configured marking direction and server UTC time. Heartbeats update contact time even when suspended; they do not create attendance or update Last marked. Contact within two minutes is labeled live.

`POST /api/attendance/devices/<device_id>/events` accepts:

```json
{
  "event_id": "unique-client-event-identifier",
  "person_kind": "student",
  "person_id": 123,
  "direction": "in",
  "occurred_at": "2026-11-05T08:30:00+05:00"
}
```

The numbers above illustrate the schema, not an existing person. `person_kind` is `student` or `staff`; `direction` is `in` or `out`. Alternatively supply `qr_token` containing an existing `schoolflow:student:<signed token>` or `schoolflow:employee:<signed token>`, omitting both identity fields. QR validation uses the private institute namespace and the registered device's campus. Unknown, foreign or inactive people produce the same unavailable-person result without exposing their names/IDs. No QR token or raw event payload is stored; a fingerprint is retained for idempotency.

Use an 8–100 character event ID containing letters, digits, hyphens or underscores. Reuse the exact event ID and body when retrying an uncertain response. A matching replay returns the original outcome without another attendance change, scan log or notification; a changed body using an old event ID returns 409. Authentication/revocation is checked before a replay can be returned. New events are capped at 600 per minute per device.

Times must include a timezone, be from today's Pakistan date, no more than 15 minutes old and no more than one minute ahead. No offline/backdated bulk import is implied. A stale or refused validly formed event is recorded as Not marked. Invalid schema is 422, bad/revoked credentials are 401, oversized JSON is 413, and rate limits are 429. A missing private schema returns 503. Successful new logs return 201 with `id`, `outcome`, `reason`, and `replayed: false`; identical retries return 200 with `replayed: true`.

The institute write gate serializes event claims, manual attendance, configuration, auto-absence and suspension. One Daily row exists per kind/person/day. Device-origin IN/OUT state and scans retain full timestamps; existing attendance times remain HH:MM for existing reports/payroll. First IN is Present or Late according to the saved shift start plus the late threshold. A selected auto-Absent may be corrected to a real arrival; existing manual attendance remains protected. OUT needs a device IN, cannot precede it, and is recorded once. Optional early OUT creates staff Short Leave; an actual late OUT can correct a missing-OUT Short Leave back to its saved IN status. Generated historical payroll is not recalculated.

## Automatic checks

The existing opt-in `SCHOOLFLOW_FINE_WORKER=1` process now checks enabled attendance rules too. No additional paid worker is created. Attendance checks run once per 15-minute bucket from 06:00 through 20:59 Asia/Karachi while the process is awake. Multiple workers/restarts remain repeat safe through the shared database gate and saved bucket; configured rules or explicit manual checks may rerun a bucket without duplicating marks. No previous date is backfilled.

An operator can run `flask --app app attendance-tick --code <PRIVATE-CODE>` or use Run today's attendance check. Both use current saved settings, shifts, holidays and lock rules. Tick code preloads shifts, holiday rows and current marks; notification snapshots are batched. All validation so far uses fictional isolated school databases; physical reader/recognition/camera verification and durable production hosting remain separate tasks.

## Native gate identity enrollment (v32)

The Android SchoolFlow Gate test client performs local attended face recognition. It verifies enrollment by presenting an existing signed SchoolFlow identity QR to the new authenticated endpoint:

`POST /api/attendance/devices/<device_id>/identity` with `{"qr_token":"schoolflow:student:<signed token>"}`.

An available, active same-campus identity returns only that person's `person_kind`, `person_id`, `name`, `scope_id` and opaque `identity_binding`. Unknown/foreign QR codes return generic 404 and suspended gates cannot enroll. Possession of a device credential alone does not supply a bulk roster or typed-ID lookup. No face image or feature vector is accepted.

Heartbeats now include an opaque `scope_id` derived from the private institute incarnation and gate/campus. Native clients pin it and send `X-Device-Scope` on identity/event requests. A changed scope returns 409 before a scan/mark is written. A new school database using an old institute code or gate number cannot silently inherit old local enrollment. Heartbeat discovery omits the scope header so a legitimately reconnected client can learn that its previous enrollment must be invalidated.

The native client includes `qr_token` and `identity_binding` in each face-derived event, omitting typed identity fields. A binding belongs to the actual current student/employee entity, not just the numeric ID or editable number. New additive table `attendance_identity_binding` has unique nullable student/employee foreign keys, an exactly-one-owner constraint and database ON DELETE CASCADE. A deleted/recreated person receives a new random binding even if ID/admission number are reused. An old binding cannot mark the new person. Returned identity values are captured under the write gate before commit, avoiding a response refresh onto a later recycled row.

Existing QR-scanner/adapter event payloads remain compatible; new native clients always send the stronger scope/binding fields. A bearer device key is still a trusted client capability and must be protected/revoked if compromised; this protocol does not attest that a camera actually recognized a live person. Existing private databases need the explicit operator schema upgrade for the new binding table. The native app remains an attended, debug-signed test client with physical accuracy/liveness/ARM64 camera testing and production signing outstanding.
