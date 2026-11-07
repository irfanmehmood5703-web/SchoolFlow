# Student Extras implementation checkpoint — 7 November 2026

## Implemented in this change

General top navigation now has the Student Extras section heading. The two
functional entries currently available are Notice Board and Student Diary.
The confirmed final order remains Parents App, Notice Board, PTM, Student Diary;
Parents App/PTM are not inserted as nonfunctional placeholders.

- Notice Board: real list and 25-row pagination, campus/date/search filters,
  title/description, From/To validation, All Students or configured class
  multi-selection, class search, campus selection and Clear Selection.
- Notice attachments: up to five JPG/PDF/MP3/MP4 files, 5 MB each/15 MB combined,
  stored as database binaries rather than ephemeral Render files. Type signature
  checks, forced-download disposition and authenticated, campus-scoped access.
- Student Diary: list with campus/class/section/subject/date/search filters;
  create date/campus/class/section/subject and plain-text diary body, channel,
  father/mother/student contacts, parent notification, Save and Save and Send SMS.
  Section/class and subject assignment are checked server-side. A class search
  filters the class picker. The body field is a useful implementation baseline;
  its exact reference editor after class selection has not been supplied yet.
- Durable, tenant-routed additive entry/attachment tables; audit on save; CSRF;
  unique submission tokens prevent duplicate refresh/double submission.
- Dedicated Student Extras view/create staff grants. Cross-campus records/files
  are restricted; limited staff cannot publish all-campus notices. Separate
  institute databases cannot read one another's notice or attachment IDs.

## Explicit limits

No parent app, SMS or WhatsApp delivery is connected by this change. Diary
message intent is saved with Provider not configured, never Sent. Notice
Delivered/Viewed columns show Not connected, not invented delivery counts.
No scheduled publishing consumer in a native app is claimed. Attachments are
stored, not malware-scanned. No real reference students, contacts, OTPs or
vendor apps are copied into SchoolFlow.

Parents App workflows, PTM, own App Links release registry and the remaining
widget expansion are still pending. PTM create/event forms and diary editor
reference after class/subject selection remain useful follow-up screenshots.
This checkpoint is not a claim that General or the four native apps are complete.

## Validation

- Full regression attempt: 613 tests, 612 passed; the only failure was the old
  menu-count assertion expecting four modules. Updated to include General;
  all 14 operation tests then passed, including every menu destination.
- All 8 Student Extras tests passed, including private-institute isolation,
  attachment download/rejection, duplicate saves and filtering.
- All 33 staff access tests passed, including the new Student Extras grant and
  cross-campus attachment restrictions.
- 11 Chromium checks: four pages at widths 390/1366, notice/class save, refresh
  persistence, diary save with accurate unavailable-delivery labels. No page
  JavaScript errors or body overflow; populated mobile diary and notice form
  screenshots visually inspected.
- No production/main merge, paid resource or external message send performed.

## Hosted verification

Testing service https://schoolflow-gate-trial-irfan.onrender.com/ is live on
commit 1603b54d33d2b099945e6e093308e2997adf6f67, deploy
`dep-dbndtftg1s2s73cef270` (live 7 November 2026, 08:19 UTC).
All 10 authenticated HTTP checks passed: four page/form GETs, notice plus binary
attachment save on the hosted PostgreSQL database, duplicate suppression,
authorized download, persistence across a fresh authenticated session and
anonymous attachment redirect to login. Only fictional QA data was added;
no external messages were sent. Initial post-live application error-log query
returned no errors; a subsequent request-log query was unavailable (503), so
that query is not treated as a clean log result.
