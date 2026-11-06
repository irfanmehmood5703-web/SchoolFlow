"""Render only a temporary fictional fixture; never connects to a school database."""
import os,tempfile,pathlib,sys,re,json,threading,secrets,argparse
from datetime import date,datetime,timezone

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--out',required=True);parser.add_argument('--chrome',required=True);args=parser.parse_args()
    out=pathlib.Path(args.out);out.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='schoolflow-visual-') as root:
        os.environ.update(DATABASE_URL='sqlite:///'+root+'/control.db',INSTITUTE_DATABASE_DIR=root+'/institutes',SECRET_KEY='fictional-browser-check-only-not-a-school-secret',PUBLIC_DEMO_ENABLED='0',SCHOOLFLOW_FINE_WORKER='0')
        sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
        from app import app,db,Student
        from flask import g
        from werkzeug.serving import make_server
        from playwright.sync_api import sync_playwright
        from reportlab.pdfgen import canvas
        with app.app_context():
            H=app.extensions['identity_helpers'];school=H['provision']('QA-CHECK','SchoolFlow Visual QA','owner@qa.invalid','Fictional-QA-Password-2026');sid=school.id;owner=app.extensions['identity_models']['owner'].query.filter_by(institute_id=sid).one().id
            engine=H['engine'](sid);db.session.remove()
            with app.test_request_context('/'):
                g.institute_engine=engine;rm=app.extensions['record_models'];fm=app.extensions['finance_models'];lm=app.extensions['ledger_models'];ops=app.extensions['ops_models'];R=app.extensions['requisition_models'];today=app.extensions['ledger_helpers']['today']();year=today.year
                stamp=dict(created_at=datetime.now(timezone.utc),updated_at=datetime.now(timezone.utc),created_by='Fictional QA',updated_by='Fictional QA')
                db.session.add_all([rm['settings'](category='campus',value='QA Campus',class_name=''),rm['settings'](category='class_name',value='One',class_name='')])
                groups={}
                for cls in ('Assets','Expense','Income','Liabilities'):
                    x=fm['group'](name='QA '+cls,account_class=cls,active=True,**stamp);db.session.add(x);db.session.flush();groups[cls]=x.id
                accts={}
                for code,name,cls in ((1000,'Cash','Assets'),(1001,'Staff Advances','Assets'),(5000,'Learning Supplies','Expense'),(4100,'Fee Income','Income'),(2100,'Payable to staff','Liabilities')):
                    x=fm['account'](code=code,name=name,group_id=groups[cls],inactive=False,**stamp);db.session.add(x);db.session.flush();accts[name]=x.id
                period=fm['period'](begin=date(year,1,1),end=date(year,12,31),closed=False,**stamp);db.session.add(period);db.session.flush()
                from requisitions import DEFAULTS
                db.session.add(R['config'](id=1,data={**DEFAULTS,'advance_account':accts['Staff Advances'],'pay_account':accts['Cash'],'payable_account':accts['Payable to staff']}))
                for i in range(1,4):db.session.add(R['request'](number='QA-'+str(i),campus='QA Campus',actor_key='owner:'+str(owner),raised_by='Fictional Owner',category='Procurement / Supplies',purpose='Learning materials for classroom '+str(i),items=[dict(item='Exercise books',qty='1',unit_price=2000,amount=2000)],estimated=2000,approved=2000,status='Approved',token=secrets.token_urlsafe(32),fingerprint='qa'))
                for i in range(1,21):
                    s=Student(admission_no='QA-'+str(i).zfill(3),name='Fictional Pupil '+str(i).zfill(2),father='Fictional Guardian '+str(i),class_name='One',status='Active');db.session.add(s);db.session.flush();db.session.add(rm['student'](student_id=s.id,data=dict(campus='QA Campus',section='A',academic_session=str(year),roll_no=str(i))))
                    db.session.flush()
                    for m in range(1,11):
                        b=ops['bill'](student_id=s.id,month=f'{year}-{m:02}',due=date(year,m,10),lines=[dict(particular='Tuition',amount=10000)],paid=4000,discount=500);db.session.add(b);db.session.flush();db.session.add(ops['receipt'](student_id=s.id,bill_id=b.id,amount=4000,discount=500,day=date(year,m,1),account='Cash',token='visual-'+str(b.id)))
                for i in range(1,21):
                    j=lm['journal'](token=secrets.token_urlsafe(32),fingerprint='qa',day=today,campus='QA Campus',kind='journal',period_id=period.id,actor='Fictional Owner',actor_key='owner:'+str(owner));db.session.add(j);db.session.flush()
                    for key,d,c in [('Cash',10000,0),('Fee Income',0,10000)]:
                        a=db.session.get(fm['account'],accts[key]);db.session.add(lm['line'](journal_id=j.id,account_id=a.id,debit=d,credit=c,memo='Fictional fee receipt '+str(i),snapshot=app.extensions['ledger_helpers']['snapshot'](a)))
                    db.session.add(lm['note'](journal_id=j.id,narration='Fictional fee receipt '+str(i)))
                db.session.commit();db.session.remove()
        server=make_server('127.0.0.1',0,app,threaded=True);threading.Thread(target=server.serve_forever,daemon=True).start();base='http://127.0.0.1:'+str(server.server_port)
        invoice=out/'fictional-bill.pdf';pdf=canvas.Canvas(str(invoice));pdf.drawString(60,760,'Fictional bill - Learning supplies - 15.00');pdf.save()
        checks=[];overflows=[];errors=[]
        with sync_playwright() as pw:
            browser=pw.chromium.launch(executable_path=args.chrome,headless=True,args=['--no-sandbox','--disable-dev-shm-usage','--single-process','--no-zygote'])
            context=browser.new_context(viewport={'width':1366,'height':900});page=context.new_page();page.on('pageerror',lambda e:errors.append(str(e)))
            page.goto(base+'/auth/institute');page.locator('#code').fill('QA-CHECK');page.locator('form button').click();page.locator('#email').fill('owner@qa.invalid');page.locator('#password').fill('Fictional-QA-Password-2026');page.locator('form button').click();page.wait_for_url('**/workspace/dashboard');checks.append('actual two-step web sign-in')
            page.goto(base+'/workspace/finance/requisitions/1/posting/issue');page.locator('input[name=amount]').fill('20');page.locator('select[name=account_id]').select_option(str(accts['Cash']));page.get_by_role('button',name='Post issue',exact=True).click();page.wait_for_load_state();assert 'Voucher #' in page.inner_text('body');checks.append('browser issue20')
            page.goto(base+'/workspace/finance/requisitions/1/posting/bill');page.locator('input[name=reference]').fill('Fictional Bill 001');page.locator('select[name=expense_account]').select_option(str(accts['Learning Supplies']));page.locator('input[name=expense_amount]').fill('10');page.locator('#req-add-expense').click();page.locator('select[name=expense_account]').nth(1).select_option(str(accts['Learning Supplies']));page.locator('input[name=expense_amount]').nth(1).fill('5');page.locator('input[name=bill_file]').set_input_files(str(invoice));page.get_by_role('button',name='Post bill',exact=True).click();page.wait_for_load_state();assert 'Download bill' in page.inner_text('body');checks.append('browser split bill15 with attachment')
            pages=[('issue','/workspace/finance/requisitions/issue'),('settle','/workspace/finance/requisitions/settle'),('bill','/workspace/finance/requisitions/1/posting/bill'),('return','/workspace/finance/requisitions/1/posting/return'),('carry','/workspace/finance/requisitions/1/posting/carry'),('settings','/workspace/finance/requisitions/settings'),('register','/workspace/finance/requisitions/reports?tab=register'),('ageing','/workspace/finance/requisitions/reports'),('fee-summary',f'/workspace/finance/audit/fees?from={year}-01-01&to={year}-12-31'),('fee-students',f'/workspace/finance/audit/fees?from={year}-01-01&to={year}-12-31&tab=students'),('general',f'/workspace/finance/reports/general?from={year}-01-01&to={year}-12-31'),('voucher','/workspace/finance/ledger/voucher/1')]
            for width,height in ((390,844),(1366,900)):
                page.set_viewport_size({'width':width,'height':height})
                for name,path in pages:
                    response=page.goto(base+path);assert response.status==200,(path,response.status);page.screenshot(path=str(out/f'{name}-{width}.png'),full_page=True)
                    sizes=page.evaluate('({w:innerWidth,body:document.documentElement.scrollWidth})')
                    if sizes['body']>width+1:overflows.append(dict(page=name,width=width,body=sizes['body']))
                    checks.append(f'{name} renders at {width}')
            page.set_viewport_size({'width':1366,'height':900})
            for name,path in [('register','/workspace/finance/requisitions/reports?tab=register&print=1'),('fee-students',f'/workspace/finance/audit/fees?from={year}-01-01&to={year}-12-31&tab=students&print=1'),('general',f'/workspace/finance/reports/general?from={year}-01-01&to={year}-12-31&print=1')]:
                page.goto(base+path);page.pdf(path=str(out/f'{name}.pdf'),format='A4',print_background=True,prefer_css_page_size=True,margin={'top':'10mm','bottom':'10mm','left':'10mm','right':'10mm'});checks.append(name+' PDF generated')
            browser.close()
        server.shutdown();(out/'browser-checks.json').write_text(json.dumps(dict(checks=checks,overflows=overflows,page_errors=errors),indent=2));print(json.dumps(dict(checks=len(checks),overflows=overflows,page_errors=errors),indent=2))

if __name__=='__main__':main()
