'use strict';
const {chromium}=require(process.env.SCHOOLFLOW_PLAYWRIGHT_MODULE||'playwright');
const fs=require('fs');
const base='http://127.0.0.1:5055',path='/workspace/fees/add-amount?from=2027-01&to=2027-04';
const assert=(condition,message)=>{if(!condition)throw Error(message);};
(async()=>{
 for(let n=0;n<60;n++){try{if((await fetch(base+path)).ok)break;}catch{}if(n===59)throw Error('QA server not ready');await new Promise(r=>setTimeout(r,500));}
 const browser=await chromium.launch({headless:true});const page=await browser.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message));
 fs.mkdirSync('/tmp/challan-amount-ui',{recursive:true});
 const row=id=>page.locator('tbody tr').filter({has:page.locator('[data-amount-id][value="'+id+'"]')});
 async function review(id,amount,mode='absolute',direction='increase'){
  await page.locator('[data-amount-id][value="'+id+'"]').check();await page.locator('[data-change-open]').click();
  await page.selectOption('#amount-head','Books Payment');await page.locator('input[name=change_by][value='+mode+']').check();await page.locator('input[name=direction][value='+direction+']').check();await page.fill('#change-amount',amount);
  await page.locator('#challan-change-form button[value=preview]').click();await page.waitForFunction(()=>document.querySelector('[name=review_token]').value.length>20);
 }
 async function apply(){await Promise.all([page.waitForEvent('load'),page.locator('#challan-change-form button[value=apply]').click()]);await page.waitForLoadState('networkidle');}
 for(const width of [390,1440]){
  const id=width===390?1:2;await page.setViewportSize({width,height:width===390?844:1000});await page.goto(base+path);
  assert(await row(4).locator('[data-amount-id]').isDisabled(),'Frozen challan selectable');assert(await page.locator('[data-change-open]').isDisabled(),'No-selection action active');
  await page.screenshot({path:'/tmp/challan-amount-ui/list-'+width+'.png',fullPage:true});
  await review(id,'200');assert((await page.textContent('[data-change-preview]')).includes('3,700'),'Incorrect increase preview');
  assert(!await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),'Page overflow '+width);
  assert(!await page.locator('#challan-change-dialog').evaluate(el=>el.scrollWidth>el.clientWidth+1),'Drawer overflow '+width);
  await page.screenshot({path:'/tmp/challan-amount-ui/review-'+width+'.png',fullPage:true});
  if(width===390){
   let lost=false;await page.route('**/fees/add-amount/apply',async route=>{await route.fetch();lost=true;await route.abort('failed');});
   await page.locator('#challan-change-form button[value=apply]').click();await page.waitForFunction(()=>!document.querySelector('[data-change-error]').hidden);
   assert(lost,'Did not simulate lost successful reply');await page.unroute('**/fees/add-amount/apply');await page.reload();await page.waitForSelector('#challan-change-dialog[open]');
   assert((await page.textContent('#challan-change-form button[value=apply]')).includes('Retry'),'Reload recovery missing');await apply();
  }else await apply();
  assert((await row(id).textContent()).includes('3,700'),'Saved addition/retry doubled or missing');
  await review(id,'10','percentage');assert((await page.textContent('[data-change-preview]')).includes('220'),'Percentage is not based on selected head');await apply();
  await review(id,'20','absolute','decrease');await apply();assert((await row(id).textContent()).includes('3,700'),'Decrease incorrect');
  await row(id).getByRole('link',{name:'History',exact:true}).click();assert((await page.textContent('body')).includes('Fictional UI Child'),'History inaccessible');
  await page.getByRole('button',{name:'Print updated challan',exact:true}).click();await page.waitForLoadState('networkidle');assert((await page.textContent('body')).includes('3,700'),'Printed total stale');
  console.log('PASS Add Amount '+width+'px: selection, drawer, reviewed increase/decrease/percentage, exact-once retry, history and saved print');
 }
 await page.goto(base+path);await review(3,'50');await apply();const full=await row(3).textContent();assert(full.includes('Partially Paid')&&full.includes('3,550')&&full.includes('3,500'),'Fully paid receipt not preserved after reopening');
 await page.locator('[data-amount-id][value="1"]').check();await page.locator('[data-amount-id][value="2"]').check();await page.locator('[data-change-open]').click();await page.selectOption('#amount-head','Books Payment');await page.fill('#change-amount','10');await page.locator('#challan-change-form button[value=preview]').click();await page.waitForFunction(()=>document.querySelector('[name=review_token]').value.length>20);assert((await page.textContent('[data-change-preview]')).includes('Review 2 challan'),'Batch preview missing');await apply();
 for(const id of [1,2])assert((await row(id).textContent()).includes('3,710'),'Batch saved incorrect total');
 assert(!errors.length,errors.join('\n'));console.log('PASS Fully paid reopening, partial balance preservation, atomic multi-challan change and no browser errors');await browser.close();
})().catch(e=>{console.error(e);process.exit(1);});
