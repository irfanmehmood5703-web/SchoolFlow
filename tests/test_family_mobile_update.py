"""Regression for owner-confirmed family mobile updates and parent login."""
import unittest
from tests import test_parents_ptm as fixture
from app import app,db,Student

class FamilyMobileUpdateTests(unittest.TestCase):
    password=fixture.ParentsPtmTests.password
    setUp=fixture.ParentsPtmTests.setUp
    tearDown=fixture.ParentsPtmTests.tearDown
    tenant=fixture.ParentsPtmTests.tenant
    token=fixture.ParentsPtmTests.token
    owner=fixture.ParentsPtmTests.owner
    post=fixture.ParentsPtmTests.post
    def test_family_phone_persists_for_siblings_and_parent_sign_in(self):
        old='03000000001';new='03100000009';code='58312694'
        fields=dict(campus='North',section='A',group_name='General',academic_session='QA Session',fee_plan='QA Plan')
        def seed():
            for cat in ('group_name','academic_session','fee_plan'):
                db.session.add(self.rm['settings'](category=cat,value=fields[cat],class_name=''))
            f=db.session.get(self.rm['family'],1)
            f.data={**f.data,'father_cnic':'0000000000000','guardian_relation':'Father'}
            s=db.session.get(Student,1);s.phone=old
            d=self.rm['student'].query.filter_by(student_id=1).one();d.data={**d.data,**fields}
            sibling=Student(admission_no='S3',name='Fictional Sibling',class_name='One',phone=old,status='Active')
            db.session.add(sibling);db.session.flush()
            db.session.add(self.rm['student'](student_id=sibling.id,family_id=1,data={**fields,'phone':old}))
            return sibling.id
        sid=self.tenant(seed)
        settings='/workspace/general/parents/login-settings'
        self.assertEqual(self.post(settings,dict(action='enable',version='0',login_code=code,confirm_code=code,acknowledge='yes')).status_code,302)
        login='/parents/PARENT-TEST/login'
        def sign(number):
            p=app.test_client();self.token(p,login)
            return p,self.post(login,dict(action='shared',phone=number,login_code=code),p)
        p,r=sign(old);self.assertEqual(r.status_code,302)
        path='/records/student/1/edit'
        self.assertIn(b'Update registered family mobile number',self.c.get(path).data)
        payload=dict(name='Fictional Child 1',admission_no='S1',gender='Male',admission_date='2026-01-01',family_mode='existing',family_id='1',family_no='F1',father='Fictional Guardian 1',father_cnic='0000000000000',guardian_relation='Father',phone=new,class_name='One',status='Active',**fields)
        self.assertEqual(self.post(path,payload).status_code,302)
        self.assertEqual(self.tenant(lambda:db.session.get(self.rm['family'],1).data['phone']),old)
        result=self.post(path,{**payload,'update_family_mobile':'1'})
        self.assertEqual(result.status_code,302,result.data[:500])
        def check():
            self.assertEqual(db.session.get(self.rm['family'],1).data['phone'],new)
            self.assertEqual(db.session.get(Student,1).phone,new)
            self.assertEqual(db.session.get(Student,sid).phone,new)
            self.assertEqual(db.session.get(self.rm['family'],2).data['phone'],'03000000002')
            self.assertEqual(self.rm['student'].query.filter_by(student_id=sid).one().data['phone'],new)
        self.tenant(check)
        self.assertEqual(p.get('/parents/PARENT-TEST').status_code,302)
        self.assertNotEqual(sign(old)[1].status_code,302)
        q,r=sign(new);self.assertEqual(r.status_code,302)
        page=q.get('/parents/PARENT-TEST')
        self.assertIn(b'Fictional Child 1',page.data)
        self.assertIn(b'Fictional Sibling',page.data)
        self.assertNotIn(b'Fictional Child 2',page.data)
