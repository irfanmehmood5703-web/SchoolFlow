"""Field registry transcribed from the supplied student/employee screenshots.

Lists whose dropdown contents were not shown are configurable in Record Settings.
The registry intentionally includes every visible field, including permissions.
"""

def field(key, label, kind="text", required=False, options=None, category=None, **kw):
    return dict(key=key, label=label, kind=kind, required=required,
                options=options or [], category=category, **kw)

STUDENT_SECTIONS = [
    ("Student Personal Information", [
        field("name", "Student Name", required=True),
        field("roll_no", "Roll No"),
        field("gender", "Gender", "select", True, category="gender"),
        field("religion", "Religion", "select", category="religion"),
        field("birth_date", "Date of Birth", "date"),
        field("admission_date", "Admission Date", "date", True),
        field("nationality", "Nationality", "select", category="nationality"),
        field("student_cnic", "Student CNIC/B-Form"),
        field("student_phone", "Student Contact No", "tel"),
        field("student_email", "Student Email", "email"),
        field("birth_city", "Birth City"),
        field("blood_group", "Blood Group", "select", category="blood_group"),
        field("admission_source", "Admission Source", "select", category="admission_source"),
        field("caste", "Caste"),
        field("identification_mark", "Identification Mark"),
        field("bio_id", "Bio Id", "digits", help="Defaults to the student's SID after saving. Use digits only."),
        field("disability", "Disability", "select", category="disability"),
    ]),
    ("Previous Qualification", [
        field("qualification_class", "Degree/Class"),
        field("qualification_major", "Major"),
        field("qualification_board", "Board/University/School"),
        field("qualification_grade", "%age/Grade/CGPA"),
        field("qualification_reg_no", "Reg No"),
        field("qualification_from", "From", "date"),
        field("qualification_to", "To", "date"),
    ]),
    ("Family Information", [
        field("family_mode", "Family", "select", True,
              options=[("new", "New Family"), ("existing", "Existing Family")]),
        field("family_id", "Select Existing Family", "family"),
        field("family_no", "Family No"),
        field("father", "Father Name", required=True),
        field("father_cnic", "Father CNIC", required=True),
        field("guardian_name", "Guardian Name"),
        field("guardian_relation", "Guardian Relation", "select", True, category="guardian_relation"),
        field("phone", "Father/Guardian Mobile", "tel", True),
        field("whatsapp", "WhatsApp No.", "tel"),
        field("guardian_cnic", "Guardian CNIC"),
        field("guardian_email", "Father/Guard Email", "email"),
        field("father_qualification", "Father Qualification"),
        field("profession", "Profession"),
        field("department", "Department"),
        field("posting_city", "Posting City"),
        field("mother_name", "Mother Name"),
        field("mother_phone", "Mother Mobile", "tel"),
        field("mother_email", "Mother Email", "email"),
        field("mother_cnic", "Mother CNIC"),
        field("mother_qualification", "Mother Qualification"),
        field("mother_tongue", "Mother Tongue", "select", category="mother_tongue"),
        field("current_address", "Current Address", "textarea"),
        field("permanent_address", "Permanent Address", "textarea"),
    ]),
    ("Office Information", [
        field("campus", "Campus", "select", True, category="campus"),
        field("class_name", "Class", "select", True, category="class_name"),
        field("section", "Section", "select", True, category="section"),
        field("group_name", "Group/Discipline", "select", True, category="group_name"),
        field("academic_session", "Session", "select", True, category="academic_session"),
        field("fee_plan", "Fee Plan", "select", True, category="fee_plan"),
        field("subjects", "Student Subjects", "subjects", category="subject"),
        field("house", "House", "select", category="house"),
        field("status", "Current Status", "select", True,
              options=[("Active", "Currently Enrolled"), ("Admission Query", "Admission Query"),
                       ("Waiting", "Waiting Approval"), ("Inactive", "Inactive"),
                       ("Withdrawn", "Withdrawn"), ("Passed Out", "Passed Out")]),
        field("class_of_admission", "Class of Admission", "select", category="class_name"),
        field("leaving_date", "Leaving Date", "date", help="Used on school leaving certificates; saving it does not change student status."),
        field("admission_no", "Admission No."),
        field("notes", "Notes", "textarea"),
    ]),
    ("Board Information", [
        field("board_reg_no", "Board Reg No."),
        field("board_roll_no", "Board Roll No."),
        field("board_total", "Total Marks", "number"),
        field("board_obtained", "Obtained Marks", "number"),
    ]),
]

