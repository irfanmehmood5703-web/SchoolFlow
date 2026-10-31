document.addEventListener('DOMContentLoaded',()=>{
 document.querySelectorAll('[data-fields]').forEach(b=>b.addEventListener('click',()=>b.closest('section').querySelectorAll('input[name^="visible_"]:not(:disabled)').forEach(c=>{c.checked=b.dataset.fields==='show';if(!c.checked)c.closest('tr').querySelector('input[name^="required_"]').checked=false})));
 document.querySelectorAll('input[name^="required_"]').forEach(c=>c.addEventListener('change',()=>{if(c.checked)c.closest('tr').querySelector('input[name^="visible_"]').checked=true}));
 const weights=()=>{const node=document.querySelector('[data-weight-total]');if(node)node.textContent=Array.from(document.querySelectorAll('[data-weight]')).reduce((s,i)=>s+(Number(i.value)||0),0).toFixed(2)+'%'};document.addEventListener('input',weights);weights();
 document.getElementById('sms-template')?.addEventListener('change',e=>{if(e.target.value)document.getElementById('message').value=e.target.value});
 let activeEditor=null,activeSource=null,savedRange=null;
 const remember=ed=>{activeEditor=ed;activeSource=null;const s=getSelection();if(s.rangeCount&&ed.contains(s.anchorNode))savedRange=s.getRangeAt(0).cloneRange()};
 const insert=(ed,html,command)=>{
  ed.focus();const s=getSelection();if(savedRange&&ed.contains(savedRange.commonAncestorContainer)){s.removeAllRanges();s.addRange(savedRange)}
  document.execCommand('styleWithCSS',false,true);document.execCommand(command||'insertHTML',false,html);ed.dispatchEvent(new Event('input'));remember(ed);
 };
 document.querySelectorAll('.settings-rich-editor').forEach(ed=>{
  const text=ed.closest('.editor-panel').querySelector('textarea');
  ed.addEventListener('input',()=>text.value=ed.innerHTML);
  // Source HTML is rendered only by the server's sanitized preview. Pasted and
  // dropped rich content is inserted as plain text, never as executable HTML.
  text.addEventListener('focus',()=>{activeSource=text;activeEditor=null;savedRange=null});
  ed.addEventListener('paste',e=>{e.preventDefault();insert(ed,e.clipboardData.getData('text/plain'),'insertText')});
  ed.addEventListener('drop',e=>{e.preventDefault();insert(ed,e.dataTransfer.getData('text/plain'),'insertText')});
  for(const event of ['keyup','mouseup','focus'])ed.addEventListener(event,()=>remember(ed));
 });
 document.querySelectorAll('[data-edit-command]').forEach(b=>{b.addEventListener('mousedown',e=>e.preventDefault());b.addEventListener('click',()=>{const ed=b.closest('.editor-panel').querySelector('.settings-rich-editor');if(b.dataset.editCommand==='table')insert(ed,'<table><tbody><tr><td>Label</td><td>Value</td></tr></tbody></table>');else insert(ed,null,b.dataset.editCommand)})});
 document.querySelectorAll('[data-edit-format]').forEach(control=>control.addEventListener('change',()=>insert(control.closest('.editor-panel').querySelector('.settings-rich-editor'),control.value,control.dataset.editFormat)));
 document.querySelectorAll('[data-insert-tag]').forEach(b=>b.addEventListener('click',()=>{
  if(activeSource){activeSource.setRangeText(b.dataset.insertTag,activeSource.selectionStart,activeSource.selectionEnd,'end');return;}
  const ed=activeEditor||document.querySelector('.settings-rich-editor');if(ed)insert(ed,b.dataset.insertTag);
 }));
 document.querySelectorAll('[data-copy-tag]').forEach(b=>b.addEventListener('click',async()=>{try{await navigator.clipboard.writeText(b.dataset.copyTag);b.textContent='Copied '+b.dataset.copyTag}catch{b.textContent='Copy: '+b.dataset.copyTag}}));
 document.querySelectorAll('[data-day-off]').forEach(c=>{const update=()=>c.closest('tr').querySelectorAll('input[type=time]').forEach(i=>{const ownOff=c.closest('tr').querySelector('[name="'+i.name.replace('_','_off_')+'"]');i.disabled=c.checked||!!ownOff?.checked;i.required=!i.disabled});c.closest('tr').querySelectorAll('input[type=checkbox]').forEach(x=>x.addEventListener('change',update));c.addEventListener('change',update);update()});
 document.querySelectorAll('[data-settings-order]').forEach(body=>{
  let dragging=null;
  body.addEventListener('dragstart',e=>{dragging=e.target.closest('[data-order-row]');if(dragging)e.dataTransfer.setData('text/plain',dragging.dataset.orderRow)});
  body.addEventListener('dragover',e=>{if(dragging)e.preventDefault()});
  body.addEventListener('drop',e=>{if(!dragging)return;e.preventDefault();const row=e.target.closest('[data-order-row]');if(row&&row!==dragging){const rect=row.getBoundingClientRect();body.insertBefore(dragging,e.clientY<rect.top+rect.height/2?row:row.nextElementSibling)}dragging=null});
  body.addEventListener('dragend',()=>dragging=null);
  body.querySelectorAll('[data-order-move]').forEach(b=>b.addEventListener('click',()=>{const row=b.closest('[data-order-row]');if(b.dataset.orderMove==='up'&&row.previousElementSibling)body.insertBefore(row,row.previousElementSibling);if(b.dataset.orderMove==='down'&&row.nextElementSibling)body.insertBefore(row.nextElementSibling,row)}));
 });
});
