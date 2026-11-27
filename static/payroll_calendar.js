document.addEventListener('DOMContentLoaded',()=>{
 const dates=Array.from(document.querySelectorAll('input[name="working_dates"]'));
 const update=()=>{
  const working=dates.filter(el=>el.checked).length;
  const paid=document.querySelector('input[name="pay_basis"]:checked')?.value==='calendar_days'?dates.length:working;
  document.getElementById('attendance-working-count').textContent=working;
  document.getElementById('salary-paid-count').textContent=paid;
 };
 document.getElementById('apply-working-weekdays')?.addEventListener('click',()=>{
  const selected=new Set(Array.from(document.querySelectorAll('[data-working-weekday]:checked'),el=>el.value));
  dates.forEach(el=>{el.checked=selected.has(el.dataset.weekday)});
  update();
 });
 document.querySelectorAll('input[name="working_dates"],input[name="pay_basis"]').forEach(el=>el.addEventListener('change',update));
 update();
});
