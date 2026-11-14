"""Recover accidental sessions without touching same-named classes or live data."""
import unittest
from tests import test_messaging as fixture
from app import app,db

class CatalogOptionsTests(unittest.TestCase):
    password=fixture.MessagingTests.password
    setUp=fixture.MessagingTests.setUp;tearDown=fixture.MessagingTests.tearDown;tenant=fixture.MessagingTests.tenant;csrf=fixture.MessagingTests.csrf;login=fixture.MessagingTests.login;post=fixture.MessagingTests.post
    def option(self,value='One',category='academic_session',school=None):
        def seed():
            r=self.rm['settings'](category=category,value=value,class_name='');db.session.add(r);db.session.flush();return r.id
        return self.tenant(seed,school)
    def remove(self,rid,value='One',client=None):return self.post('/records/settings/sessions/'+str(rid)+'/delete',dict(confirm_value=value),client)
    def present(self,rid,school=None):return self.tenant(lambda:db.session.get(self.rm['settings'],rid) is not None,school)
    def test_class_category_stays_selected_after_each_save(self):
        for name in ('Three','Four'):
            r=self.post('/records/settings',dict(category='class_name',value=name));self.assertEqual(r.status_code,302);self.assertIn('category=class_name',r.location)
            page=self.c.get(r.location);self.assertIn(b'value="class_name" selected',page.data)
        self.assertEqual(self.tenant(lambda:self.rm['settings'].query.filter_by(category='academic_session').count()),0)
    def test_unused_session_deletes_but_same_named_class_and_records_remain(self):
        rid=self.option();other=self.option('2026-27')
        page=self.c.get('/records/settings');self.assertIn(('sessions/'+str(rid)+'/delete').encode(),page.data)
        self.assertEqual(self.remove(rid).status_code,302);self.assertFalse(self.present(rid));self.assertTrue(self.present(other))
        self.assertEqual(self.tenant(lambda:self.rm['settings'].query.filter_by(category='class_name',value='One').count()),1)
        self.assertEqual(self.tenant(lambda:__import__('app').Student.query.count()),2)
        self.assertEqual(self.tenant(lambda:self.ops['audit'].query.filter_by(action='Delete unused catalog session').count()),1)
    def test_current_session_and_mapping_are_protected(self):
        rid=self.option();M=app.extensions['institute_setup_models']
        for model in ('profile','mapping'):
            def use():
                if model=='profile':
                    r=db.session.get(M[model],1);r.data={**r.data,'current_session':'One'}
                else:db.session.add(M[model](campus='North',class_name='One',data=dict(academic_session='One')))
            self.tenant(use);r=self.remove(rid);self.assertEqual(r.status_code,302);self.assertIn(b'cannot be deleted',self.c.get(r.location).data);self.assertTrue(self.present(rid))
            self.tenant(lambda: M[model].query.delete())
    def test_student_and_nested_workflow_session_references_are_protected(self):
        rid=self.option()
        def use():
            r=self.rm['student'].query.first();r.data={**r.data,'academic_session':'One'}
        self.tenant(use);self.remove(rid);self.assertTrue(self.present(rid))
        def use_workflow():
            r=self.rm['student'].query.first();r.data={k:v for k,v in r.data.items() if k!='academic_session'}
            db.session.add(self.ops['workflow'](kind='awards',status='Active',data=dict(papers=[dict(session='One')])) )
        self.tenant(use_workflow);self.remove(rid);self.assertTrue(self.present(rid))
    def test_csrf_stale_confirm_and_non_session_rows_cannot_be_deleted(self):
        rid=self.option();url='/records/settings/sessions/'+str(rid)+'/delete'
        self.assertEqual(self.c.post(url,data=dict(confirm_value='One')).status_code,400)
        self.assertEqual(self.c.get(url).status_code,405)
        self.assertEqual(self.remove(rid,'Changed').status_code,409)
        cls=self.option('Five','class_name');self.assertEqual(self.remove(cls,'Five').status_code,404)
        self.assertTrue(self.present(rid));self.assertTrue(self.present(cls))
    def test_other_school_and_staff_without_delete_permission_are_blocked(self):
        school=self.H['provision']('CAT-TWO','Other fictional','owner@example.invalid',self.password).id
        foreign=self.option('Other school session',school=school)
        # A foreign numeric ID never resolves to the foreign school's row.
        self.assertIn(self.remove(foreign,'Other school session').status_code,(404,409));self.assertTrue(self.present(foreign,school))
        rid=self.option()
        def grant():
            staff=db.session.get(self.Staff,1);staff.data={**staff.data,'campuses':['North','South'],'permissions':{'core.view':['North','South'],'core.update':['North','South']}}
        self.tenant(grant);teacher=self.login('teacher1')
        self.assertEqual(self.remove(rid,client=teacher).status_code,403)
        self.assertNotIn(b'Delete session One',teacher.get('/records/settings').data)
        self.assertTrue(self.present(rid))
