# Student Diary and PTM reference forms

Reference: five user-supplied screenshots on 13 November 2026. Implementation keeps SchoolFlow's original interface and top navigation.

## Student Diary

- Campus/class-dependent sections and searchable multiple subjects. Each subject has independent Classwork and Homework editors, Bold/Italic and separate files.
- One durable diary entry per selected subject; existing single-description diaries remain readable. Subjects, class mappings and section membership are validated server-side.
- Sanitized formatting permits only text, paragraphs, line breaks, bold and italic. Each work part accepts up to five verified JPG/PNG/WebP/PDF/MP3/MP4 files; the whole submission accepts twenty files and 15 MB, 5 MB per file.
- Atomic save, actor-bound retry protection and content/file fingerprints prevent partial batches or changed retry payloads.
- Parent views use the child's family, class, section, explicit enrolled subjects and fee access rules. Attachments receive the same checks; file names/content are never executable in the portal.
- Save/Save and Send retains channel, contacts and notification intent. This change does not connect an SMS/push provider or claim delivery.

## PTM

- Events add term, academic year, optional feedback opening/closing times, parent notification preference, voice-note preference and notes. Event names are unique within a campus/year; reuse in another campus/year is allowed. Preferences are visible after saving.
- Voice-note preference and feedback windows are stored configuration. This release does **not** implement recording/upload/playback, automatic event publication notifications or a new parent-feedback endpoint.
- Create PTM supports campus, class, multiple sessions and sections, active student checkboxes, optional assigned teachers, date, optional event, exam filters/subjects and notes. Standalone meetings need no event. Up to 500 active students per batch.
- All selected students and active teachers are revalidated inside the institute write transaction. No teachers assigned means no Teacher-role staff account sees that batch. Manager access still requires normal PTM action/campus grants.
- Optional exam marks are immutable snapshots from SchoolFlow's canonical result calculation, filtered by student, subject, type and dates. Staff also need exam-view access. Empty filters copy no marks.
- Class meeting attendance/feedback has optimistic version checks and appears alongside legacy appointments in meeting/report pages and Excel export. Legacy meeting creation APIs and existing saved records remain supported.
- New tables only: diary_submission, ptm_event_config, ptm_group, ptm_evaluation. No deployed table gains a required column; existing private school schemas use the established additive upgrade path.

## Verification

Focused tests cover multi-subject formatting/files, atomic rejection, exact/changed retries, class mappings, parent file/family/fee checks, event preferences/name scope, roster validation, report/export, immutable marks and assigned-teacher access. Existing parent/legacy-diary/PTM tests remain in the full suite.

Local browser execution could not run: Chromium's process socket is prohibited in this execution environment. JavaScript syntax checks and HTTP/template/form regression tests are used; no physical Android/browser visual testing is claimed.

Release checks and hosted QA results are appended after deployment.
