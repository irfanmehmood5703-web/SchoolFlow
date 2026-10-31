document.addEventListener('DOMContentLoaded',()=>{
 document.getElementById('apply-working-weekdays')?.addEventListener('click',()=>{
  const selected=new Set(Array.from(document.querySelectorAll('[data-working-weekday]:checked'),el=>el.value));
  document.querySelectorAll('input[name="working_dates"]').forEach(el=>{el.checked=selected.has(el.dataset.weekday)});
 });
});
