document.addEventListener('DOMContentLoaded',()=>{
 document.querySelectorAll('[data-fields]').forEach(b=>b.addEventListener('click',()=>b.closest('section').querySelectorAll('input[name^="visible_"]:not(:disabled)').forEach(c=>{c.checked=b.dataset.fields==='show';if(!c.checked)c.closest('tr').querySelector('input[name^="required_"]').checked=false})));
 document.querySelectorAll('input[name^="required_"]').forEach(c=>c.addEventListener('change',()=>{if(c.checked)c.closest('tr').querySelector('input[name^="visible_"]').checked=true}));
 const weights=()=>{const node=document.querySelector('[data-weight-total]');if(node)node.textContent=Array.from(document.querySelectorAll('[data-weight]')).reduce((s,i)=>s+(Number(i.value)||0),0).toFixed(2)+'%'};document.addEventListener('input',weights);weights();
 document.getElementById('sms-template')?.addEventListener('change',e=>{if(e.target.value)document.getElementById('message').value=e.target.value});
 let activeEditor=null,savedRange=null;
 document.querySelectorAll('.settings-rich-editor').forEach(ed=>{
  const text=ed.closest('.editor-panel').querySelector('textarea');
  ed.addEventListener('input',()=>text.value=ed.innerHTML);
  text.addEventListener('input',()=>ed.innerHTML=text.value);
  for(const event of ['keyup','mouseup','focus'])ed.addEventListener(event,()=>{activeEditor=ed;const s=getSelection();if(s.rangeCount&&ed.contains(s.anchorNode))savedRange=s.getRangeAt(0).cloneRange()});
 });
 const insert=(ed,html,command)=>{ed.focus();const s=getSelection();if(savedRange&&ed.contains(savedRange.commonAncestorContainer)){s.removeAllRanges();s.addRange(savedRange)}document.execCommand(command||'insertHTML',false,html);ed.dispatchEvent(new Event('input'))};
 document.querySelectorAll('[data-edit-command]').forEach(b=>{b.addEventListener('mousedown',e=>e.preventDefault());b.addEventListener('click',()=>{const ed=b.closest('.editor-panel').querySelector('.settings-rich-editor');if(b.dataset.editCommand==='table')insert(ed,'<table><tbody><tr><td>Label</td><td>Value</td></tr></tbody></table>');else insert(ed,null,b.dataset.editCommand)})});
 document.querySelectorAll('[data-insert-tag]').forEach(b=>b.addEventListener('click',()=>{const ed=activeEditor||document.querySelector('.settings-rich-editor');if(ed)insert(ed,b.dataset.insertTag)}));
 document.querySelectorAll('[data-copy-tag]').forEach(b=>b.addEventListener('click',async()=>{try{await navigator.clipboard.writeText(b.dataset.copyTag);b.textContent='Copied '+b.dataset.copyTag}catch{b.textContent='Copy: '+b.dataset.copyTag}}));
 document.querySelectorAll('[data-day-off]').forEach(c=>{const update=()=>c.closest('tr').querySelectorAll('input[type=time]').forEach(i=>{const ownOff=c.closest('tr').querySelector('[name="'+i.name.replace('_','_off_')+'"]');i.disabled=c.checked||!!ownOff?.checked;i.required=!i.disabled});c.closest('tr').querySelectorAll('input[type=checkbox]').forEach(x=>x.addEventListener('change',update));c.addEventListener('change',update);update()});
});
