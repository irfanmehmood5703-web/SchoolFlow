"""FCM registration and dispatch tests: no real Firebase credentials or network."""
import json,time,unittest
from unittest.mock import patch
from tests import test_parents_ptm as fixture
from app import app,db
from school_clock import school_today
from firebase_push import message

class FirebasePushTests(unittest.TestCase):
    password=fixture.ParentsPtmTests.password
    setUp=fixture.ParentsPtmTests.setUp
    tearDown=fixture.ParentsPtmTests.tearDown
    tenant=fixture.ParentsPtmTests.tenant
    token=fixture.ParentsPtmTests.token
    owner=fixture.ParentsPtmTests.owner
    post=fixture.ParentsPtmTests.post
    credential=fixture.ParentsPtmTests.credential
    parent=fixture.ParentsPtmTests.parent
    def test_private_push_payload_contains_only_opaque_digests(self):
        payload=message('fictional-token','a'*64,['b'*64], 'com.schoolflow.schools.s'+'c'*32+'.owner.test')
        m=payload['message']
        self.assertEqual(set(m['data']),{'kind','actor','ids'})
        self.assertNotIn('notification',m)
        self.assertEqual(m['android']['restricted_package_name'],'com.schoolflow.schools.s'+'c'*32+'.owner.test')
    def test_disabled_transport_does_not_register(self):
        path='/owner-app/notification-feed'
        with patch('firebase_push.credentials',return_value=None):
            r=self.c.get(path);self.assertEqual(r.status_code,200);self.assertNotIn('push_enabled',r.json)
            self.assertEqual(self.post(path,{'push_token':'fictional-token-0000000000','package':'invalid'}).status_code,200)
        self.assertEqual(app.extensions['firebase_push_helpers']['model'].query.count(),0)
    def test_owner_registers_only_matching_package_then_pushes_new_event_once(self):
        path='/owner-app/notification-feed'
        H=app.extensions['firebase_push_helpers'];Lease=H['model'];S=app.extensions['identity_models']['institute']
        scope=S.query.filter_by(code='PARENT-TEST').one().storage_key
        package='com.schoolflow.schools.s'+scope+'.owner.test'
        token='fictional-token-0000000000000000'
        with patch('firebase_push.credentials',return_value={'project_id':'fictional'}),patch('firebase_push.Transport.send',return_value='submitted') as send:
            r=self.c.get(path);self.assertEqual(r.status_code,200);self.assertTrue(r.json['push_enabled'])
            self.assertEqual(self.c.post(path,data={'push_token':token,'package':package}).status_code,400)
            self.assertEqual(self.post(path,{'push_token':token,'package':package.replace('.owner.','.teacher.')}).status_code,422)
            self.assertTrue(self.post(path,{'push_token':token,'package':package}).json['push_registered'])
            db.session.remove();row=Lease.query.one()
            self.assertNotIn(token.encode(),row.encrypted);self.assertEqual(row.actor,r.json['actor'])
            row.checked=0;db.session.commit()
            self.assertEqual(H['tick'](),0);send.assert_not_called()
            L=app.extensions['general_leave_model']
            self.tenant(lambda:db.session.add(L(institute_scope=scope,student_id=1,from_date=school_today(),to_date=school_today(),leave_type='Sick Leave',reason='Fictional request')))
            db.session.remove();row=Lease.query.one();row.checked=0;db.session.commit()
            self.assertEqual(H['tick'](),1);send.assert_called_once()
            args=send.call_args.args;self.assertEqual(args[1],token);self.assertEqual(args[2],r.json['actor'])
            self.assertTrue(all(len(i)==64 for i in args[3]))
            db.session.remove();row=Lease.query.one();row.checked=0;db.session.commit()
            self.assertEqual(H['tick'](),0);send.assert_called_once()
            # Revocation is rechecked before any subsequent push.
            O=app.extensions['identity_models']['owner'];owner=O.query.filter_by(institute_id=self.school).one();owner.version+=1;db.session.commit()
            row=Lease.query.one();row.checked=0;db.session.commit()
            self.assertEqual(H['tick'](),0);send.assert_called_once()
            db.session.remove();self.assertEqual(Lease.query.count(),0)
