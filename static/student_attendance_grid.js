document.addEventListener('DOMContentLoaded',()=>{
 const form=document.querySelector('[data-attendance-grid]');if(!form)return;
 const rows=[...form.querySelectorAll('[data-att-row]')],all=form.querySelector('[data-att-select-all]'),label=form.querySelector('[data-att-selected]');
 const selected=r=>r.querySelector('input[name=attendance_keys]');
 const filters=document.getElementById('attendance-filters');
 const dirty=()=>rows.some(r=>{const checked=r.querySelector('input[type=radio]:checked'),original=r.querySelector('input[name^=original_]');return checked&&original&&checked.value!==original.value;});
 const warn=()=>!dirty()||window.confirm('Unsaved attendance changes will be lost. Continue without saving?');
 if(filters){
   const dropdowns=[...document.querySelectorAll('[data-att-filter]')];
   dropdowns.forEach(el=>{el.dataset.previous=el.value;el.addEventListener('change',()=>{if(!warn()){el.value=el.dataset.previous;return;}if(filters.reportValidity())filters.submit();else el.value=el.dataset.previous;});});
   filters.addEventListener('submit',e=>{if(e.submitter&&e.submitter.name==='export')return;if(!warn())e.preventDefault();});
   filters.querySelector('[data-filter-clear]')?.addEventListener('click',e=>{if(!warn())e.preventDefault();});
 }
 const sync=()=>{const n=rows.filter(r=>selected(r).checked).length;all.checked=rows.length>0&&n===rows.length;all.indeterminate=n>0&&n<rows.length;label.textContent=n+' selected';form.querySelectorAll('button[name=action]').forEach(b=>b.disabled=n===0);};
 all.addEventListener('change',()=>{rows.forEach(r=>selected(r).checked=all.checked);sync();});
 form.addEventListener('change',e=>{if(e.target.matches('input[name=attendance_keys]'))sync();if(e.target.type==='radio'){const r=e.target.closest('[data-att-row]');if(r){selected(r).checked=true;sync();}}});
 form.querySelectorAll('[data-bulk-status]').forEach(b=>b.addEventListener('click',()=>{for(const r of rows){if(!selected(r).checked)continue;const radio=[...r.querySelectorAll('input[type=radio]')].find(x=>x.value===b.dataset.bulkStatus);if(radio)radio.checked=true;}}));sync();
});