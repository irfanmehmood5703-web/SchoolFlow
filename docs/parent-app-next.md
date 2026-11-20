Parent summary interface work in progress. Not registered or deployed.

The user supplied the complete Parent App reference screenshots, then explicitly prioritised the launcher/logo bug. Branding is fixed separately on main. Continue this parent interface in the same SchoolFlow repository.

Draft: parent_app.py contains scoped family summaries, child selection, monthly attendance/calendar data, published-result summaries, fee/partial-payment summaries, leave/feedback actions, PTM feedback, notices, and guarded photos. It is not yet wired into parents.py.

Remaining: implement parent_study.py for school-published learning/notes/assignments/vacation/date sheets/roll slips; create the Parent App base/content templates and responsive CSS/JS; connect authenticated parents.home/feature without breaking existing 200/403 legacy routes; preserve diary/notice attachments and result publication rules; test two families/two schools, blocked features, persistence, requests and mobile/desktop navigation; remove native Parents portal toolbar only once the new shell is ready and bump the APK source protocol. A school-bound parent login remains institute-specific; do not infer cross-school family links from a shared phone number.

Review draft before integrating: avoid allowing snapshot child name to overwrite exam title; choose explicitly requested student on legacy feature routes; preserve exact fee paisa and publication/privilege gates. No real school/student records were changed by this draft.
