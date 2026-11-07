# General functional screenshots — 7 November 2026

## Confirmed scope and menu grouping

The user confirmed that the current reference collection reaches Student Diary.
Preserve the reference's section headings and item order in SchoolFlow's original
green/white/zinc interface and top navigation:

- General
  - SchoolFlow App Links (reference label: EDUBase App Links)
  - Widgets
  - **Student Extras** (section heading, not a separate page)
    - Parents App
    - Notice Board
    - PTM (Parent Teacher Meeting)
    - Student Diary

Do not flatten Student Extras into a list without its heading. Later menu entries
remain an inventory only until their active screens and scope are supplied.
Do not insert disabled reference items between these current active options.

This document captures 28 supplied screenshots, not completed implementation.
No real student/contact/code data from screenshots belongs in source or fixtures.

## App Links

Eight visible cards: Parents App, Teacher App, Admin, QR Attendance, Owner App,
SMS App, Face Attendance, WhatsApp Desktop Sender. Store/open/download and Copy
link actions vary by card. Use SchoolFlow-owned releases and links; vendor
versions/APKs are reference only. The widget says nine apps but only eight cards
are visible; do not invent a ninth or claim downloads exist.

## Widgets

Tabs: My dashboard, Widget library, Permissions. Dashboard has Customise,
Add widget, three-dot menus, Expand, Open report, period controls and contextual
empty-state actions. Library, Permissions and three-dot contents are not shown.

37 reference widgets:
- Admissions (7): Admission Queries; Active Students; Student Strength;
  Admission Capacity; New Admissions — 12 Months; Inactive Students — 12 Months;
  Student Strength Chart.
- Finance (14): Daily Income & Expenses; This Month Paid Amount; Fee Collection;
  Unpaid Challans; Un-paid Amount; Day Wise P & L; Fee Defaulters;
  Class Wise Fee Report; Month-wise Fee Chart; Average Tuition Fee Report;
  Month Wise Fee Report; Students by Discount Type; Particular Fee Report;
  Monthly Particular Wise Fee Report.
- Exam & Attendance (6): Absent Today by Class; Student Attendance Donut;
  Class-wise Result; Month-wise Result; Upcoming Exams; Result Performance Bands.
- HRM (4): Employee Status; Staff Attendance Chart; Employee Approvals;
  Staff on Leave.
- General (6): Birthdays; Mobile Apps; Complaints & Suggestions;
  Complaints & Suggestions Chart; platform Updates; SMS Balance & Sent.

All metrics must derive from actual tenant data. Do not copy reference values,
claim actual app adoption/SMS credits, or claim all 37 widgets are already built.

## Parents App

Subtabs: Analytics, OTP Portal, Login Link, Privileges.

### Analytics
Father/Mother/Student contact choices; Branded SMS, App SMS, WhatsApp SMS and
Parent App Notification; editable message, character count, Send SMS and row
Send app action. Active/Inactive summary, Last Used range, Login Status, Clear
Filters, global/per-column filters, entries, pagination, export-column selector,
Reload, gear, Excel, print and PDF.

Columns include SID, family/roll/student/guardian, campus/class/section, masked
OTP with Reveal/Expired/Send via WhatsApp, Send App Link, Login Status, Last Used,
guardian mobile. A shown permission toast specifically denies sensitive standing
parent code access without Core Settings > Users & Privileges permission. This
does not establish why every grey General option is disabled. Require tenant/
family scope, sensitive-code permission and reveal auditing; exclude clear codes
from normal exports/logs. App activity requires actual authentication telemetry.

### OTP Portal
Tabs: Live Requests, OTP by Contact, Not Installed, Active vs Inactive.
Only Live Requests is shown. Codes last ten minutes and work once. Live requests
cover the last 120 minutes, refresh every 15 seconds and show countdowns to
authorized staff. Counters: Waiting for parent, Signed in, Expired unused,
Replaced by newer code. Other tabs hide codes until Reveal; viewing is audited.
Implement scope, expiry, single use, replacement and rate limits before claiming
working login. Empty reference screens do not prove login delivery.

### Login Links
Search by student/father/SID/number, paginated family/student cards, App in use /
Never signed in, contact and issued-link state. Printable QR, Hand over link,
Cancel link. One-time links must bind the correct school/family/children.
The reference warns of first-login links opening an empty app: record this as a
vendor defect, not behavior to reproduce.

### Privileges
Automatic rules and Students tabs. Campus scope; 1/2/3 months pending bands,
highest reached band wins. Allow/Warn/Block; Allow removes a rule.
18 reference features: School Shop; Vacation quizzes; Notice Board; Messages &
Notifications; Attendance; Daily Diary; Academics & Marks; Exam Report Cards;
Date Sheet; Roll Number Slip; Fee Details; Leave Application; Complaints &
Suggestions; Teacher Talk; Student 360°; Student Profile; Pickup pass;
Get Help/Contact Us.
Fee Details, Pickup pass and Get Help/Contact Us remain reachable and cannot be
blocked in the shown manual form. Student 360° remains excluded from the main
menu by the earlier user decision; this screenshot does not reverse it.

Student filters: campus/class/section/show/search. Rows show months pending,
effective access and Manage. Modal: From rules, Parent sees, This student,
Note for staff, Until. Follow the rules and Always allow are described;
other manual choices are not visible. Staff-only notes, optional expiry,
Remove all manual settings, Close, Save changes. Native app enforcement is
separate work; server configuration alone does not prove it works.

## Notice Board
List: Add Notice; Title, Event/News Description, Display Duration, Targeted
Audiences, Delivered to, Viewed By, Attachment, Created At; pagination.
Add form: Title, Description, From/To, multiple JPG/PDF/MP3/MP4 attachments,
All Students, Clear Selection, All Campuses/configured campus dropdown,
searchable class multi-checkbox selection, Cancel, Save Notice.
Classes/campuses come from school setup. No section selector is shown.
Time granularity and edit/delete/read drilldowns are unverified.
Delivery/read counts require actual events; saving does not mean SMS sent.

## PTM
Tabs: PTM Event, Create PTM, PTM Meetings, PTM Reports.
Event page: Reports and New PTM Event; events group a term's meetings.
Meetings: empty No PTM found with Retry PTM reads.
Reports depend on events and held meetings. New Event/Create PTM forms and
populated meeting/report details are not shown; do not invent exact fields or
copy the reference read error as intended behavior.

## Student Diary
Record search: Campus, Class, Section, Subjects, From, To, Submit, Create Diary.
Create: Date, Campus, Class, Section, Subject; searchable configured class list.
Branded SMS/App SMS/WhatsApp SMS channel radios; Parents App Notification;
Father/Mother/Student contact choices.
Save Student Diary and Save and Send SMS are separate actions.
The diary content area after selecting class/subject is not shown yet.
Durable save and actual provider delivery must be distinguished. Screenshots
do not authorize sending messages to real people.

## Remaining reference gaps
Widget Library/Permissions, OTP tabs other than Live Requests, PTM event/create
forms and populated records/reports, diary contents after class/subject selection.
These gaps are not a claim that the current reference pages are implemented.
