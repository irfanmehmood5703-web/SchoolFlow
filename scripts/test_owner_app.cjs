'use strict';
const {chromium}=require(process.env.SCHOOLFLOW_PLAYWRIGHT_MODULE||'playwright');
const fs=require('fs');
const output=process.env.OWNER_UI_OUTPUT||'/tmp/owner-app-ui';let activePage;
(async()=>{
 const browser=await chromium.launch({headless:true,...(process.env.SCHOOLFLOW_CHROMIUM_PATH?{executablePath:process.env.SCHOOLFLOW_CHROMIUM_PATH,args:['--no-sandbox']}: {})});
 fs.mkdirSync(output,{recursive:true});const entry=fs.readFileSync(process.env.OWNER_UI_ENTRY_FILE||'/tmp/owner-ui-entry.txt','utf8').trim();
 for(const width of [390,1280]){
  const context=await browser.newContext({viewport:{width,height:844}});const page=await context.newPage();activePage=page;const errors=[];console.log('Owner UI '+width+'px: signing in');page.on('pageerror',e=>errors.push(String(e)));
  await page.goto('http://localhost:5057'+entry);await page.locator('input[name=email]').fill('owner@example.invalid');await page.locator('input[name=password]').fill('Fictional-owner-2026-password');await page.getByRole('button',{name:'Sign in →',exact:true}).click();await page.waitForURL('**/owner-app');
  const check=async label=>{if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1))throw Error(label+' overflow '+width);if(errors.length)throw Error(errors.join('\n'));};
  await check('home');await page.screenshot({path:`${output}/home-${width}.png`});
  await page.locator('[data-open="campus-dialog"]').click();await page.getByRole('radio',{name:'North',exact:true}).check();await page.getByRole('button',{name:'Show campus figures'}).click();await page.waitForURL('**/owner-app?campus=North&month=*');await check('campus');
  await page.locator('.bottom-nav').getByRole('link',{name:'Reports',exact:true}).click();await page.waitForURL('**/owner-app/reports?*');await check('reports');await page.screenshot({path:`${output}/reports-${width}.png`});
  if(await page.getByRole('button',{name:'Favourite: Active Students',exact:true}).getAttribute('aria-pressed')!=='true')await page.getByRole('button',{name:'Favourite: Active Students',exact:true}).click();await page.waitForLoadState('networkidle');if(await page.getByRole('button',{name:'Favourite: Active Students',exact:true}).getAttribute('aria-pressed')!=='true')throw Error('favourite was not saved');
  if(await page.getByRole('button',{name:'Pin to Home: Active Students',exact:true}).getAttribute('aria-pressed')!=='true')await page.getByRole('button',{name:'Pin to Home: Active Students',exact:true}).click();await page.waitForLoadState('networkidle');await page.reload();if(await page.getByRole('button',{name:'Pin to Home: Active Students',exact:true}).getAttribute('aria-pressed')!=='true')throw Error('pin lost after refresh');
  await page.getByRole('button',{name:'Favourites',exact:true}).click();if(!(await page.locator('[data-favourite=yes]').count()))throw Error('no saved favourite');await page.getByRole('button',{name:'Show all reports',exact:true}).click();
  await page.locator('.bottom-nav').getByRole('link',{name:'Approvals',exact:true}).click();await page.waitForURL('**/owner-app/approvals?*');await page.getByRole('link',{name:'Employees',exact:true}).click();await page.locator('.segmented').getByRole('link',{name:/Approved/}).click();await check('approval filters');await page.screenshot({path:`${output}/approvals-${width}.png`});
  await page.locator('.bottom-nav').getByRole('link',{name:'Connect',exact:true}).click();await page.waitForURL('**/owner-app/connect?*');await check('connect');await page.screenshot({path:`${output}/connect-${width}.png`});
  await page.getByRole('link',{name:/Reminders & To-dos/}).click();await page.locator('input[name=text]').fill('Fictional browser follow-up');await page.getByRole('button',{name:'Add reminder',exact:true}).click();await page.waitForLoadState('networkidle');if(!(await page.textContent('body')).includes('Fictional browser follow-up'))throw Error('reminder missing');
  await page.getByRole('link',{name:'Notifications',exact:true}).click();await page.waitForLoadState('networkidle');await check('notifications');await page.getByRole('button',{name:'Mark displayed as read'}).click();await page.waitForLoadState('networkidle');
  await page.getByRole('link',{name:'Profile and settings'}).click();await page.getByRole('link',{name:'Users & Privileges',exact:true}).click();const frame=page.frameLocator('iframe');await frame.locator('body').waitFor();if(await frame.locator('.app-header').isVisible())throw Error('desktop navigation visible in detail');await check('detail');
  console.log(`PASS Owner ${width}px: real login, campus switch, saved pin/favourite, approval filters, reminders, notifications and compact detail`);await context.close();
 }
 await browser.close();
})().catch(async e=>{console.error(e);if(activePage&&!activePage.isClosed()){try{await activePage.screenshot({path:output+'/failure.png'});fs.writeFileSync(output+'/failure.html',await activePage.content());}catch{}}process.exit(1)});
