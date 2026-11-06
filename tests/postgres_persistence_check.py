"""Opt-in local PostgreSQL/PGlite check. Never run against a hosted database."""
import os,sys,json,pathlib,re,secrets,hashlib
from datetime import datetime,timezone
from urllib.parse import urlsplit
url=urlsplit(os.environ.get('DATABASE_URL',''))
if os.getenv('SCHOOLFLOW_POSTGRES_TEST')!='1' or url.hostname not in ('127.0.0.1','localhost'):
    raise SystemExit('Requires explicit local PostgreSQL test opt-in.')
from app import app,db,Student
from flask import g
app.config.update(TESTING=True,IDENTITY_ENFORCE_IN_TESTS=True)
manifest=pathlib.Path(sys.argv[2]);phase=sys.argv[1];password='Fictional-Postgres-QA-2026'
checks=[]
def ok(name,condition):
    if not condition:raise AssertionError(name)
    checks.append(name)
def login(code):
    c=app.test_client();c.get('/auth/institute')
    with c.session_transaction() as s:token=s['record_csrf']
    c.post('/auth/institute',data=dict(_csrf=token,code=code))
    with c.session_transaction() as s:token=s['record_csrf']
    ok('owner login '+code,c.post('/auth/login',data=dict(_csrf=token,email='owner@qa.invalid',password=password)).status_code==302)
    with c.session_transaction() as s:token=s['record_csrf']
    return c,token
with app.app_context():
    H=app.extensions['identity_helpers'];I=app.extensions['identity_models']['institute'];rm=app.extensions['record_models'];fm=app.extensions['finance_models'];R=app.extensions['requisition_models'];today=app.extensions['ledger_helpers']['today']();now=datetime.now(timezone.utc)
    if phase=='write':
        suffix=secrets.token_hex(4).upper();records=[]
        for letter in ('A','B'):
            code='PGQA-'+suffix+'-'+letter;school=H['provision'](code,'Fictional '+letter,'owner@qa.invalid',password);sid=school.id;engine=H['engine'](sid);db.session.remove()
            with app.test_request_context('/'):
                g.institute_engine=engine
                db.session.add(Student(admission_no='SAME-ID',name='Only school '+letter,class_name='One',status='Active'));db.session.add(rm['settings'](category='campus',value='QA Campus',class_name=''))
                if letter=='A':
                    stamp=dict(created_at=now,updated_at=now,created_by='QA',updated_by='QA');gids={};ids={}
                    for cls in ('Assets','Expense','Liabilities'):
                        group=fm['group'](name='QA '+cls,account_class=cls,active=True,**stamp);db.session.add(group);db.session.flush();gids[cls]=group.id
                    for code_n,name,cls in ((1000,'Cash','Assets'),(1001,'Advances','Assets'),(5000,'Supplies','Expense'),(2100,'Staff payable','Liabilities')):
                        a=fm['account'](code=code_n,name=name,group_id=gids[cls],inactive=False,**stamp);db.session.add(a);db.session.flush();ids[name]=a.id
                    db.session.add(fm['period'](begin=today,end=today,closed=False,**stamp))
                    from requisitions import DEFAULTS
                    db.session.add(R['config'](id=1,data={**DEFAULTS,'advance_account':ids['Advances'],'pay_account':ids['Cash'],'payable_account':ids['Staff payable']}))
                db.session.commit();db.session.remove()
            records.append(dict(code=code,sid=sid,letter=letter))
        for record in records:
            c,token=login(record['code']);body=c.get('/records/student').data
            ok('school isolation '+record['letter'],('Only school '+record['letter']).encode() in body and ('Only school '+('B' if record['letter']=='A' else 'A')).encode() not in body)
        c,token=login(records[0]['code']);base='/workspace/finance/requisitions/'
        r=c.post(base+'mine',data=dict(_csrf=token,post_token=secrets.token_urlsafe(32),campus='QA Campus',category='Procurement / Supplies',purpose='Persistent fictional bill',item=['Supplies'],qty=['1'],unit_price=['20']));ok('raise request',r.status_code==302);rid=int(r.location.rsplit('/',1)[1])
        ok('approve request',c.post(base+str(rid)+'/decide',data=dict(_csrf=token,post_token=secrets.token_urlsafe(32),version='1',decision='Approved',approved='20')).status_code==302)
        ok('PostgreSQL atomic advance',c.post(base+str(rid)+'/posting/issue',data=dict(_csrf=token,post_token=secrets.token_urlsafe(32),version='2',day=today.isoformat(),amount='20',account_id=str(ids['Cash']))).status_code==302)
        import io
        content=b'%PDF-1.4\nFictional persistent attachment\n%%EOF'
        ok('PostgreSQL expense and bytea attachment',c.post(base+str(rid)+'/posting/bill',data=dict(_csrf=token,post_token=secrets.token_urlsafe(32),version='3',day=today.isoformat(),reference='Fictional',expense_account=[str(ids['Supplies'])],expense_amount=['15'],bill_file=(io.BytesIO(content),'bill.pdf')),content_type='multipart/form-data').status_code==302)
        page=c.get(base+str(rid)+'/posting/bill');attachment=re.search(rb'href="([^"]+/attachment/\d+)"',page.data)[1].decode();ok('stored attachment downloaded',c.get(attachment).data==content)
        manifest.write_text(json.dumps(dict(schools=records,attachment=attachment,sha=hashlib.sha256(content).hexdigest(),rid=rid)))
    else:
        data=json.loads(manifest.read_text())
        for record in data['schools']:
            c,token=login(record['code']);body=c.get('/records/student').data
            ok('student survives process/database restart '+record['letter'],('Only school '+record['letter']).encode() in body)
        c,token=login(data['schools'][0]['code']);response=c.get(data['attachment']);ok('attachment survives restart',hashlib.sha256(response.data).hexdigest()==data['sha'])
        body=c.get('/workspace/finance/requisitions/reports').data;ok('advance and ledger survive restart',b'This agrees with your books' in body and b'5.00' in body)
    print(json.dumps(dict(phase=phase,checks=checks)),flush=True)
