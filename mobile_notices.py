"""Small, authenticated mobile notification feeds; no public topics or credentials."""
import hashlib,hmac,json
from flask import current_app,jsonify

def feed(role,scope,actor,events):
    # Never expose internal identifiers to the native deduplication cache.
    secret=str(current_app.config['SECRET_KEY']).encode()
    def opaque(value):return hmac.new(secret,json.dumps(value,sort_keys=True,default=str).encode(),hashlib.sha256).hexdigest()
    result=[]
    for item in events[:80]:
        if item.get('read'):continue
        result.append(dict(id=opaque([role,scope,actor,item['key'],item['revision']]),title=str(item['title'])[:120],body=str(item.get('detail',item.get('body','')))[:500]))
    response=jsonify(actor=opaque([role,scope,actor]),events=result)
    response.headers['Cache-Control']='private, no-store'
    return response