EMPLOYEE_SECTIONS = [
    ("Personal Details", [
        field("name", "Employee Name", required=True),
        field("father_name", "Father/Husband Name", required=True),
        field("cnic", "CNIC"),
        field("marital_status", "Marital Status", "select", True, category="marital_status"),
        field("gender", "Gender", "select", True, category="gender"),
    ]),
    ("Contact Details", [
        field("address", "Address"), field("city", "City"),
        field("home_phone", "Home Phone", "tel"), field("phone", "Mobile", "tel", True),
    ]),
    ("Other Information", [field("notes", "Notes", "textarea")]),
    ("Office Information", [
        field("campus", "Select Campus", "select", True, category="campus"),
        field("department", "Department", "select", True, category="department"),
        field("designation_group", "Designation Group", "select", True, category="designation_group"),
        field("role", "Designation", "select", True, category="designation"),
        field("employment_type", "Employment Type", "select", True, category="employment_type"),
        field("employee_no", "Employee Code", required=True),
        field("joining_date", "Joining Date", "date", True),
        field("probation_from", "Probation From", "date"),
        field("probation_to", "Probation To", "date"),
        field("increment_month", "Increment Month", "select", options=[("", "Not Set")]+
              [(str(i), m) for i, m in enumerate(["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"], 1)]),
        field("pay_mode", "Pay Mode", "select", category="pay_mode"),
        field("lecture_assigned", "Lecture Assigned", "integer"),
    ]),
    ("Teacher App Credentials", [
        field("username", "Username"), field("password", "Password", "password"),
        field("app_active", "Active", "checkbox"),
        field("diary_approval", "Multimedia Diary", "radio", options=[("required", "Approval Required"), ("not_required", "No need for approval")]),
        field("award_permission", "Award List", "radio", options=[("update", "Update"), ("return_date", "Update till Return Date"), ("one_time", "One Time")]),
        field("attendance_permission", "Attendance", "radio", options=[("update", "Update"), ("one_time", "One Time"), ("until", "Update till")]),
        field("contact_absentee", "Contact Absentee Guardian", "radio", options=[("allowed", "Allowed"), ("not_allowed", "Not Allowed")]),
        field("fee_access", "Access Fee Defaulter Information", "radio", options=[("not_allowed", "Not Allowed"), ("view", "Show Fee Defaulters"), ("contact", "Show Fee Defaulters with contact")]),
        field("salary_access", "Teacher App Salary Report", "radio", options=[("allowed", "Allowed"), ("not_allowed", "Not Allowed")]),
    ]),
]

STUDENT_COMMUNICATION = [
    ("father_contact", "Father Contact"), ("mother_contact", "Mother Contact"),
    ("student_contact", "Student Contact"), ("branded_sms", "Branded SMS"),
    ("app_sms", "App SMS"), ("whatsapp_sms", "WhatsApp SMS"),
    ("parent_notification", "Parent App Notification"), ("send_sms", "Send SMS"),
]

FAMILY_KEYS = [f["key"] for title, fields in STUDENT_SECTIONS if title == "Family Information"
               for f in fields if f["key"] not in ("family_mode", "family_id")]

# These are setup values for a fictional demo, not a claimed transcription of
# dropdown options which were closed in the screenshots.
DEMO_CHOICES = {
    "campus": ["Demo Campus"], "class_name": ["Demo Class"], "section": ["A"],
    "group_name": ["General"], "academic_session": ["2026-27"], "fee_plan": ["Demo Fee Plan"],
    "gender": ["Male", "Female"], "religion": ["Islam"], "nationality": ["Pakistani"],
    "blood_group": ["A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-"],
    "guardian_relation": ["Father", "Mother", "Guardian"],
    "marital_status": ["Married", "Unmarried"],
    "department": ["Academics"], "designation_group": ["Teaching"],
    "designation": ["Teacher"], "employment_type": ["Full Time"],
    "pay_mode": ["Cash", "Bank Transfer"],
}

CATEGORIES = {f["category"]: f["label"] for sections in [STUDENT_SECTIONS, EMPLOYEE_SECTIONS]
              for _, fields in sections for f in fields if f["category"]}
