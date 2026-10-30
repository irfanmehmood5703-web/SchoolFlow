# Certificate reference coverage — 30 October 2026

The supplied 30-image batch has been reviewed together with the certificate list, log and QR tab screenshots. No real pupil names, contact details, photos or school assets from those images are seeded into the software.

| Document | Reference coverage | Implemented default |
|---|---|---|
| Student Card New | Front/back preview and editor | Editable front/back student identification and QR card |
| Student Card | Specific preview/editor missing | Clearly marked original starter card |
| Guardian Card | Preview and editor | Child identification, guardian name/contact and pickup/drop-off card |
| School Leaving Certificate | Preview and full editor | Admission/leaving dates, class, section, character, registration/DOB/session, remarks, teacher report, copy and signatures |
| Student Character Certificate | Specific preview/editor missing | Clearly marked original starter certificate |
| Migration Slip Campus - Campus | Specific preview/editor missing | Clearly marked original starter migration form |
| Student Rustication Notice | Specific preview/editor missing | Clearly marked original starter notice; no automatic status change |
| Student Warning Letter | Editor | Editable attendance/progress warning letter |
| Student Trip Letter | Preview and editor | School permission request, trip details and counts |
| Student Fee Clearance Certificate | Preview and editor | Current fee values, total outstanding and signatures; issuance requires no outstanding challans |
| Student Admission Confirmation Letter | Preview and editor | Admission details, base fee plan, current fee position and signatures |
| Student Envelopes Tags | Editor body | School heading, SID/roll, pupil/father, class/section/session |
| Student Admitted Card | Preview and editor | Identity, admission date, admission/tuition fee, fee totals and signatures |
| Student Birth Certificate | Preview and editor | School-record birth date, registration details and signatures |
| Appreciation Certificate | Preview and editor | Pupil/father/class, editable achievement/position and signatures |

## Workflow

- Campus-specific templates: Name, Campus, rich-text Header/Body/Footer, student/institute/fee/reference tag list, save and safe unsaved preview.
- Preview never issues a document or reserves a reference. Selected student previews have Previous/Next controls.
- Generate & Print is an explicit POST action, assigns a reference, snapshots content and images, and logs the batch. Repeated print tokens do not issue duplicates.
- Saved documents can be reprinted without changing their reference or consulting current student/fee/template data.
- Certificate logs capture generated-for-printing events, not physical printer completion. Authenticated actor identities remain pending the institution-login work.
- QR codes identify a pupil with an opaque signed value. They do not themselves grant access to a record, authenticate a parent, or mark attendance.
- Student QR lists include active pupils and campus/class/section/gender filtering, column selection, CSV/Excel, and selected QR printing/PDF.
- PDF output uses the browser’s Print / Save PDF flow. Template editing is an original lightweight editor, not the reference editor’s source code.
- Exact print dimensions, typography and source CSS are reviewable original defaults; screenshots do not supply the original HTML/CSS. Campus-wide yearly fee grids and advanced fee-print settings are separate pending workflows.
