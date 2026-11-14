"""Shared identities and scopes for help, support and personal notices."""
import hashlib,hmac,json,secrets
from flask import abort,g,request,session

def actor(app):
    identity=getattr(g,'school_identity',None) or {};staff=getattr(g,'staff_principal',None)
    if staff:return dict(key='staff:'+str(staff.id),label=staff.username,role='Staff',school_id=session.get('institute_id'),school_code=identity.get('code',''),demo=False)
    if session.get('owner_id'):return dict(key='owner:'+str(session['owner_id']),label='School owner',role='Owner',school_id=session.get('institute_id'),school_code=identity.get('code',''),demo=False)
    if session.get('demo') or (app.testing and not app.config.get('IDENTITY_ENFORCE_IN_TESTS')):
        return dict(key='demo:'+session.setdefault('workspace_actor_token',secrets.token_urlsafe(24)),label='Demo user',role='Demo',school_id=None,school_code='DEMO',demo=True)
    abort(403)

def scopes(app,permission):
    staff=getattr(g,'staff_principal',None)
    return set(app.extensions['staff_access_helpers']['grant'](staff,permission)) if staff is not None else None

def stamp(app):
    staff=getattr(g,'staff_principal',None)
    if staff is None:return 'owner'
    raw=json.dumps(dict(version=staff.version,campuses=staff.data.get('campuses',[]),permissions=staff.data.get('permissions',{})),sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()

def csrf():
    if request.method=='POST' and (not request.form.get('_csrf') or not hmac.compare_digest(request.form['_csrf'],session.get('record_csrf',''))):abort(400,'Reload this page before submitting.')
