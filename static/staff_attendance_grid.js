document.addEventListener('DOMContentLoaded',()=>{
  document.querySelectorAll('[data-staff-attendance-grid]').forEach(form=>{
    const rows=[...form.querySelectorAll('[data-staff-row]')],all=form.querySelector('[data-staff-all]'),label=form.querySelector('[data-staff-selected]');
    const check=row=>row.querySelector('input[type=checkbox]'), enabled=rows.filter(row=>!check(row).disabled);
    const save=[...form.querySelectorAll('[data-staff-save]')].filter(button=>!button.disabled);
    const bulk=[...form.querySelectorAll('[data-staff-mark]')].filter(button=>!button.disabled);
    const sync=()=>{const n=enabled.filter(row=>check(row).checked).length;if(label)label.textContent=n+' selected';if(all){all.checked=enabled.length>0&&n===enabled.length;all.indeterminate=n>0&&n<enabled.length;}save.concat(bulk).forEach(button=>button.disabled=n===0);};
    all?.addEventListener('change',()=>{enabled.forEach(row=>check(row).checked=all.checked);sync();});
    enabled.forEach(row=>check(row).addEventListener('change',sync));
    bulk.forEach(button=>button.addEventListener('click',()=>{for(const row of enabled){if(!check(row).checked)continue;const select=row.querySelector('[data-staff-status]');if([...select.options].some(option=>option.value===button.dataset.staffMark))select.value=button.dataset.staffMark;}}));
    sync();
  });
});
