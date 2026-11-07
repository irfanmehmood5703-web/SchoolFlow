# App Links and Widgets — 7 November 2026

These two General options were omitted from the earlier Student Extras milestone.
They are now implemented as separate functional pages before Student Extras:

1. SchoolFlow App Links (the original-brand equivalent of EDUBase App Links)
2. Widgets
3. Student Extras: Parents App, Notice Board, PTM, Student Diary.

## App Links

Eight reference cards: Parents App, Teacher App, SchoolFlow Admin, QR Attendance
App, Owner App, SMS App, Face Attendance, WhatsApp Desktop Sender. The private
school's Parent Web Portal has a working separate link.

Each native release has a versioned form for public HTTPS URL, version, optional
size and release notes. Published URLs enable the actual open/download and Copy
link actions. Unpublished apps say so; no APK, download link, installation,
vendor version or app adoption is invented. Real native artifacts must still
be built/published before download links can be configured. Vendor APKs and
reference contact/student data are not reused. Source contains only fictional
test URLs, never a fake release published into the hosted registry.

Read access and editing have separate Apps permissions. Public demo visitors
cannot change shared release or role settings. Changing the release
registry needs every configured campus; stale writes and unsafe URL schemes,
embedded login credentials and fragments are rejected. No external fetch,
message send, new storage service or paid resource is performed by a save.

## Widgets

The full reference catalogue has 37 cards:
Admissions 7; Finance 14; Exam & Attendance 6; HRM 4; General 6.

My dashboard, Widget library and Permissions are functional. Personal selection,
group/card order, 1/2/3-column layout, Simple Dashboard, default-dashboard
selection, Add widget, Customise, Expand/Collapse and source reports are wired.
Preferences persist per institute and owner/staff account. Anonymous demo changes
stay in the browser session. The previous 14-card dashboard remains available
until the user explicitly chooses the 37-card page as their default.

Every card opens a real, dated, paginated source report with Excel and browser
print/PDF. Charts and source rows derive from actual records. The attendance
card has an SVG donut, counts and an unmarked bucket; unmarked is not absent.
Missing data is described rather than replaced with screenshots' numbers.

Permissions combine widget role visibility, campus scope and underlying source
module grants. Finance accounting retains the existing all-campus access
requirement. Export and role-management rights are distinct. Partial campus
staff cannot change global release or role settings. The previous dashboard
also applies these role/source restrictions, so it does not bypass hidden cards.
Campus catalogue reads are cached only within an individual GET request;
mutations re-read permissions inside their existing lock.

## Calculations and deliberate limits

- Student counts use Active status; admission/leaving trends use saved dates.
  Missing leaving dates are not manufactured from an updated timestamp.
- Paid Amount always uses this month's non-voided receipt dates. Fee Collection
  uses current paid balances on selected bill months. Outstanding values are
  current balances, not reconstructed historical snapshots.
- Month-wise fee cards show current calendar year-to-date bill-month totals.
  Overdue means positive remaining balance and an actual due date before today.
- P&L uses posted journal lines and captured Income/Expense classifications,
  including offsetting reversals. Unposted cash receipts are not silently
  treated as ledger income.
- Average tuition uses actual minus discount on the latest effective active
  student fee plan, excluding arrears. A unique Tuition/Tuition Fee particular
  can auto-match; otherwise the administrator selects it in Permissions.
- Mixed-particular challans do not store per-particular payment allocation.
  Their allocated paid/discount values are explicitly unavailable, not guessed.
- Results use saved numeric paper marks and dates; absent/leave/direct grades
  are excluded. Creation date is the disclosed fallback when no paper date
  exists. Performance bands count student/award/month result groups.
- Staff attendance uses saved non-Off-Day marks, with Present + Late as present.
  Approvals are real Pending workflows; leave counts use approved date ranges.
- Birthdays use actual birth dates. Complaints use locally saved workflows.
  Native parent submission telemetry is not inferred.
- Mobile Apps and SchoolFlow Updates reflect configured published releases.
  There is no install/adoption claim. SMS Balance & Sent shows unavailable
  external credit/delivery telemetry and reports local communication requests;
  a queued request never means an SMS was sent.

## Verification

- Full regression: 644 tests passed.
- Eleven General tool tests verify all 37 cards/reports, release URL/version checks,
  account-isolated/default/reordered layouts, actual fee values, mixed-head
  limits, numeric result exclusions, discounted tuition and captured ledger
  classifications.
- After the final GET-only campus cache change, 41 staff-access/performance
  tests passed. After tightening finance source access, all 12 General tool and
  targeted staff tests passed. A final public-demo check also passed: demo
  preferences remain session-only and demo visitors cannot change global
  releases or widget role policy.
- Sixteen Chromium checks passed at 390 and 1366 widths: pages/reports, release
  save/Copy, selection/order persistence, Expand, saved default, role settings
  and Excel. No JavaScript errors or body overflow. Mobile/desktop layouts were
  inspected. The fake release URL existed only in a local fictional fixture.
- Hosted rollout verification is appended after deployment. Main remains
  unmerged and no native/SMS delivery is claimed complete.
