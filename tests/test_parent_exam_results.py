"""Explicit owner publication, immutable copies and family-scoped exam results."""
import re,unittest
from tests import test_parents_ptm as fixture
from app import app,db

class ParentExamResultTests(unittest.TestCase):
    setUp=fixture.ParentsPtmTests.setUp
    tearDown=fixture.ParentsPtmTests.tearDown
    tenant=fixture.ParentsPtmTests.tenant
    token=fixture.ParentsPtmTests.token
    owner=fixture.ParentsPtmTests.owner
    post=fixture.ParentsPtmTests.post
    credential=fixture.ParentsPtmTests.credential
    parent=fixture.ParentsPtmTests.parent
    password=fixture.ParentsPtmTests.password
    def seed_exam(self,complete=True):
        def seed():
            W=self.ops['workflow'];S=self.ops['score']
            w=W(kind='awards',status='Active',data=dict(name='Fictional exam',campus='North',class_name='One',papers=[dict(subject='Math',grading='Marks',total=100,date='2026-11-13',type='Written')]))
            db.session.add(w);db.session.flush();self.award=w.id
            db.session.add(S(award_id=w.id,student_id=1,paper=0,obtained=80,state=''))
            if complete:db.session.add(S(award_id=w.id,student_id=2,paper=0,obtained=27,state=''))
        self.tenant(seed)
    def review(self):
        r=self.c.get(f'/workspace/core/exam/results/{self.award}');self.assertEqual(r.status_code,200,r.data[:300])
        return dict(version=re.search(rb'name="version" value="([^"]+)"',r.data)[1].decode(),fingerprint=re.search(rb'name="fingerprint" value="([^"]+)"',r.data)[1].decode(),action='publish')
    def publish(self,data=None,c=None):return self.post(f'/workspace/general/parents/exams/{self.award}/publish',data or self.review(),c)
    def test_unpublished_not_exposed_published_is_own_child_only(self):
        self.seed_exam();p=self.parent()
        path='/parents/PARENT-TEST/students/1/marks'
        self.assertNotIn(b'Fictional exam',p.get(path).data)
        self.assertEqual(self.publish().status_code,302)
        page=p.get(path);self.assertIn(b'Math: 80 / 100',page.data);self.assertIn(b'80%',page.data);self.assertNotIn(b'27 / 100',page.data)
        self.assertEqual(p.get('/parents/PARENT-TEST/students/2/marks').status_code,404)
        self.assertIn(b'80 / 100',p.get('/parents/PARENT-TEST/students/1/results').data)
    def test_snapshot_not_silently_updated_and_unpublish_revokes_visibility(self):
        self.seed_exam();self.publish();p=self.parent();path='/parents/PARENT-TEST/students/1/results'
        def edit():self.ops['score'].query.filter_by(award_id=self.award,student_id=1).one().obtained=90
        self.tenant(edit)
        self.assertIn(b'80 / 100',p.get(path).data);self.assertNotIn(b'90 / 100',p.get(path).data)
        self.assertEqual(self.publish().status_code,302);self.assertIn(b'90 / 100',p.get(path).data)
        version=self.review()['version'];self.assertEqual(self.publish(dict(version=version,action='unpublish')).status_code,302)
        self.assertNotIn(b'Fictional exam',p.get(path).data)
    def test_stale_source_versions_incomplete_rows_and_csrf_are_rejected(self):
        self.seed_exam(complete=False)
        self.assertEqual(self.publish().status_code,422)
        def complete():db.session.add(self.ops['score'](award_id=self.award,student_id=2,paper=0,obtained=27,state=''))
        self.tenant(complete);stale=self.review()
        def change():self.ops['score'].query.filter_by(award_id=self.award,student_id=1).one().obtained=81
        self.tenant(change);self.assertEqual(self.publish(stale).status_code,422)
        self.assertEqual(self.publish(dict(self.review(),fingerprint='🔥')).status_code,422)
        self.assertEqual(self.c.post(f'/workspace/general/parents/exams/{self.award}/publish',data=self.review()).status_code,400)
        data=self.review();self.assertEqual(self.publish(data).status_code,302);self.assertEqual(self.publish(data).status_code,422)
    def test_parent_cannot_publish_and_fee_privileges_still_apply(self):
        self.seed_exam();self.publish();p=self.parent()
        self.assertEqual(p.post(f'/workspace/general/parents/exams/{self.award}/publish',data={}).status_code,302)
        p=self.parent()
        self.tenant(lambda:db.session.add(self.ops['bill'](student_id=1,month='2026-01',due=__import__('datetime').date(2026,1,10),lines=[dict(particular='Tuition',amount=10000)])))
        self.assertEqual(self.post('/workspace/general/parents/privileges',dict(version='0',action='rules',marks_1='block',results_1='block')).status_code,302)
        self.assertEqual(p.get('/parents/PARENT-TEST/students/1/marks').status_code,403)
        self.assertEqual(p.get('/parents/PARENT-TEST/students/1/results').status_code,403)
        self.assertEqual(p.get('/parents/PARENT-TEST/students/1/fees').status_code,200)

if __name__=='__main__':unittest.main()
