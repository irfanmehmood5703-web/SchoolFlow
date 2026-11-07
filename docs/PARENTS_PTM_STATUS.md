# Parents App and PTM web checkpoint — 7 November 2026

Later milestone: [APP_LINKS_WIDGETS_STATUS.md](APP_LINKS_WIDGETS_STATUS.md)
records the App Links registry and full 37-card widget workspace. References
below to those items remaining apply to this earlier checkpoint only.

This completes the next web implementation milestone after Notice Board and
Student Diary. It is not a claim that four native Android apps, SIM delivery,
every EDUBase module, or production security certification are complete.

## Menu and pages

General > **Student Extras** retains this order:
Parents App, Notice Board, PTM (Parent Teacher Meeting), Student Diary.
All four entries now lead to functional SchoolFlow pages.

Parents App has Analytics, OTP Portal, Login Links and Privileges. Analytics
uses actual parent web sign-ins, not enrolment as a proxy. It has configured
campus/class/section, contact/name/SID search, login/date filters, 25/50/100
entries, selected-column Excel and browser print/PDF. Invitations record
communication intent with Provider not configured; nothing is actually sent.

OTP Portal includes Live Requests, OTP by Contact, Not Installed and Active vs
Inactive. Not Installed is explicitly labelled as installation unverified:
a missing sign-in is not proof an Android app is absent. Live requests refresh
every 15 seconds and cover two hours. Codes last ten minutes, are single use,
and lock after five failed attempts. Staff code views/reveals are audited;
codes are encrypted at rest and excluded from analytics exports.

Private family-bound login links/printable QR work for a family's first login,
without the reference vendor's empty-children defect. A new link supersedes an
old unused link; cancellation and expiry are enforced. Links keep their secret
in a URL fragment, remove it from the address bar client-side and redeem only
on an explicit POST. Parent sign-in clears staff/owner identity in that browser.
The school can revoke all existing parent sessions and unused credentials.

Parent access rules have Allow/Warn/Block at 1/2/3+ distinct overdue challan
months (highest configured reached restriction persists; Allow removes a rule),
campus scope, student overrides, staff-only notes, expiry and clearing.
Fee Details, Pickup pass and Help remain accessible. Campus restrictions extend
all-campus rules; individual Always allow is the explicit exception.
Student 360 is a reference privilege row only and stays out of the main menu.

The responsive Parent Web Portal reads the same tenant database. Family-bound
children, fee balances, attendance, published notices, diary, basic profile and
office/help pages are available. Notice attachments enforce family/student,
campus, class, publication dates and effective access. Actual unique notice
views feed Viewed By; outbound delivery remains Not connected. Other parent
features without published content say so instead of fabricating records.

PTM includes events, create meeting, meetings and reports. Events have title,
campus, From/To and notes. Meetings link an active student/employee to an event,
date/time and notes. Exact teacher/student slot conflicts are prevented
atomically. Cancelled meetings release their slots; reactivation checks
availability. Attendance/feedback updates use optimistic versions, with real
counts, event/campus/date/status filters, Excel and browser print/PDF.
The inner PTM reference forms were not supplied; these fields are a working
baseline selected to complete the workflow, not a claim of exact unseen parity.

## Security and boundaries

- Separate institute database namespaces; public parent requests resolve their
  explicit institute and family session, never a posted owner/student identity.
- Parent sessions expire in eight hours and check a revocable database version.
  Parent cookies cannot open staff workspace routes.
- Public code requests use a generic response, no public code reveal, contact
  ambiguity fails closed, and per-institute IP/contact rate limits apply.
- Every public redemption holds the institute write gate, preventing concurrent
  replay. CSRF, expiry, replacement, attempt limits and one-use checks apply.
- Parent admin needs full-campus grants to avoid exposing partial families.
  Sensitive codes/link/QR actions require a separate parents.codes permission.
  Parent exports, updates and PTM create/update/export have distinct grants.
- Staff notes and raw credentials are excluded from parent content/exports.
  Public parent responses are no-store with no-referrer.
- Core school settings, fee/payroll math, main deployment and paid resources
  are not changed. No actual SMS/WhatsApp/native notification is sent.
- This is tested application behavior, not a blanket security guarantee.
  Load/security audit, backup restore drills and native clients remain work.

## Verification

- Sixteen targeted parent/PTM tests passed: first-use family binding,
  cross-family and cross-institute denial, encrypted/audited code, one use,
  replacement/cancel/expiry, failed-attempt lock, rate limit, session revoke,
  fee restrictions and non-blockable routes, private notes, overrides,
  selected exports, notice attachments/view counts and PTM scheduling/reports.
- Twenty-eight Chromium checks passed: 12 administration pages at 390/1366
  widths plus real first-use parent login, fee-rule enforcement, override
  privacy, and event > meeting > attendance > report. No JavaScript errors or
  body overflow. Populated parent mobile and PTM screenshots were inspected.
- Full regression: 631 tests passed. A final rule-threshold correction was
  then verified by all 16 targeted parent/PTM tests, including the new test
  proving that Allow removes a higher rule while a lower restriction persists.
  Hosted verification is recorded after deployment below.

## Hosted verification

Testing service https://schoolflow-gate-trial-irfan.onrender.com/ is live on
commit `2f13ce937cbed4aea85200d51f9350c52bab53a2`, deploy
`dep-dbnee7bm8hqs73c044gg` (live 7 November 2026, 08:55 UTC).
All 12 hosted checks passed, including all 13 page/tab GETs, a new fictional
family/student through the normal validated record form, first-use parent link
binding, fee access, session persistence, replay rejection, OTP request/audited
reveal/sign-in on PostgreSQL, session revoke, event/meeting/attendance/feedback,
filtered Excel and PTM report persistence across a fresh owner session.
A read-only database diagnostic independently confirmed the fictional family,
parent account and two redeemed credentials during verification. No credentials
or raw codes were added to source, reports or logs. Only fictional trial data
and demo dropdown choices were added to the isolated testing institute; no
external messages were sent and no paid resources or main-branch rollout
were used. Native clients, actual message delivery and the wider widget/release
registry work remain separate from this web milestone.
