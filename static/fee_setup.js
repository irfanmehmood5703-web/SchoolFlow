'use strict';
document.addEventListener('DOMContentLoaded',()=>{
 document.querySelectorAll('[data-fee-schedule-line]').forEach(row=>{
  const amount=row.querySelector('input[name^="amount_"]'),first=row.querySelector('input[name^="first_"]'),override=row.querySelector('input[name^="override_"]');
  const update=()=>{
   const output=row.querySelector('[data-yearly-amount]'),mode=row.dataset.timing;
   if(mode==='manual'||mode==='fine'){output.textContent='On request / by policy';return;}
   const n=Number(amount.value);if(!amount.value||!Number.isFinite(n)||n<0||n>999999999){output.textContent='Enter a valid actual amount';return;}
   const count=override.checked?row.querySelectorAll('input[name^="months_"]:checked').length:(mode==='months'?JSON.parse(row.dataset.headMonths).length:12);
   const times=first.checked||mode==='first'?(count?1:0):count;
   output.textContent=(Math.round(n*100)*times/100).toLocaleString('en-PK',{minimumFractionDigits:2,maximumFractionDigits:2})+((first.checked||mode==='first')?' · only if the first-challan condition applies':'');
  };
  row.addEventListener('input',update);row.addEventListener('change',update);update();
 });
});
