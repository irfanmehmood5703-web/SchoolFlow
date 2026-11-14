"""Menu coverage, real destinations, category search and private help boundaries."""
import os
import unittest
from urllib.parse import urlsplit
from flask import g

os.environ['DATABASE_URL'] = 'sqlite:///:memory:'
from app import app, db
from module_catalog import MENUS
from how_to_content import GUIDES, SETTINGS, UTILITY_GUIDES


class HowToTests(unittest.TestCase):
    def setUp(self):
        app.config.update(TESTING=True, IDENTITY_ENFORCE_IN_TESTS=False)
        self.ctx = app.app_context(); self.ctx.push()
        db.drop_all(); db.create_all()
        self.client = app.test_client()

    def tearDown(self):
        db.session.remove(); db.drop_all(); self.ctx.pop()
        app.config['IDENTITY_ENFORCE_IN_TESTS'] = False

    def test_every_current_menu_has_a_guide_and_real_destination(self):
        keys = {key for groups in MENUS.values() for _, items in groups for _, key in items}
        self.assertEqual(set(GUIDES), keys)
        with app.test_request_context('/workspace/how-to'):
            g.school_identity = dict(scope='fictional', demo=False)
            from flask import session
            session['owner_id'] = 1
            articles = app.extensions['how_to_catalogue']()
            self.assertEqual(len(articles), len(keys)+len(SETTINGS)+len(UTILITY_GUIDES)+1)
            self.assertEqual(len({a['slug'] for a in articles}), len(articles))
            for article in articles:
                rule, _ = app.url_map.bind('localhost').match(urlsplit(article['target']).path)
                self.assertNotEqual(rule, 'ops.entry', article['slug'])
                self.assertTrue(article['steps'], article['slug'])

    def test_category_filter_search_empty_state_and_escaped_input(self):
        page = self.client.get('/workspace/how-to?category=Finance')
        self.assertEqual(page.status_code, 200)
        self.assertIn(b'How To', page.data)
        self.assertIn(b'Requisition Approvals', page.data)
        self.assertNotIn(b'Write separate Classwork', page.data)
        page = self.client.get('/workspace/how-to?q=Classwork')
        self.assertIn(b'Student Diary', page.data)
        self.assertNotIn(b'Read school summaries', page.data)
        page = self.client.get('/workspace/how-to?q=<script>no-such-guide</script>')
        self.assertIn(b'No matching guides', page.data)
        self.assertNotIn(b'<script>no-such-guide', page.data)
        self.assertEqual(self.client.get('/workspace/how-to?category=Front%20Desk').status_code, 404)

    def test_all_visible_articles_open_and_excluded_features_stay_out(self):
        with app.test_request_context('/workspace/how-to'):
            articles = app.extensions['how_to_catalogue']()
        for article in articles:
            page = self.client.get('/workspace/how-to/'+article['slug'])
            self.assertEqual(page.status_code, 200, article['slug'])
            self.assertIn(b'Step by step', page.data)
            self.assertIn(article['target'].encode().replace(b'&', b'&amp;'), page.data)
        page = self.client.get('/workspace/how-to')
        for title in (b'Front Desk', b'Student 360', b'Canteen', b'School Shop', b'AI Assistant'):
            self.assertNotIn(title, page.data)
        for slug in ('general-library', 'general-feedback', 'general-leaves', 'unknown', 'student-360'):
            self.assertEqual(self.client.get('/workspace/how-to/'+slug).status_code, 404)
        self.assertEqual(self.client.post('/workspace/how-to', data={}).status_code, 405)

    def test_authentication_required_for_index_and_reader(self):
        app.config['IDENTITY_ENFORCE_IN_TESTS'] = True
        for path in ('/workspace/how-to', '/workspace/how-to/students'):
            page = self.client.get(path)
            self.assertEqual(page.status_code, 302)
            self.assertIn('/auth/institute', page.location)

