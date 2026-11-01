document.addEventListener('DOMContentLoaded',()=>{
 const modes=JSON.parse(document.getElementById('subject-grading').textContent),table=document.querySelector('.repeat-table');
 const update=row=>{const subject=row.querySelector('[name=subject]'),total=row.querySelector('[name=total]');if(!subject||!total)return;const numeric=(modes[subject.value]||'Marks')==='Marks';if(!numeric&&!total.readOnly){total.dataset.previous=total.value;total.value='0'}else if(numeric&&total.readOnly){total.value=total.dataset.previous||''}total.required=numeric;total.readOnly=!numeric;total.min=numeric?'0.01':'0';total.setAttribute('aria-label',numeric?'Total marks':'Qualitative subject: no numeric total');};
 table.addEventListener('input',e=>{if(e.target.name==='subject')update(e.target.closest('tr'))});
 new MutationObserver(()=>table.querySelectorAll('tbody tr').forEach(update)).observe(table.querySelector('tbody'),{childList:true});
 table.querySelectorAll('tbody tr').forEach(update);
});
