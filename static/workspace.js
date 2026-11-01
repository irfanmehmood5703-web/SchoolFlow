document.addEventListener('DOMContentLoaded',()=>{
 document.querySelectorAll('.nav-menu').forEach(d=>d.addEventListener('toggle',()=>{if(d.open)document.querySelectorAll('.nav-menu').forEach(o=>{if(o!==d)o.open=false})}));
 document.addEventListener('click',e=>{if(!e.target.closest('.nav-menu'))document.querySelectorAll('.nav-menu').forEach(d=>d.open=false)});
 document.querySelectorAll('form').forEach(f=>{const update=()=>{const n=f.querySelectorAll('input[type=checkbox][name]:checked:not([name=_csrf])').length;f.querySelectorAll('[data-needs-selection]').forEach(b=>{b.disabled=!f.querySelector('input[name=ids]:checked,input[name=student_ids]:checked,input[name=employee_ids]:checked')||(b.hasAttribute('data-needs-template')&&!f.querySelector('input[name=template_id]:checked'))})};f.querySelectorAll('[data-select-all]').forEach(a=>a.addEventListener('change',()=>{f.querySelectorAll('tbody input[type=checkbox]:not(:disabled)').forEach(c=>c.checked=a.checked);update()}));f.addEventListener('change',update);update();});
 document.querySelectorAll('.table-search').forEach(input=>input.addEventListener('input',()=>{input.closest('.form-card').querySelectorAll('tbody tr').forEach(r=>r.hidden=!r.textContent.toLowerCase().includes(input.value.toLowerCase()))}));
 document.querySelectorAll('[data-add-row]').forEach(b=>b.addEventListener('click',()=>{const body=b.closest('form').querySelector('.repeat-table tbody');const row=body.firstElementChild.cloneNode(true);row.querySelectorAll('input,textarea').forEach(i=>{if(i.type==='checkbox')i.checked=false;if(i.name==='total'||!['date','number'].includes(i.type))i.value=''});body.append(row)}));
 document.addEventListener('click',e=>{const b=e.target.closest('[data-remove-row]');if(b&&b.closest('tbody').children.length>1)b.closest('tr').remove()});
 document.querySelectorAll('[data-expand]').forEach(b=>b.addEventListener('click',()=>document.querySelectorAll('.family-row').forEach(d=>d.open=b.dataset.expand==='true')));
 const totals=()=>document.querySelectorAll('[data-marks-row]').forEach(r=>{let sum=0;r.querySelectorAll('.mark-input').forEach(i=>{const s=i.closest('td').querySelector('.paper-state');i.disabled=!!s.value;if(!s.value)sum+=Number(i.value)||0});r.querySelectorAll('[data-retained-mark]').forEach(i=>sum+=Number(i.dataset.retainedMark)||0);r.querySelector('.marks-total').textContent=sum.toFixed(2)});document.addEventListener('input',totals);document.addEventListener('change',totals);totals();
 document.querySelectorAll('[data-widget-key]').forEach(c=>{const k='sf:widget:'+c.dataset.widgetKey;c.open=localStorage.getItem(k)==='open';c.addEventListener('toggle',()=>localStorage.setItem(k,c.open?'open':'closed'))});
});
document.addEventListener('DOMContentLoaded',()=>{
 document.querySelectorAll('[data-fee-plan]').forEach(form=>{
  const fmt=value=>(value/100).toLocaleString('en',{minimumFractionDigits:2,maximumFractionDigits:2});
  const update=()=>{let arrears=0,discount=0,net=0,actualTotal=0;
   const samePeriod=form.dataset.effective===form.querySelector('[name=effective]').value,pct=Number(form.querySelector('[name=percentage]').value)||0;
   form.querySelectorAll('[data-fee-line]').forEach(row=>{
    const base=Number(samePeriod?row.dataset.baseActual:row.dataset.actual),input=row.querySelector('[data-discount]'),d=Math.round((Number(input.value)||0)*100),a=Math.round((Number(row.querySelector('[data-arrears]').value)||0)*100);
    const baseNet=base-d,increment=Math.round(baseNet*pct/100),actual=base+increment;
    input.max=String(base/100);arrears+=a;discount+=d;net+=baseNet+increment;actualTotal+=actual;
    row.querySelector('[data-net]').textContent=fmt(baseNet+increment);row.querySelector('[data-adjusted-actual]').textContent=fmt(actual);
    row.querySelector('[data-increment-note]').textContent=increment?' Includes increment '+fmt(increment)+' on net '+fmt(baseNet):'';
   });
   for(const [key,value] of Object.entries({arrears,discount,net,actual:actualTotal}))form.querySelector('[data-total-'+key+']').textContent=fmt(value);
  };
  form.addEventListener('input',update);form.addEventListener('change',update);update();
 });
});

document.addEventListener('DOMContentLoaded',()=>{
 const panels=[...document.querySelectorAll('details[data-advanced]')],button=document.querySelector('[data-advanced-toggle]');
 if(!panels.length||!button)return;
 const key='sf:advanced:'+document.body.dataset.advancedScope+':'+location.pathname;
 let preference=null;try{preference=localStorage.getItem(key)}catch(e){}
 let full=preference===null?document.body.dataset.advancedDefault==='full':preference==='full';
 panels.forEach(p=>p.open=full);button.hidden=false;
 const update=()=>{button.textContent=panels.some(p=>p.open)?'Hide advanced settings':'Show advanced settings';button.setAttribute('aria-expanded',String(panels.some(p=>p.open)))};
 panels.forEach(p=>p.addEventListener('toggle',update));update();
 button.addEventListener('click',()=>{full=!panels.some(p=>p.open);panels.forEach(p=>p.open=full);try{localStorage.setItem(key,full?'full':'light')}catch(e){}update()});
});
