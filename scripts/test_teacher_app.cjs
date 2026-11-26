'use strict';
const {chromium}=require(process.env.SCHOOLFLOW_PLAYWRIGHT_MODULE||'playwright'),fs=require('fs');const output='/tmp/teacher-app-ui';let current;
(async()=>{fs.mkdirSync(output,{recursive:true});const entry=JSON.parse(fs.readFileSync('/tmp/teacher-ui-entry.json','utf8')),browser=await chromium.launch({headless:true});let storage;
// Login must be usable without scrolling through a duplicate website header.
for(const [width,height] of [[320,568],[360,640],[390,844],[1280,800]]){
 const context=await browser.newContext({viewport:{width,height}}),page=await context.newPage();current=page;
 await page.goto('http://localhost:5059'+entry.entry);
 await page.getByRole('heading',{name:'Welcome back',exact:true}).waitFor();
 if(await page.locator('h1').count()!==1||await page.locator('.public-header,.auth-intro').count())throw Error('Duplicate school branding');
 if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1))throw Error('Teacher login overflow '+width);
 const login=page.getByRole('button',{name:/^Sign in(?: →)?$/});
 const bounds=await login.boundingBox();
 if(!bounds||bounds.y+bounds.height>height)throw Error('Sign in below the first screen at '+width);
 await page.locator('[name=password]').fill('Fictional-preview-only');
 await page.getByRole('button',{name:'Show password',exact:true}).click();
 if(await page.locator('[name=password]').getAttribute('type')!=='text')throw Error('Password eye did not reveal password');
 await page.getByRole('button',{name:'Hide password',exact:true}).click();
 if(await page.locator('[name=password]').getAttribute('type')!=='password')throw Error('Password eye did not hide password');
 await page.locator('[name=password]').fill('');
 await page.screenshot({path:`${output}/login-${width}.png`});
 console.log('PASS compact Teacher login '+width+'px');await context.close();
}
for(const width of [390,1280]){const context=await browser.newContext({viewport:{width,height:844},...(storage?{storageState:storage}:{})}),page=await context.newPage();current=page;const errors=[];page.on('pageerror',e=>errors.push(String(e)));const base='http://localhost:5059';if(!storage){await page.goto(base+entry.entry);await page.locator('[name=email]').fill(entry.username);await page.locator('[name=password]').fill(entry.password);await page.getByRole('button',{name:/^Sign in(?: →)?$/}).click();await page.waitForURL(base+'/teacher-app');storage=await context.storageState()}else await page.goto(base+'/teacher-app');
const check=async label=>{if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1))throw Error(label+' overflow '+width);if(errors.length)throw Error(errors.join('\n'));if((await page.textContent('body')).includes('Pupil Campus B'))throw Error('Foreign campus leak')};await check('home');await page.screenshot({path:`${output}/home-${width}.png`});
for(const [key,path] of [['attendance',`/classes/${entry.cid}/attendance`],['diary',`/classes/${entry.cid}/diary`],['materials',`/classes/${entry.cid}/materials`],['exams',`/classes/${entry.cid}/exams`],['salary','/my-salary'],['leave','/requests/leave'],['reminders','/reminders'],['profile','/profile']]){await page.goto(base+'/teacher-app'+path);await check(key);if(key==='attendance'){await page.locator(`[name=status_${entry.pupil}]`).selectOption(width===390?'Absent':'Present');await page.getByRole('button',{name:'Save attendance',exact:true}).click();await page.waitForLoadState('networkidle');await page.reload();if(await page.locator(`[name=status_${entry.pupil}]`).inputValue()!==(width===390?'Absent':'Present'))throw Error('Attendance not persisted')}
if(key==='leave'&&width===390){await page.locator('[name=type]').selectOption('Leave');await page.locator('[data-leave-from]').fill('2026-11-21');await page.locator('[data-leave-to]').fill('2026-11-21');await page.locator('[name=reason]').fill('Fictional browser leave');await page.getByRole('button',{name:'Submit request',exact:true}).click();await page.waitForLoadState('networkidle');if(!(await page.textContent('body')).includes('Fictional browser leave'))throw Error('Leave not saved')}
await check(key);await page.screenshot({path:`${output}/${key}-${width}.png`})}
console.log('PASS Teacher '+width+'px: login, assigned class isolation, persisted attendance, personal records, leave and reminders');await context.close()}
await browser.close()})().catch(async e=>{console.error(e);if(current&&!current.isClosed())try{await current.screenshot({path:output+'/failure.png'});fs.writeFileSync(output+'/failure.html',await current.content())}catch{}process.exit(1)});
