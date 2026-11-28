const {chromium}=require(process.env.SCHOOLFLOW_PLAYWRIGHT_MODULE || 'playwright');
const base='http://127.0.0.1:5056',url=base+'/workspace/core/fees/schedules';
(async()=>{
 for(let i=0;i<60;i++){try{if((await fetch(url)).ok)break;}catch{}if(i===59)throw Error('Fictional fee server not ready');await new Promise(r=>setTimeout(r,500));}
 const browser=await chromium.launch({headless:true});
 try{
  for(const width of [390,1440]){
   const page=await browser.newPage({viewport:{width,height:width===390?844:1000}});page.on('pageerror',e=>{throw e});
   await page.goto(url);
   const campus=page.locator('[data-fee-scope=campuses]'),classes=page.locator('[data-fee-scope=classes]'),form=page.locator('#schedule-editor');
   if(await form.locator('select[multiple][name=campuses],select[multiple][name=classes]').count())throw Error('Ambiguous listbox remains');
   for(const group of [campus,classes]){if(await group.locator('input:checked').count())throw Error('New schedule scope was preselected');if(!(await group.locator('[data-scope-count]').textContent()).includes('0 selected'))throw Error('Missing explicit zero-selection state');}
   await page.fill('#name','Fictional scope '+width);await page.fill('#due_day','10');
   const amount=(head)=>page.locator(`[data-fee-schedule-line][data-head-key="${head}"]`).locator('input[name^=amount_]');
   await page.getByText('Add Fee Head',{exact:true}).click();
   await page.locator('#optional-head-select').selectOption({label:'Annual Charges'});
   await page.getByRole('button',{name:'Add selected head',exact:true}).click();
   await amount('Tuition Fee').fill('3500');await amount('Annual Charges').fill('3000');
   await page.getByRole('button',{name:'Create schedules',exact:true}).click();
   if(!(await campus.locator('[data-scope-error]').isVisible()))throw Error('Missing inline campus instruction');
   if(!(await classes.locator('[data-scope-error]').isVisible()))throw Error('Missing inline class instruction');
   if(await page.inputValue('#name')!=='Fictional scope '+width || await amount('Tuition Fee').inputValue()!=='3500')throw Error('Validation lost entered values');
   await page.locator('.fee-schedule-scopes').screenshot({path:'/tmp/sf-fee-scope-empty-'+width+'.png'});
   const north=campus.getByRole('checkbox',{name:'North',exact:true});await north.focus();await north.press('Space');
   if(!(await north.isChecked())||!(await campus.locator('[data-scope-count]').textContent()).includes('1 selected'))throw Error('Keyboard selection failed');
   await campus.getByRole('button',{name:'Select all campuses',exact:true}).click();if(await campus.locator('input:checked').count()!==2)throw Error('Campus select-all failed');
   await campus.getByRole('button',{name:'Clear campuses',exact:true}).click();if(await campus.locator('input:checked').count())throw Error('Campus clear failed');
   await north.check();await campus.getByRole('checkbox',{name:'South',exact:true}).check();
   await classes.getByRole('button',{name:'Select all classes',exact:true}).click();if(await classes.locator('input:checked').count()!==4)throw Error('Class select-all failed');
   await classes.getByRole('button',{name:'Clear classes',exact:true}).click();
   await classes.getByRole('checkbox',{name:'Montessori',exact:true}).check();await classes.getByRole('checkbox',{name:'One',exact:true}).check();
   if(await classes.locator('.is-selected').count()!==2||!(await classes.locator('[data-scope-count]').textContent()).includes('2 selected'))throw Error('Selection appearance/count mismatch');
   if(await campus.locator('[data-scope-error]').isVisible()||await classes.locator('[data-scope-error]').isVisible())throw Error('Resolved errors still shown');
   const payload=await form.evaluate(el=>({campuses:new FormData(el).getAll('campuses'),classes:new FormData(el).getAll('classes')}));
   if(payload.campuses.join('|')!=='North|South'||payload.classes.join('|')!=='Montessori|One')throw Error('Repeated POST fields changed');
   if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1))throw Error('Mobile scope overflow');
   await page.locator('.fee-schedule-scopes').screenshot({path:'/tmp/sf-fee-scope-selected-'+width+'.png'});
   await page.getByRole('button',{name:'Create schedules',exact:true}).click();await page.waitForLoadState('networkidle');
   const savedRows=page.locator('section').filter({has:page.getByRole('heading',{name:'Configured schedules',exact:true})}).locator('tr').filter({hasText:'Fictional scope '+width});
   if(await savedRows.count()!==4)throw Error('Selected campus/class pairs not saved');
   const northMont=savedRows.filter({hasText:'North / Montessori'});await northMont.getByRole('link',{name:'Edit / Duplicate',exact:true}).click();await page.waitForLoadState('networkidle');
   if(!(await campus.getByRole('checkbox',{name:'North',exact:true}).isChecked())||!(await classes.getByRole('checkbox',{name:'Montessori',exact:true}).isChecked())||await campus.locator('input:checked').count()!==1||await classes.locator('input:checked').count()!==1)throw Error('Edit did not retain saved scope');
   if(Number(await amount('Tuition Fee').inputValue())!==3500)throw Error('Scope save changed fee amount');
   await amount('Tuition Fee').fill('3600');await page.getByRole('button',{name:'Save this scope',exact:true}).click();await page.waitForLoadState('networkidle');
   await savedRows.filter({hasText:'South / One'}).getByRole('link',{name:'Edit / Duplicate',exact:true}).click();await page.waitForLoadState('networkidle');
   if(Number(await amount('Tuition Fee').inputValue())!==3500)throw Error('Editing one pair changed another pair');
   if(width===390){
    await page.fill('#name','Fictional duplicate');await campus.getByRole('button',{name:'Clear campuses',exact:true}).click();await north.check();
    await classes.getByRole('button',{name:'Clear classes',exact:true}).click();await classes.getByRole('checkbox',{name:'Two',exact:true}).check();
    await page.getByRole('button',{name:'Duplicate to selected name/scopes',exact:true}).click();await page.waitForLoadState('networkidle');
    const duplicate=page.locator('tr').filter({hasText:'Fictional duplicate'});if(await duplicate.count()!==1||!(await duplicate.textContent()).includes('North / Two'))throw Error('Duplicate scope incorrect');
   }
   console.log('PASS '+width+'px: explicit unchecked choices, inline validation with values retained, keyboard/select-all/clear, exact multi-scope save, edit isolation and duplicate flow');
   await page.close();
  }
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1)});
