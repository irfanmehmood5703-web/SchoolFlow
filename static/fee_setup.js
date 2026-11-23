'use strict';
document.addEventListener('DOMContentLoaded',()=>{
 const groups=[...document.querySelectorAll('[data-fee-scope]')];
 const updateScope=group=>{
  const boxes=[...group.querySelectorAll('input[type=checkbox]')],count=boxes.filter(box=>box.checked).length;
  const error=group.querySelector('[data-scope-error]'),valid=count>0&&(!group.hasAttribute('data-scope-single')||count===1);
  group.querySelector('[data-scope-count]').textContent=count+' selected';
  boxes.forEach(box=>box.closest('label').classList.toggle('is-selected',box.checked));
  if(boxes.length){boxes[0].setCustomValidity(valid?'':error.textContent.trim());if(valid)boxes[0].removeAttribute('aria-invalid');}
  if(valid){error.hidden=true;group.classList.remove('has-error');}
  return valid;
 };
 const showScopeError=group=>{
  group.querySelector('[data-scope-error]').hidden=false;group.classList.add('has-error');
  const first=group.querySelector('input[type=checkbox]');if(first)first.setAttribute('aria-invalid','true');
 };
 groups.forEach(group=>{
  updateScope(group);
  group.addEventListener('change',event=>{
   if(group.hasAttribute('data-scope-single')&&event.target.matches('input[type=checkbox]')&&event.target.checked){
    group.querySelectorAll('input[type=checkbox]').forEach(box=>{if(box!==event.target)box.checked=false;});
   }
   updateScope(group);
  });
  group.addEventListener('invalid',()=>showScopeError(group),true);
  group.querySelectorAll('[data-scope-action]').forEach(button=>button.addEventListener('click',()=>{
   group.querySelectorAll('input[type=checkbox]').forEach(box=>{box.checked=button.dataset.scopeAction==='all';});updateScope(group);
  }));
 });
 [...new Set(groups.map(group=>group.closest('form')))].forEach(form=>form.addEventListener('submit',event=>{
  if(event.submitter?.formNoValidate)return;
  const missing=groups.filter(group=>group.closest('form')===form&&!updateScope(group));
  if(missing.length){event.preventDefault();missing.forEach(showScopeError);missing[0].focus();}
 }));
 const linesContainer=document.querySelector('[data-fee-schedule-lines]');
 const optionalPicker=document.querySelector('[data-optional-head-select]');
 const feeFeedback=document.querySelector('[data-fee-head-feedback]');
 const feedback=(message,isError=false)=>{
  if(!feeFeedback)return;
  feeFeedback.textContent=message;
  feeFeedback.classList.toggle('is-error',isError);
 };
 const wireRow=row=>{
  const amount=row.querySelector('input[name^="amount_"]'),first=row.querySelector('input[name^="first_"]'),override=row.querySelector('input[name^="override_"]'),includeFirst=row.querySelector('input[name^="include_first_"]');
  const update=()=>{
   const output=row.querySelector('[data-yearly-amount]'),mode=row.dataset.timing;
   if(mode==='manual'||mode==='fine'){output.textContent='On request / by policy';return;}
   const n=Number(amount.value);if(!amount.value||!Number.isFinite(n)||n<0||n>999999999){output.textContent='Enter a valid actual amount';return;}
   const count=override.checked?row.querySelectorAll('input[name^="months_"]:checked').length:(mode==='months'?JSON.parse(row.dataset.headMonths).length:12);
   const times=(first.checked||mode==='first')?((count||includeFirst.checked)?1:0):(count||(includeFirst.checked?1:0));
   output.textContent=(Math.round(n*100)*times/100).toLocaleString('en-PK',{minimumFractionDigits:2,maximumFractionDigits:2})+((first.checked||mode==='first')?' · only if the first-challan condition applies':includeFirst.checked?' · plus a conditional first charge outside recurring months':'');
  };
  row.addEventListener('input',update);row.addEventListener('change',update);update();
  const remove=row.querySelector('[data-remove-fee-head]');
  if(remove)remove.addEventListener('click',()=>{
   row.hidden=true;row.querySelector('[data-head-fields]').disabled=true;
   if(optionalPicker){const option=[...optionalPicker.options].find(item=>item.value===row.dataset.headKey);if(option)option.disabled=false;}
   feedback('Optional fee head removed. It will not be included in this schedule.');
  });
 };
 document.querySelectorAll('[data-fee-schedule-line]').forEach(wireRow);
 if(linesContainer&&optionalPicker){
  const existingRows=()=>[...linesContainer.querySelectorAll('[data-fee-schedule-line]')];
  const activate=row=>{
   row.hidden=false;row.querySelector('[data-head-fields]').disabled=false;
   const option=[...optionalPicker.options].find(item=>item.value===row.dataset.headKey);
   if(option)option.disabled=true;
   optionalPicker.value='';
   row.scrollIntoView({behavior:'smooth',block:'center'});
   const amount=row.querySelector('input[name^="amount_"]');if(amount)amount.focus({preventScroll:true});
   feedback('Fee head added. Enter the amount and billing timing as needed.');
  };
  document.querySelector('[data-add-existing-head]')?.addEventListener('click',()=>{
   const key=optionalPicker.value;
   if(!key){feedback('Choose a fee head first.',true);return;}
   const row=existingRows().find(r=>r.dataset.headKey===key);
   if(!row){feedback('Refresh to load this fee head.',true);return;}
   activate(row);
  });
  const addCustom=document.querySelector('[data-add-custom-head]'),customName=document.querySelector('[data-custom-head-name]');
  addCustom?.addEventListener('click',async()=>{
   const label=customName.value.trim();
   if(!label){feedback('Enter the new fee head name.',true);customName.focus();return;}
   const base=existingRows().find(r=>r.querySelector('[data-remove-fee-head]'));
   if(!base){feedback('No fee head template available. Refresh and retry.',true);return;}
   addCustom.disabled=true;feedback('Creating fee head...');
   try{
    const form=addCustom.closest('form');
    const body=new URLSearchParams({_csrf:form.querySelector('input[name="_csrf"]').value,label});
    const response=await fetch('/workspace/core/fees/heads/quick-add',{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/x-www-form-urlencoded','Accept':'application/json'},body});
    if(!response.ok)throw new Error('Could not create fee head. Check the name and retry.');
    const saved=await response.json();
    const found=existingRows().find(r=>r.dataset.headKey===saved.key);
    if(found){activate(found);customName.value='';return;}
    if(saved.existing)throw new Error('This fee head already exists. Refresh the page to load it.');
    const slot=Math.max(0,...existingRows().map(r=>Number(r.dataset.headSlot)))+1;
    const row=base.cloneNode(true);
    row.dataset.headKey=saved.key;row.dataset.headSlot=String(slot);row.dataset.timing='manual';row.dataset.headMonths='[]';
    row.querySelector('h3').textContent=saved.label;
    const oldSlot=base.dataset.headSlot;
    row.querySelectorAll('[name],[id],[for]').forEach(el=>{
     for(const attr of ['name','id','for']){
      const current=el.getAttribute(attr);
      if(current&&current.endsWith('_'+oldSlot))el.setAttribute(attr,current.slice(0,-String(oldSlot).length)+slot);
     }
    });
    row.querySelectorAll('input').forEach(input=>{
     if(input.name==='head_key')input.value=saved.key;
     else if(input.name==='head_index')input.value=String(slot);
     else if(input.name==='head_version_'+slot)input.value='1';
     else if(input.type==='checkbox')input.checked=false;
     else if(input.name==='amount_'+slot)input.value='0.00';
     else if(input.type!=='hidden')input.value='';
    });
    row.querySelector('details')?.removeAttribute('open');
    linesContainer.appendChild(row);wireRow(row);activate(row);
    const option=document.createElement('option');option.value=saved.key;option.textContent=saved.label;option.disabled=true;optionalPicker.appendChild(option);
    customName.value='';
   }catch(error){feedback(error.message||'Could not add the fee head.',true);}
   finally{addCustom.disabled=false;}
  });
 }
});