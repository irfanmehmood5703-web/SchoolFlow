'use strict';
const {chromium}=require(process.env.SCHOOLFLOW_PLAYWRIGHT_MODULE||'playwright');
const base='http://127.0.0.1:5056';const assert=(yes,message)=>{if(!yes)throw Error(message);};
(async()=>{const browser=await chromium.launch({headless:true});try{
 for(const width of [390,1440]){
  const page=await browser.newPage({viewport:{width,height:width===390?844:1000}});const errors=[];page.on('pageerror',e=>errors.push(e.message));
  for(const query of ['?q=NoMatchingFictionalRecord','']){
   await page.goto(base+'/records/student'+query);assert(await page.locator('details[data-advanced]').count()===0,'List unexpectedly has an advanced panel');assert(await page.locator('[data-advanced-toggle]').isHidden(),'Unused advanced toggle is visible');
   const text=await page.textContent('body');assert(text.includes(query?'No records match these filters.':'Fictional visibility child'),'Empty/existing student fixture not shown');
  }
  await page.screenshot({path:'/tmp/sf-fee-scope-advanced-list-'+width+'.png'});
  await page.goto(base+'/records/student/new');const panels=page.locator('details[data-advanced]'),toggle=page.locator('[data-advanced-toggle]');assert(await panels.count()>0,'Admission form missing its actual advanced panels');assert(await toggle.isVisible(),'Useful advanced toggle hidden');
  if((await toggle.textContent()).includes('Hide'))await toggle.click();assert(await page.locator('details[data-advanced][open]').count()===0,'Advanced panels did not close');await toggle.click();assert(await page.locator('details[data-advanced][open]').count()===await panels.count(),'Advanced panels did not open');await toggle.click();assert(await page.locator('details[data-advanced][open]').count()===0,'Second toggle failed');
  assert(!errors.length,errors.join('\n'));console.log('PASS Advanced toggle '+width+'px: hidden on empty/existing student lists, visible and functional on Add Student');await page.close();
 }
}finally{await browser.close();}})().catch(e=>{console.error(e);process.exit(1);});
