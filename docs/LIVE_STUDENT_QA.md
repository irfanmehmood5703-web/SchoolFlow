# Live private-school student flow check

The software owner requested adding one student and checking connected data.
Testing uses the original SchoolFlow host and a new isolated institute,
SF-QA-13NOV-1EBB, labelled SchoolFlow QA - Fictional student test. Its single
child is QA Student 13Nov, admission QA-STUDENT-001. All names, contacts,
records, notices, marks and money are synthetic. No actual school was populated
with fixtures and no SMS, WhatsApp, bank transfer or APK installation was made.

The QA owner uses normal institute-code/password authentication. Student and
school setup, fee plan, challan, receipt, attendance, exam and General records
were submitted through the actual hosted web forms. Independent reads of the
private PostgreSQL schema checked saved records and accounting totals.

| Item | Expected and observed |
| --- | --- |
| Students / family | One active student, linked family, correct class/campus/section |
| Refresh / new sign-in | Same student retained |
| Photo | Synthetic PNG saved, listed and downloaded through scoped file route |
| Gross monthly tuition | PKR 3,500 |
| Student concession | PKR 500 |
| Issued November challan | PKR 3,000; one bill after repeated generation |
| Receipt | PKR 1,000; duplicate submission refused |
| Outstanding | PKR 2,000 |
| Receipt ledger | One source link; total debit100,000 / credit100,000 paisa |
| Attendance | Present; invalid status rejected without replacing it |
| Exam | Mathematics80 /100 persisted and appeared in school results |
| Fee exports | Student status, detail, class/particular, family and monthly defaulter reports reconcile with 3,000 /1,000 /2,000 |
| General / parent | Targeted diary and notice saved; parent saw correct fees, attendance, diary, notice and profile |
| Access separation | Parent denied foreign child and staff administration; private child absent from shared demo; anonymous student requests redirected |

Initial testing recorded81 distinct checks:80 passed and one missing connection
was found. Parent Academics & Marks and Exam Report Cards had no connection to
saved exam scores. This was not treated as a successful empty result.

## Correction

School results now offer an explicit school-owner Publish to Parents App action.
The release stores a reviewed per-student copy and defaults to unpublished.
All eligible papers must be complete. A source fingerprint rejects changes to
marks, roster or grading since review; optimistic versions reject stale actions.
Editing marks does not silently update the published copy: review and republish,
or unpublish to withdraw it. Audit records identify the owner and exam action.
No grades from any real school are automatically published by this deployment.

Parent marks/results remain behind the existing institute/family/child and fee
privilege checks. Only the current child's saved release is rendered; another
child's results are never included. Numeric, absent/leave and qualitative papers
reuse the school result calculation. Unpublished and incomplete exams stay out
of the parent view. The Parent Portal adds Academics & Marks / Exam Report Cards
links. The shared result calculation is used by the school report and release,
rather than duplicating grading/subject inclusion formulas.

The additive parent_exam_release table is created through normal workspace
upgrades; no existing business records or deployment secrets are replaced.
Four new tests cover explicit publication, family isolation, unchanged published
copies, republish/unpublish, stale source/version, malformed/absent CSRF and fee
restrictions. Full regression, PostgreSQL and corrected live checks follow.

This one-student pass does not certify HRM/payroll, every report layout,
physical mobile apps, gate hardware, SIM delivery or load/security behavior.
