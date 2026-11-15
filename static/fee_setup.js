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
 document.querySelectorAll('[data-fee-schedule-line]').forEach(row=>{
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
 });
});
