'use strict';
const {chromium}=require(process.env.SCHOOLFLOW_PLAYWRIGHT_MODULE||'playwright');
const base='http://127.0.0.1:5057',url=base+'/workspace/core/institute';
const assert=(yes,message)=>{if(!yes)throw Error(message);};
(async()=>{
 for(let i=0;i<60;i++){try{if((await fetch(url)).ok)break;}catch{}if(i===59)throw Error('Completion server not ready');await new Promise(r=>setTimeout(r,500));}
 const browser=await chromium.launch({headless:true});let completions=0;
 try{
  for(const width of [390,1440]){
   const page=await browser.newPage({viewport:{width,height:width===390?844:1000}});const errors=[];page.on('pageerror',e=>errors.push(e.message));
   await page.goto(url+'#class-map');assert(!await page.locator('#class-map form').evaluate(el=>el.checkValidity()),'Unused class editor should be empty and invalid');
   // Reproduce the old response without a fragment: a successful POST lands
   // back at the URL's stale class-map anchor, hiding the saved completion.
   await page.route('**/workspace/core/institute',async route=>{
    const req=route.request();if(req.method()==='POST'&&new URLSearchParams(req.postData()).get('action')==='complete_setup'){
     const response=await route.fetch({maxRedirects:0});const headers=response.headers();headers.location=headers.location.split('#')[0];await route.fulfill({response,headers});
    }else await route.continue();
   });
   await page.getByRole('button',{name:'Complete reviewed institute setup',exact:true}).click();await page.waitForLoadState('networkidle');
   assert(new URL(page.url()).hash==='#class-map','Old redirect did not reproduce stale fragment inheritance');assert(await page.locator('[data-setup-completed]').count()===1,'Old flow did not actually save completion');completions++;
   await page.unroute('**/workspace/core/institute');await page.goto(url+'#class-map');
   const response=page.waitForResponse(r=>r.request().method()==='POST'&&new URL(r.url()).pathname==='/workspace/core/institute');
   await page.getByRole('button',{name:'Complete reviewed institute setup',exact:true}).click();assert((await response).status()===302,'Completion did not submit');
   await page.waitForURL('**/institute#setup-readiness');await page.waitForLoadState('networkidle');await page.waitForFunction(()=>{const y=document.querySelector('#setup-readiness').getBoundingClientRect().top;return y>=-2&&y<150;});
   assert(await page.locator('[data-setup-completed]').isVisible(),'Saved completion confirmation hidden');assert((await page.locator('[data-setup-completed]').textContent()).includes('Setup completed:'),'No completed-state message');completions++;
   const state=await (await page.request.get(base+'/qa/state')).json();assert(state.activated&&state.completions===completions,'Completion marker/audit not saved exactly once per click');assert(!state.students&&!state.bills&&!state.salaries,'Completion created operational records');
   await page.screenshot({path:'/tmp/sf-fee-scope-completed-'+width+'.png'});
   // Saving academic dates from a class-map URL must also select its own anchor.
   await page.goto(url+'#class-map');await page.getByRole('button',{name:'Save academic year',exact:true}).click();await page.waitForURL('**/institute#academic-year');await page.waitForLoadState('networkidle');
   assert(!errors.length,errors.join('\n'));console.log('PASS Setup completion '+width+'px: reproduced old successful-save scroll, unused forms do not block completion, checklist anchor and completed status visible, academic anchor, no student/bill/salary writes');await page.close();
  }
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1);});
