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
  await page.goto(base+'/records/student/new');
  const details=page.locator('#student-more-details'), toggle=details.locator('summary').first();
  assert(await toggle.isVisible(),'More Details control is hidden');
  assert(!(await details.evaluate(el=>el.open)),'Optional admission fields are open by default');
  await toggle.click();assert(await details.evaluate(el=>el.open),'Optional admission fields did not open');
  await toggle.click();assert(!(await details.evaluate(el=>el.open)),'Optional admission fields did not close');
  assert(!errors.length,errors.join('\n'));console.log('PASS Advanced toggle '+width+'px: hidden on student lists, More Details works on Add Student');await page.close();
 }
}finally{await browser.close();}})().catch(e=>{console.error(e);process.exit(1);});
