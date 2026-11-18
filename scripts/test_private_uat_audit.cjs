'use strict';
const {chromium}=require(process.env.SCHOOLFLOW_PLAYWRIGHT_MODULE||'playwright');const fs=require('fs');
const base='http://127.0.0.1:5058',out='/tmp/schoolflow-uat-audit';fs.mkdirSync(out,{recursive:true});
const assert=(yes,message)=>{if(!yes)throw Error(message);};
async function login(page){await page.goto(base+'/auth/institute');await page.fill('#code','MSG-ONE');await page.getByRole('button',{name:'Proceed →',exact:true}).click();await page.fill('#email','owner@example.invalid');await page.fill('#password','Fictional-messages-password-2026');await page.getByRole('button',{name:'Sign in →',exact:true}).click();await page.waitForURL('**/workspace/dashboard');}
const skip=url=>/\/(?:logo|photo|files|exports|identity-card|qr-image|download)(?:\/|\?|$)/.test(url)||/export=|print=1/.test(url);
(async()=>{
 for(let n=0;n<60;n++){try{if((await fetch(base+'/qa/targets')).ok)break;}catch{}if(n===59)throw Error('Private audit server not ready');await new Promise(r=>setTimeout(r,500));}
 const targets=await (await fetch(base+'/qa/targets')).json();assert(targets.length===106,'Private guide/menu coverage changed');const browser=await chromium.launch({headless:true});const failures=[],results=[];
 try{
  for(const width of [1440,390]){
   const page=await browser.newPage({viewport:{width,height:width===390?844:1000}});await login(page);const pageErrors=[];page.on('pageerror',e=>pageErrors.push(e.message));let active='';page.on('response',r=>{if(r.status()>=500)failures.push({width,url:active,error:'HTTP '+r.status()+' '+r.url()});});
   let urls=new Set(targets.map(t=>t.url).concat(['/records/student','/records/student/new','/records/student/1','/records/employee/new','/workspace/fees/add-amount?from=2027-01&to=2027-03','/workspace/core/institute'])),seen=new Set();
   for(let depth=0;depth<2;depth++){
    const more=new Set();for(const path of [...urls].sort()){
     if(seen.has(path)||skip(path))continue;seen.add(path);active=path;pageErrors.length=0;
     try{
      const response=await page.goto(base+path,{waitUntil:'load'});const expected=path.split('?')[0]==='/workspace/attendance/geo-self'?403:200;assert(response.status()===expected,'Page returned '+response.status());if(expected===403){results.push({width,url:path,status:403,expected:true});continue;}
      assert(!page.url().includes('/auth/'),'Private session unexpectedly signed out');assert(!(await page.textContent('body')).includes('Reference screen pending'),'Unimplemented screen');
      const panels=page.locator('details[data-advanced]'),toggle=page.locator('[data-advanced-toggle]');const count=await panels.count();
      if(await toggle.count()){
       assert(count?await toggle.isVisible():await toggle.isHidden(),'Advanced toggle visibility disagrees with panels: '+count);
       if(count){await toggle.click();let open=await page.locator('details[data-advanced][open]').count();assert(open===count||open===0,'Advanced toggle only changed some panels');await toggle.click();assert(await page.locator('details[data-advanced][open]').count()!==open,'Advanced toggle did nothing');}
      }
      assert(!await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),'Page has horizontal overflow');assert(!pageErrors.length,pageErrors.join('; '));
      for(const href of await page.locator('a[href]').evaluateAll(links=>links.map(a=>a.getAttribute('href')).filter(h=>h.startsWith('/workspace/')||h.startsWith('/records/'))))more.add(href.split('#')[0]);
      results.push({width,url:path,status:response.status(),advancedPanels:count});
      if(['/records/student','/records/student/new','/workspace/core/institute','/workspace/fees/add-amount?from=2027-01&to=2027-03'].includes(path))await page.screenshot({path:out+'/page-'+width+'-'+path.split('?')[0].replaceAll('/','_')+'.png'});
     }catch(error){failures.push({width,url:path,error:error.message});}
    }urls=more;
   }
   console.log('AUDIT '+width+'px: '+seen.size+' private menu/inner pages, '+failures.filter(x=>x.width===width).length+' issue(s)');await page.close();
  }
  // A real browser admission save, refresh and fresh login verify the user's
  // next workflow on fictional data in a private institute.
  const page=await browser.newPage({viewport:{width:390,height:844}});await login(page);await page.goto(base+'/records/student/new');
  await page.fill('#name','Fictional pre-UAT child');await page.selectOption('#gender','Female');await page.fill('#admission_date','2027-01-01');await page.fill('#father','Fictional UAT Guardian');await page.fill('#father_cnic','TEST-ONLY-UAT');await page.fill('#phone','00000000000');await page.selectOption('#guardian_relation','Father');
  for(const [id,value] of [['campus','North'],['class_name','One'],['section','A'],['group_name','General'],['academic_session','2027'],['fee_plan','Common 2027']]){await page.waitForFunction(([id,value])=>[...document.getElementById(id).options].some(o=>o.value===value),[id,value]);await page.selectOption('#'+id,value);}
  await page.fill('#admission_no','QA-UAT-NEW');await page.getByRole('button',{name:'Save and View',exact:true}).click();await page.waitForURL(/\/records\/student\/\d+$/);const sid=new URL(page.url()).pathname.split('/').pop();await page.reload();assert((await page.textContent('body')).includes('Fictional pre-UAT child'),'Student lost after refresh');
  await page.goto(base+'/workspace/student-fee-plans/'+sid+'/edit');await page.fill('#effective','2027-01');await page.fill('#year','2027');await page.getByRole('button',{name:'Create Fee Plan',exact:true}).click();await page.waitForLoadState('load');
  for(const [month,total] of [['2027-01','5,800.00'],['2027-03','6,500.00']]){
   await page.goto(base+'/workspace/student-fee-plans/generate');await page.fill('#month',month);await page.locator('input[name=student_ids][value="'+sid+'"]').check();await page.getByRole('button',{name:'Generate selected challans',exact:true}).click();await page.waitForLoadState('load');assert((await page.textContent('body')).includes(total),'Incorrect generated amount '+month);
  }
  await page.goto(base+'/workspace/fees/payments?q=Fictional%20pre-UAT%20child');const row=page.locator('tbody tr').filter({hasText:'2027-03'});await row.getByRole('link',{name:'Pay this month',exact:true}).click();const amount=page.locator('input[name^=amount_]');await amount.fill('1000');await page.getByRole('button',{name:'Submit payment',exact:true}).click();await page.waitForLoadState('load');await page.goto(base+'/workspace/fees/add-amount?from=2027-03&to=2027-03&q=QA-UAT-NEW');assert((await page.textContent('body')).includes('5,500.00'),'Partial payment remaining balance incorrect');
  const fresh=await browser.newPage();await login(fresh);await fresh.goto(base+'/records/student?q=QA-UAT-NEW');assert((await fresh.textContent('body')).includes('Fictional pre-UAT child'),'Student lost on a fresh private login');
  console.log('PASS Private admission save → refresh → common fee plan → January 5800 / March 6500 → partial payment / remaining 5500 → fresh-login persistence');await fresh.close();await page.close();
 }catch(error){failures.push({stage:'private-admission-fees',error:error.message});}
 finally{await browser.close();fs.writeFileSync(out+'/audit-results.json',JSON.stringify({results,failures},null,2));}
 console.log('AUDIT RESULT '+results.length+' page checks; '+failures.length+' issue(s)');if(failures.length){console.error(JSON.stringify(failures));process.exit(1);}
})().catch(e=>{console.error(e);process.exit(1);});
