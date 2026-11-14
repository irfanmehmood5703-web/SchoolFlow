# Internal Messages — reference implementation

The header **Messages** link opens `/workspace/conversations`. The existing
`/workspace/messages` SMS Blaster/fee-intimation workflow is preserved.

## Conversations and identity

- Searchable recent conversation list, unread counts, participant-only thread,
  subject/body, replies, resolve/reopen, manual message flags and severity.
- New conversation offers Staff/Admin, Owner, Teacher, Parent and Student.
  Recipients come from the current school's real active records. Teachers/staff
  need an active employee-linked staff login with Messages view access to the
  chosen campus. They need create/update permissions for the corresponding
  actions. Teacher-to-family starts require a saved class/section assignment.
- Parent conversations use the existing verified family login under
  `/parents/<code>/messages`. Family/child ownership, active enrolment,
  account-version/expiry and the existing Messages feature privileges apply.
- There is no independent Student sign-in in the current product. A Student
  conversation is explicitly labelled student-linked and read/replied to by the
  verified family account. Its Student role-pair policy still applies.
- Participant identity comes from the authenticated session. Requests cannot
  select a sender. Another owner, family or staff member cannot open a thread
  merely by knowing its ID. Reports have distinct, explicit campus permissions.
- Exact retries are actor/payload/file bound and create one message. Changed
  retries fail. School write locking, optimistic versions and atomic commits
  prevent partial attachments and duplicate submissions. Rate limits apply to
  successful sends (30/minute, 500/day/account).

## Settings

Institute-wide management controls on/off, role pairs, parent initiation,
individual staff disable switches, file types/size, voice-note length,
attachment availability, contact handling, follow-up hours and flag notices.
Messaging off keeps history readable; a disabled staff account cannot read or
write Messages. Independent student initiation is unavailable and cannot be
silently enabled. Staff settings need management access to every campus.

Contact handling offers Warn and flag, Block, and Hide. Text detection recognises
common phones, emails, URLs/social handles and Urdu/Arabic digits. Hidden details
are redacted in saved message text. Blocked messages/files are not served to
recipients; authorised reports retain an audit copy. This detector is a review
aid, not a guarantee against deliberate obfuscation. Images, PDF contents,
filenames and spoken audio are not scanned for contact details.

Flag notices appear internally for managers when enabled. High-severity flags
record a pending support-escalation workflow, with IDs/metadata only. External
support delivery is not connected. No SMS, WhatsApp or native push is sent.

## Media

Photos (JPG/PNG/WebP/GIF), PDFs and MP3/M4A/OGG/WAV/WEBM audio are supported when
enabled. Content/type signatures and image structure are checked. Audio is
independently decoded with the bundled FFmpeg binary, bounded by time/output,
without trusting a client-reported duration. Audio uploads allow at most fifteen
minutes; voice notes use the configured maximum. No video uploads are offered.

Browser microphone recording produces a 16 kHz mono PCM WAV, requires permission,
stops at the selected duration and stops when the tab becomes hidden. Audio
stays in the page until Send. It can be previewed or removed before submission.
Five files and 20 MB combined are allowed per message; each file also observes
the configured 1–20 MB limit. Message read receipts use the displayed message
IDs and do not move backwards. They indicate an in-app read acknowledgement,
not proof of push delivery or human comprehension.

Attachments use authenticated participant routes with MIME/nosniff/sandbox
headers and protected streaming/download. Availability can be unlimited (0) or
30–3650 days. Expiry prevents access but does not delete the message or silently
purge the stored file bytes; storage cleanup remains a separate operational
policy. Transcript exports contain text/metadata rather than attachment bytes.

## Reports and help

Overview, Conversations, Flagged and Response times use recorded message/read
states. Filters include conversation creation dates, permitted campus, status
and subject/message text. Reply metrics measure school replies following family
messages. Unresolved age starts at the oldest unanswered family message, so a
new reminder does not reset it. First-responder groups use account identity,
not potentially duplicate display names. Blocked messages do not count as
unread or replies.

Summary and full transcript exports are XLSX. Transcript export requires an
explicit confirmation and an export permission; each exported conversation is
audited. Cell text is forced to spreadsheet strings, including formula-like
message text. The Flagged tab exports only flagged conversations in the current
filter. Reports are bounded to 500 conversations / 20,000 messages; narrower
filters are required beyond that. Message/state queries are batched rather than
one query per report row.

How To now has three Communication guides for inbox, settings and reports:
103 guides for private owners, 100 in demo/staff help catalogues.

## Deployment and checks

New tables only: conversation_policy, conversation, conversation_message,
conversation_file, conversation_seen, conversation_submission, conversation_rate.
Existing private workspaces use the established additive upgrade path. No
existing data, secrets, signing keys or database URLs are replaced. Attachment
bytes use the same tenant database storage model as existing Diary files.
`imageio-ffmpeg==0.6.0` supplies the validation binary through its platform wheel.

Tests exercise real school/teacher/family logins, another school/family/campus,
revoked sessions and fee privilege, role and account switches, contact modes,
blocked file privacy, exact/changed/concurrent retries, invalid uploads, decoded
voice duration, retention expiry, settings versions, audited/formula-safe
exports, read state, resolve/flags and response timing. Chromium CI exercises
390px/1440px forms, actual recipients, PDF/reply, fake-microphone WAV capture,
report search/download and the existing How To/Diary/PTM workflows. Fake-device
Chromium is not a physical Android microphone or APK installation test.
