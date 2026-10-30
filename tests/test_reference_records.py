"""End-to-end record tests with fictional data and an in-memory database."""
import io
import os
import unittest

os.environ["DATABASE_URL"] = "sqlite:///:memory:"
from app import app, db, Student, Employee
from record_schema import DEMO_CHOICES
from werkzeug.security import check_password_hash


class ReferenceRecordTests(unittest.TestCase):
    def setUp(self):
        app.config.update(TESTING=True, SECRET_KEY="test-fixture-not-a-deployment-secret")
        self.ctx = app.app_context()
        self.ctx.push()
        db.drop_all()
        db.create_all()
        self.models = app.extensions["record_models"]
        for category, values in DEMO_CHOICES.items():
            for value in values:
                db.session.add(self.models["settings"](category=category,value=value,class_name=""))
        for category, value, cls in [("subject", "Math", "Demo Class"), ("house", "Green", ""),
                                     ("admission_source", "School Visit", ""), ("disability", "None", ""),
                                     ("mother_tongue", "Urdu", "")]:
            db.session.add(self.models["settings"](category=category,value=value,class_name=cls))
        db.session.commit()
        self.client = app.test_client()
        self.client.get("/records/student/new")
        with self.client.session_transaction() as session:
            self.csrf = session["record_csrf"]

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def student(self, **changes):
        data = dict(_csrf=self.csrf, name="Fictional Student", roll_no="R-100", gender="Female",
            religion="Islam", birth_date="2018-01-12", admission_date="2026-10-30", nationality="Pakistani",
            student_cnic="TEST-BFORM", student_phone="00000000000", student_email="student@example.test",
            birth_city="Test City", blood_group="O+", admission_source="School Visit", caste="Test",
            identification_mark="Test mark", bio_id="1000", disability="None",
            qualification_class="Previous Class", qualification_major="General", qualification_board="Test School",
            qualification_grade="A", qualification_reg_no="OLD-1", qualification_from="2025-01-01", qualification_to="2026-01-01",
            family_mode="new", family_no="F-TEST", father="Fictional Father", father_cnic="TEST-FATHER",
            guardian_name="Fictional Guardian", guardian_relation="Father", phone="00000000000", whatsapp="00000000000",
            guardian_cnic="TEST-GUARDIAN", guardian_email="guardian@example.test", father_qualification="Test Qualification",
            profession="Test Profession", department="Test Department", posting_city="Test City", mother_name="Fictional Mother",
            mother_phone="00000000000", mother_email="mother@example.test", mother_cnic="TEST-MOTHER",
            mother_qualification="Test Qualification", mother_tongue="Urdu", current_address="Test Address", permanent_address="Test Address",
            campus="Demo Campus", class_name="Demo Class", section="A", group_name="General", academic_session="2026-27",
            fee_plan="Demo Fee Plan", subjects=["Math"], house="Green", status="Active", class_of_admission="Demo Class",
            admission_no="ADM-TEST", notes="Complete record", board_reg_no="BOARD-1", board_roll_no="BR-1", board_total="100", board_obtained="80",
            father_contact="1", app_sms="1", parent_notification="1", visitor_0_name="Fictional Visitor", visitor_0_relation="Uncle",
            save_action="view")
        data.update(changes)
        return data

    def employee(self, **changes):
        data = dict(_csrf=self.csrf, name="Fictional Employee", father_name="Fictional Parent", cnic="TEST-CNIC",
            marital_status="Married", gender="Female", address="Test Address", city="Test City", home_phone="00000000000",
            phone="00000000000", notes="Employee notes", campus="Demo Campus", department="Academics", designation_group="Teaching",
            role="Teacher", employment_type="Full Time", employee_no="EMP-TEST", joining_date="2026-10-30",
            probation_from="2026-10-30", probation_to="2027-01-30", increment_month="1", pay_mode="Cash", lecture_assigned="5",
            username="fictional.teacher", password="Fictional-Test-Password-123", app_active="1", diary_approval="required",
            award_permission="return_date", attendance_permission="one_time", contact_absentee="allowed", fee_access="contact",
            salary_access="allowed", save_action="back")
        data.update(changes)
        return data

    def test_full_student_roundtrip_and_profile(self):
        r = self.client.post("/records/student/new", data=self.student())
        self.assertEqual(r.status_code, 302)
        obj = Student.query.one()
        detail = self.models["student"].query.one()
        self.assertEqual(obj.admission_no, "ADM-TEST")
        self.assertEqual(detail.data["subjects"], ["Math"])
        self.assertEqual(detail.data["house"], "Green")
        self.assertEqual(detail.data["visitors"][0]["name"], "Fictional Visitor")
        for key in ["guardian_cnic", "mother_qualification", "qualification_grade", "bio_id", "board_roll_no"]:
            self.assertEqual(detail.data[key], self.student()[key])
        self.assertEqual(self.models["communication"].query.one().status, "Provider not configured")
        r = self.client.get(r.location)
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"Fictional Visitor", r.data)
        self.assertIn(b"BOARD-1", r.data)

    def test_family_link_does_not_overwrite_siblings(self):
        self.client.post("/records/student/new",data=self.student())
        family = self.models["family"].query.one()
        r = self.client.post("/records/student/new",data=self.student(name="Second Fictional Student",admission_no="ADM-2",
            family_mode="existing",family_id=str(family.id),father="Must not change shared father"))
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self.models["family"].query.count(), 1)
        self.assertEqual(Student.query.order_by(Student.id.desc()).first().father, "Fictional Father")
        self.assertEqual(family.data["father"], "Fictional Father")

    def test_invalid_fields_are_atomic(self):
        r = self.client.post("/records/student/new", data=self.student(board_obtained="101",bio_id="abc",qualification_to="2020-01-01"))
        self.assertEqual(r.status_code,422)
        self.assertEqual(Student.query.count(),0)
        self.assertEqual(self.models["family"].query.count(),0)
        self.assertIn(b"Obtained marks cannot exceed",r.data)

    def test_unique_student_and_employee_numbers(self):
        self.client.post("/records/student/new",data=self.student())
        r = self.client.post("/records/student/new",data=self.student())
        self.assertEqual(r.status_code,422)
        self.assertEqual(Student.query.count(),1)
        self.client.post("/records/employee/new",data=self.employee())
        r = self.client.post("/records/employee/new",data=self.employee())
        self.assertEqual(r.status_code,422)
        self.assertEqual(Employee.query.count(),1)

    def test_employee_permissions_and_password_storage(self):
        r = self.client.post("/records/employee/new",data=self.employee())
        self.assertEqual(r.status_code,302)
        detail = self.models["employee"].query.one()
        self.assertTrue(check_password_hash(detail.password_hash,"Fictional-Test-Password-123"))
        self.assertNotIn("password",detail.data)
        self.assertEqual(detail.data["attendance_permission"],"one_time")
        self.assertEqual(detail.data["award_permission"],"return_date")
        self.assertEqual(detail.data["fee_access"],"contact")
        self.assertTrue(detail.app_active)
        r = self.client.get(f"/records/employee/{detail.employee_id}/edit")
        self.assertNotIn(b"Fictional-Test-Password-123",r.data)

    def test_update_preserves_salary_and_password(self):
        self.client.post("/records/employee/new",data=self.employee())
        obj = Employee.query.one()
        obj.salary = 10000
        db.session.commit()
        old_hash = self.models["employee"].query.one().password_hash
        r = self.client.post(f"/records/employee/{obj.id}/edit",data=self.employee(password="",name="Updated Employee"))
        self.assertEqual(r.status_code,302)
        self.assertEqual(obj.name,"Updated Employee")
        self.assertEqual(obj.salary,10000)
        self.assertEqual(self.models["employee"].query.one().password_hash,old_hash)

    def test_save_buttons_and_salary_handoff_do_not_claim_payroll(self):
        r = self.client.post("/records/student/new",data=self.student(save_action="new"))
        self.assertTrue(r.location.endswith("/records/student/new"))
        r = self.client.post("/records/employee/new",data=self.employee(save_action="salary"))
        self.assertIn("/salary-plan",r.location)
        r = self.client.get(r.location)
        self.assertIn(b"No salary plan was created",r.data)

    def test_attachment_download_and_removal(self):
        data = self.student()
        data.update(document_title="Test document",documents=(io.BytesIO(b"%PDF-1.4\nfictional test document"),"test.pdf"))
        r = self.client.post("/records/student/new",data=data,content_type="multipart/form-data")
        self.assertEqual(r.status_code,302)
        f = self.models["file"].query.one()
        r = self.client.get(f"/records/files/{f.id}")
        self.assertEqual(r.status_code,200)
        self.assertEqual(r.headers["X-Content-Type-Options"],"nosniff")
        self.assertIn("attachment",r.headers["Content-Disposition"])
        obj = Student.query.one()
        r = self.client.post(f"/records/student/{obj.id}/edit", data=self.student(family_mode="existing",
            family_id=str(self.models["family"].query.one().id),remove_document=str(f.id)))
        self.assertEqual(r.status_code,302)
        self.assertEqual(self.models["file"].query.count(),0)

    def test_malicious_photo_and_csrf_rejected(self):
        data = self.employee()
        data["photo"] = (io.BytesIO(b"<script>alert(1)</script>"), "fake.png")
        r = self.client.post("/records/employee/new",data=data,content_type="multipart/form-data")
        self.assertEqual(r.status_code,422)
        self.assertEqual(Employee.query.count(),0)
        r = self.client.post("/records/student/new",data=self.student(_csrf="bad"))
        self.assertEqual(r.status_code,400)

    def test_settings_class_subject_filter_and_legacy_records(self):
        legacy = Student(admission_no="OLD-1",name="Legacy Student",father="Legacy Father",class_name="Old Class")
        db.session.add(legacy)
        db.session.commit()
        for path in ["/records/student","/records/employee","/records/student/new","/records/employee/new",
                     "/records/settings",f"/records/student/{legacy.id}",f"/records/student/{legacy.id}/edit","/attendance","/exams"]:
            self.assertEqual(self.client.get(path).status_code,200,path)
        r = self.client.post("/records/settings",data=dict(_csrf=self.csrf,category="subject",value="Science",class_name="Demo Class"))
        self.assertEqual(r.status_code,302)
        self.assertEqual(self.models["settings"].query.filter_by(category="subject",value="Science").count(),1)
        r = self.client.post("/records/student/new",data=self.student(subjects=["Unknown Subject"]))
        self.assertEqual(r.status_code,422)

    def test_export_filters_and_formula_safety(self):
        self.client.post("/records/student/new",data=self.student(name="=FICTIONAL()"))
        r = self.client.get("/records/student/export.csv?q=FICTIONAL")
        self.assertEqual(r.status_code,200)
        self.assertIn(b"'=FICTIONAL()",r.data)
        self.assertNotIn(b"password",r.data.lower())
        r = self.client.get("/records/student?q=not-found")
        self.assertIn(b"No records match",r.data)


if __name__ == "__main__":
    unittest.main()
