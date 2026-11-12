"""Regression tests for the General module.

Run with: python -m unittest discover -s tests -p 'test_general_api.py'
"""
import os
import tempfile
import unittest
from pathlib import Path

class GeneralApiTests(unittest.TestCase):
    def setUp(self):
        from app import app, db
        self.tmp = tempfile.TemporaryDirectory()
        self.app, self.db = app, db
        self.previous = {key: app.config.get(key) for key in ('TESTING','IDENTITY_ENFORCE_IN_TESTS','INSTITUTE_DATABASE_DIR','PUBLIC_DEMO_ENABLED')}
        app.config.update(TESTING=True, IDENTITY_ENFORCE_IN_TESTS=True,
                          INSTITUTE_DATABASE_DIR=self.tmp.name, PUBLIC_DEMO_ENABLED=False)
        self.ctx=app.app_context();self.ctx.push()
        db.drop_all();db.create_all()
        self.client = app.test_client()
        school = app.extensions['identity_helpers']['provision'](
            'GENERAL-TEST', 'General Test School', 'owner@example.com', 'a-valid-test-password-123')
        self.school_id = school.id

    def tearDown(self):
        self.db.session.remove();self.db.drop_all();self.ctx.pop()
        self.app.config.update(self.previous);self.tmp.cleanup()

    def login(self):
        self.client.get('/auth/institute')
        with self.client.session_transaction() as session: token=session['record_csrf']
        self.client.post('/auth/institute',data={'_csrf':token,'code':'GENERAL-TEST'})
        with self.client.session_transaction() as session: token=session['record_csrf']
        self.assertEqual(self.client.post('/auth/login',data={'_csrf':token,'email':'owner@example.com','password':'a-valid-test-password-123'}).status_code,302)
        self.client.get('/workspace/general/')
        with self.client.session_transaction() as session: return {'X-CSRF-Token':session['record_csrf']}

    def test_integrated_navigation_and_library_workflow(self):
        from app import Student
        from flask import g
        headers=self.login()
        with self.app.test_request_context('/'):
            g.institute_engine=self.app.extensions['identity_helpers']['engine'](self.school_id)
            self.db.session.add(Student(admission_no='LIB-1',name='Fictional Library Borrower',class_name='One',status='Active'))
            self.db.session.commit();self.db.session.remove()
        page=self.client.get('/workspace/general/')
        self.assertEqual(page.status_code,200)
        self.assertEqual(page.data.count(b'<summary>General</summary>'),1)
        for path in ('/workspace/general/app-links','/workspace/general/widgets','/workspace/general/parents','/workspace/general/?section=leaves'):
            self.assertIn(path.encode(),page.data)
        self.assertEqual(self.client.get('/workspace/general/widgets').data.count(b'data-general-widget='),37)
        result=self.client.post('/api/general/library/catalogue',json={'title':'Fictional Book'},headers=headers)
        self.assertEqual(result.status_code,201)
        book=result.json['id']
        result=self.client.post('/api/general/library/copies',json={'book_id':book,'accession':'LIB-QA-1'},headers=headers)
        self.assertEqual(result.status_code,201)
        copy=result.json['id']
        result=self.client.post('/api/general/library/issue',json={'copy_id':copy,'borrower_type':'student','borrower_id':'1','days':14},headers=headers)
        self.assertEqual(result.status_code,201)
        loan=result.json['id']
        self.assertEqual(self.client.get('/api/general/library/reports/summary').json['issued'],1)
        self.assertEqual(self.client.post('/api/general/library/return/'+str(loan),json={},headers=headers).status_code,200)
        self.assertEqual(self.client.get('/api/general/library/reports/summary').json['issued'],0)
        with self.client.session_transaction() as session: session.clear()
        self.login()
        self.assertEqual(self.client.get('/api/general/library/catalogue').json[0]['title'],'Fictional Book')

    def test_additive_release_upgrade_preserves_existing_library_rows(self):
        from sqlalchemy import inspect
        headers=self.login()
        self.assertEqual(self.client.post('/api/general/library/catalogue',json={'title':'Preserved Library Book'},headers=headers).status_code,201)
        helpers=self.app.extensions['identity_helpers']
        engine=helpers['engine'](self.school_id)
        table=self.db.metadata.tables['widget_center_preference']
        self.db.session.remove()
        table.drop(engine)
        self.assertNotIn(table.name,inspect(engine).get_table_names())
        helpers['upgrade_missing_tables']()
        self.assertIn(table.name,inspect(engine).get_table_names())
        self.assertEqual(self.client.get('/api/general/library/catalogue').json[0]['title'],'Preserved Library Book')

    def test_anonymous_api_requires_login(self):
        for path in ('/api/general/library/catalogue',
                     '/api/general/feedback/', '/api/general/leaves/'):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 401, path)

    def test_general_portal_rejects_anonymous(self):
        response = self.client.get('/workspace/general/')
        self.assertIn(response.status_code, (302, 403))

    def test_library_rejects_mutation_without_csrf(self):
        # Authentication is intentionally required before mutation validation.
        response = self.client.post('/api/general/library/catalogue', json={'title':'Test'})
        self.assertEqual(response.status_code, 401)

if __name__ == '__main__':
    unittest.main()
