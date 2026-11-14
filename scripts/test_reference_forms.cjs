const {chromium}=require(process.env.SCHOOLFLOW_PLAYWRIGHT_MODULE || 'playwright');
(async()=>{for(let attempt=0;attempt<60;attempt++){try{const r=await fetch('http://127.0.0.1:5055/workspace/general/diary');if(r.ok)break;}catch(e){}if(attempt===59)throw Error('UI QA server did not start');await new Promise(r=>setTimeout(r,500));}
const browser=await chromium.launch({headless:true});const page=await browser.newPage({viewport:{width:390,height:844}});page.on('pageerror',e=>{throw e});
for (const width of [390,1440]) {
await page.setViewportSize({width,height:width===390?844:1000});
await page.goto('http://127.0.0.1:5055/workspace/how-to');
if(await page.locator('.help-card').count()!==97)throw Error('How To guide coverage');
if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1))throw Error('How To horizontal overflow at '+width);
const navY=await page.locator('.help-categories').evaluate(el=>el.getBoundingClientRect().top);
await page.locator('.help-results').evaluate(el=>el.scrollTop=400);
if(await page.locator('.help-results').evaluate(el=>el.scrollTop)<300)throw Error('articles do not scroll');
if(Math.abs(await page.locator('.help-categories').evaluate(el=>el.getBoundingClientRect().top)-navY)>1)throw Error('categories moved with articles');
await page.locator('.help-categories a').filter({hasText:'Finance'}).click();
if(await page.locator('.help-card').count()!==16)throw Error('Finance category filter');
if(!(await page.locator('.help-categories a[aria-current=page]').textContent()).includes('Finance'))throw Error('selected category');
await page.locator('#help-q').fill('requisition');await page.locator('.help-search button').click();
if(await page.locator('.help-card').count()!==6)throw Error('category search');
await page.locator('.help-card h2 a').first().click();
if(!(await page.textContent('.help-detail')).includes('Step by step'))throw Error('missing full instructions');
if(!(await page.locator('.help-detail>.button').getAttribute('href')).startsWith('/workspace/'))throw Error('guide target');
await page.locator('.help-back').click();
await page.locator('#help-q').fill('no-such-guide');await page.locator('.help-search button').click();
if(await page.locator('.help-empty').count()!==1)throw Error('empty search');
console.log('PASS How To '+width+'px: guide coverage, independent scrolling, category, search, reader and empty state');
}
await page.setViewportSize({width:390,height:844});
await page.goto('http://127.0.0.1:5055/workspace/general/diary?new=1');
await page.selectOption('[name=campus]','North');await page.waitForFunction(()=>[...document.querySelector('[name=class_name]').options].some(o=>o.value==='One'));await page.selectOption('[name=class_name]','One');await page.waitForFunction(()=>document.querySelector('#diary-subjects').options.length===2);await page.selectOption('[name=section]','A');await page.selectOption('#diary-subjects',['Math','English']);
if(await page.locator('[data-subject-panel]:visible').count()!==2)throw Error('missing panels');
const math=page.locator('[data-subject-panel]').filter({has:page.locator('legend',{hasText:'Math'})});await math.locator('[data-work-editor=classwork]').fill('Browser Math work');await math.locator('[data-work-editor=homework]').fill('Browser Math homework');
const english=page.locator('[data-subject-panel]').filter({has:page.locator('legend',{hasText:'English'})});await english.locator('[data-work-editor=classwork]').fill('Browser English work');
await page.selectOption('#diary-subjects',['Math']);if(await page.locator('[data-subject-panel]:visible').count()!==1)throw Error('deselection');await page.selectOption('#diary-subjects',['Math','English']);if(await english.locator('[data-work-editor=classwork]').textContent()!=='Browser English work')throw Error('lost work');
await page.screenshot({path:'/tmp/sf-diary-mobile.png',fullPage:true});await page.locator('button[name=action][value=save]').click();await page.waitForURL('**/diary');if(!(await page.textContent('body')).includes('Browser Math homework'))throw Error('diary save');console.log('PASS mobile diary subjects, preserved editors and save');
await page.goto('http://127.0.0.1:5055/workspace/general/ptm/create');await page.selectOption('#ptm-campus','North');await page.waitForFunction(()=>document.querySelector('#ptm-class').options.length>1);await page.selectOption('#ptm-class','One');await page.waitForFunction(()=>document.querySelector('#ptm-sessions').options.length>0);await page.selectOption('#ptm-sessions',['2026-27']);await page.waitForFunction(()=>document.querySelector('#ptm-options-status').textContent!=='Loading meeting choices…');await page.selectOption('#ptm-sections',['A']);await page.waitForSelector('#ptm-students input');await page.selectOption('#ptm-teachers',['1']);await page.fill('[name=day]','2026-11-13');await page.screenshot({path:'/tmp/sf-ptm-mobile.png',fullPage:true});await page.locator('#ptm-create').click();await page.waitForURL('**/meetings');if(!(await page.textContent('body')).includes('Fictional UI Child'))throw Error('ptm save');console.log('PASS mobile PTM dependencies, roster and save');
if(await page.evaluate(()=>document.documentElement.scrollWidth>window.innerWidth+1))throw Error('mobile overflow');
await page.setViewportSize({width:1440,height:1000});await page.goto('http://127.0.0.1:5055/workspace/general/ptm/events?new=1');await page.fill('[name=title]','Browser event');await page.fill('[name=academic_year]','2026-27');await page.fill('[name=starts]','2026-11-13');await page.fill('[name=ends]','2026-11-14');await page.locator('button').filter({hasText:'Create event'}).click();await page.waitForURL('**/events');if(!(await page.textContent('body')).includes('Browser event'))throw Error('event save');console.log('PASS desktop event preferences and save');await browser.close();})().catch(e=>{console.error(e);process.exit(1)});
