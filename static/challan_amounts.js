'use strict';
document.addEventListener('DOMContentLoaded',()=>{
 const dialog=document.querySelector('#challan-change-dialog');if(!dialog)return;
 const form=dialog.querySelector('form'),open=document.querySelector('[data-change-open]'),counter=document.querySelector('[data-amount-selected]'),all=document.querySelector('[data-amount-all]');
 const choices=[...document.querySelectorAll('[data-amount-id]:not(:disabled)')],preview=dialog.querySelector('[data-change-preview]'),error=dialog.querySelector('[data-change-error]'),token=form.elements.review_token,apply=form.querySelector('[value=apply]'),previewButton=form.querySelector('[value=preview]');
 const key=form.dataset.pendingKey,csrf=form.elements._csrf.value;let busy=false,serial=0,pending=null;
 try{pending=JSON.parse(sessionStorage.getItem(key)||'null');if(pending&&(!Array.isArray(pending)||pending.length>110||pending.some(item=>!Array.isArray(item)||item.length!==2||item.some(v=>typeof v!=='string'))))pending=null;}catch{}
 const remember=fields=>{pending=fields;try{sessionStorage.setItem(key,JSON.stringify(fields));}catch{}};
 const forget=()=>{pending=null;try{sessionStorage.removeItem(key);}catch{}};
 const selected=()=>choices.filter(box=>box.checked);
 const sync=()=>{const n=selected().length;counter.textContent=n+' selected';open.disabled=!n&&!pending;open.textContent=pending?'Resume reviewed change':'Change amount…';all.checked=n>0&&n===choices.length;all.indeterminate=n>0&&n<choices.length;};
 const lockControls=disabled=>form.querySelectorAll('input:not([type=hidden]),select,textarea').forEach(el=>{el.disabled=disabled;});
 const invalidate=()=>{if(pending)return;serial++;token.value='';apply.disabled=true;apply.textContent='Apply reviewed change';error.hidden=true;preview.textContent='Details changed. Preview again before applying.';};
 const controls=()=>{const percent=form.elements.change_by.value==='percentage';dialog.querySelector('[data-value-label]').textContent=percent?'Percentage (%)':'Amount (Rs.)';form.elements.amount.max=percent?(form.elements.direction.value==='decrease'?'100':'10000'):'999999999';};
 form.addEventListener('input',invalidate);form.addEventListener('change',()=>{invalidate();controls();});
 const showPending=()=>{
  form.reset();lockControls(false);const ids=form.querySelector('[data-change-ids]');ids.replaceChildren();
  for(const [name,value] of pending){
   if(name==='ids'){const el=document.createElement('input');el.type='hidden';el.name='ids';el.value=value;ids.append(el);}
   else if(name==='direction'||name==='change_by'){form.querySelector('input[name='+name+'][value='+value+']').checked=true;}
   else if(form.elements[name])form.elements[name].value=value;
  }
  dialog.querySelector('[data-dialog-count]').textContent=pending.filter(([n])=>n==='ids').length;
  controls();lockControls(true);apply.disabled=false;apply.textContent='Retry reviewed change';previewButton.disabled=true;
  preview.textContent='A previous submission needs confirmation. Retry this same reviewed change; a saved change will not be added twice. You may close this panel to inspect challan History first.';
  error.hidden=true;dialog.showModal();
 };
 choices.forEach(box=>box.addEventListener('change',sync));all.addEventListener('change',()=>{choices.forEach(box=>{box.checked=all.checked;});sync();});sync();
 open.addEventListener('click',()=>{
  if(pending){showPending();return;}
  const boxes=selected();if(!boxes.length||boxes.length>100)return;
  form.reset();lockControls(false);dialog.querySelector('[data-dialog-count]').textContent=boxes.length;
  const holder=form.querySelector('[data-change-ids]');holder.replaceChildren();
  boxes.forEach(box=>{const input=document.createElement('input');input.type='hidden';input.name='ids';input.value=box.value;holder.append(input);});
  invalidate();preview.textContent='Choose a fee head and an amount to review what each challan becomes.';controls();previewButton.disabled=false;dialog.showModal();
 });
 dialog.querySelectorAll('[data-change-close]').forEach(button=>button.addEventListener('click',()=>{if(!busy){serial++;dialog.close();}}));
 dialog.addEventListener('cancel',event=>{if(busy)event.preventDefault();else serial++;});
 form.addEventListener('submit',async event=>{
  event.preventDefault();if(busy)return;
  const action=event.submitter?.value||'preview';if(action==='apply'&&!token.value)return;
  const data=new FormData();
  if(pending)pending.forEach(([name,value])=>data.append(name,value));else for(const [name,value] of new FormData(form))if(name!=='_csrf')data.append(name,value);
  data.set('_csrf',csrf);if(action==='apply')remember([...data].filter(([name])=>name!=='_csrf'));
  const requestSerial=serial;busy=true;error.hidden=true;lockControls(true);form.querySelectorAll('button').forEach(button=>{button.disabled=true;});
  try{
   const response=await fetch(action==='apply'?form.dataset.applyUrl:form.dataset.previewUrl,{method:'POST',body:data,headers:{Accept:'application/json'},credentials:'same-origin'});
   if(response.redirected)throw Error('Your sign-in changed. Reload the page and sign in again.');
   let result;try{result=await response.json();}catch{const e=Error('The server reply could not be confirmed. Retry this same reviewed change or check History.');e.keepReview=action==='apply';throw e;}
   if(!response.ok){const e=Error(result.error||'The change could not be reviewed.');e.keepReview=action==='apply'&&response.status>=500;throw e;}
   if(action==='apply'){forget();window.location.reload();return;}
   if(requestSerial!==serial||!dialog.open)return;
   preview.innerHTML=result.html;token.value=result.review_token;
  }catch(e){
   const uncertain=action==='apply'&&(e instanceof TypeError||e.keepReview);
   if(!uncertain){forget();token.value='';}
   error.textContent=uncertain?'Submission could not be confirmed. Retry this same reviewed change; it will not be added twice.':e.message||'Connection failed. Preview again before retrying.';error.hidden=false;
  }finally{
   busy=false;lockControls(!!pending);form.querySelectorAll('button').forEach(button=>{button.disabled=false;});apply.disabled=!token.value;previewButton.disabled=!!pending;apply.textContent=pending?'Retry reviewed change':'Apply reviewed change';sync();
  }
 });
 if(pending)showPending();
});
