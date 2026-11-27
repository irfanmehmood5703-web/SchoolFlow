"""Shared result-list assets are included on the main workspace pages."""
import os
import re
import unittest
os.environ['DATABASE_URL'] = 'sqlite:///:memory:'
from app import app, db, Employee

class ResultListAssetsTests(unittest.TestCase):
    def setUp(self):
        app.config.update(TESTING=True, IDENTITY_ENFORCE_IN_TESTS=False)
        self.ctx=app.app_context()
        self.ctx.push()
        db.drop_all()
        db.create_all()
        self.client=app.test_client()
        employee=Employee(employee_no='TEST-1', name='Fictional teacher', role='Teacher', status='Active')
        db.session.add(employee)
        db.session.flush()
        db.session.add(app.extensions['ops_models']['workflow'](
            kind='salary-plans', status='Approved',
            data={'employee_id':str(employee.id), 'basic':2000000}))
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def test_workspace_pages_share_versioned_assets(self):
        for url in ['/records/student', '/records/employee',
                    '/workspace/salary-plans', '/workspace/payroll-policy']:
            with self.subTest(url=url):
                response=self.client.get(url)
                self.assertEqual(response.status_code, 200)
                body=response.get_data(as_text=True)
                for filename in ['result_lists.css', 'result_lists.js']:
                    match=re.search(r'(?:href|src)="([^"]*/'+filename+r'(?:\?[^"]*)?)"',body)
                    self.assertIsNotNone(match,filename)
                    with self.client.get(match.group(1)) as asset:
                        self.assertEqual(asset.status_code, 200)
                self.assertIn('defer',body.split('result_lists.js',1)[1].split('>',1)[0])

    def test_salary_plan_keeps_original_selection_and_record(self):
        response=self.client.get('/workspace/salary-plans')
        self.assertEqual(response.status_code,200)
        body=response.get_data(as_text=True)
        self.assertIn('Salary Plan Approvals', body)
        self.assertIn('Fictional teacher', body)
        self.assertIn('20,000', body)
        self.assertIn('name="ids"', body)
        self.assertIn('class="status-pill">Approved', body)
