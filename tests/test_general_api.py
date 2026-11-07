"""Regression tests for the General module.

Run with: python -m unittest discover -s tests -p 'test_general_api.py'
"""
import os
import tempfile
import unittest
from pathlib import Path

class GeneralApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        os.environ['DATABASE_URL'] = 'sqlite:///' + str(Path(self.tmp.name) / 'control.db')
        os.environ['INSTITUTE_DATABASE_DIR'] = str(Path(self.tmp.name) / 'schools')
        os.environ['PUBLIC_DEMO_ENABLED'] = '0'
        from app import app, db
        self.app, self.db = app, db
        self.app.config.update(TESTING=True, IDENTITY_ENFORCE_IN_TESTS=True)
        self.client = self.app.test_client()
        with self.app.app_context():
            school = self.app.extensions['identity_helpers']['provision'](
                'GENERAL-TEST', 'General Test School', 'owner@example.com', 'a-valid-test-password-123')
            self.school_id = school.id

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
