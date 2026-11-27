document.addEventListener('DOMContentLoaded',()=>{
 for(const form of document.querySelectorAll('[data-payroll-preview]')){
  const apply=form.querySelector('[name="attendance_based"]');
  if(!apply)return; // A saved school-wide policy applies automatically.
  const format=new Intl.NumberFormat('en-PK',{minimumFractionDigits:2,maximumFractionDigits:2});
  const update=()=>{
   for(const el of form.querySelectorAll('[data-base-paisa]')){
    const amount=Number(apply.checked?el.dataset.basePaisa:el.dataset.noAttendancePaisa);
    el.textContent='Rs '+format.format(amount/100);
   }
  };
  apply.addEventListener('change',update);
 }
});
