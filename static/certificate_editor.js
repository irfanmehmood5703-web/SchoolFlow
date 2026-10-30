document.addEventListener('DOMContentLoaded',()=>{
 document.querySelectorAll('.rich-editor').forEach(editor=>{
  const surface=editor.querySelector('[data-editor-surface]'),source=editor.querySelector('[data-editor-source-text]');source.hidden=true;
  const sync=()=>{if(!surface.hidden)source.value=surface.innerHTML;};
  surface.addEventListener('input',sync);
  editor.querySelectorAll('[data-editor-command]').forEach(button=>{
   button.addEventListener('mousedown',event=>event.preventDefault());
   button.addEventListener('click',()=>{if(surface.hidden)return;surface.focus();document.execCommand('styleWithCSS',false,true);document.execCommand(button.dataset.editorCommand,false);sync();});
  });
  editor.querySelector('[data-editor-source]').addEventListener('click',()=>{
   if(!surface.hidden){sync();surface.hidden=true;source.hidden=false;source.focus();}
   else {source.focus();alert('Use Preview changes below to apply HTML source safely.');}
  });
  editor.querySelector('[data-editor-size]').addEventListener('change',event=>{if(surface.hidden)return;surface.focus();document.execCommand('styleWithCSS',false,true);document.execCommand('fontSize',false,event.target.value);sync();});
  editor.querySelector('[data-editor-colour]').addEventListener('change',event=>{if(surface.hidden)return;surface.focus();document.execCommand('styleWithCSS',false,true);document.execCommand('foreColor',false,event.target.value);sync();});
  editor.querySelector('[data-editor-table]').addEventListener('click',()=>{if(surface.hidden)return;surface.focus();document.execCommand('styleWithCSS',false,true);document.execCommand('insertHTML',false,'<table style="width:100%"><tr><td>Heading</td><td>Value</td></tr><tr><td>Label</td><td>Value</td></tr></table>');sync();});
  editor.querySelector('[data-editor-tag]').addEventListener('click',()=>{if(surface.hidden)return;const tag=prompt('Tag name, for example studentName or tuitionFee');if(tag&&/^[A-Za-z_][A-Za-z0-9_]*$/.test(tag)){surface.focus();document.execCommand('styleWithCSS',false,true);document.execCommand('insertText',false,'['+tag+']');sync();}});
  editor.closest('form').addEventListener('submit',sync);
 });
});
