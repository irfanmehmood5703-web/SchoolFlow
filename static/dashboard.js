document.addEventListener('DOMContentLoaded',()=>{
 const panel=document.getElementById('dashboard-customise');
 document.querySelectorAll('[data-open-dashboard]').forEach(link=>link.addEventListener('click',()=>{panel.open=true}));
 panel?.addEventListener('click',event=>{
  const button=event.target.closest('[data-move-widget]');if(!button)return;
  const row=button.closest('[data-dashboard-item]');
  const sibling=button.dataset.moveWidget==='up'?row.previousElementSibling:row.nextElementSibling;
  if(sibling){if(button.dataset.moveWidget==='up')row.parentNode.insertBefore(row,sibling);else row.parentNode.insertBefore(sibling,row);button.focus()}
 });
 document.querySelectorAll('[data-dashboard-widget]').forEach(widget=>{
  const button=widget.querySelector('[data-expand-widget]');
  const scope=widget.closest('[data-dashboard-scope]').dataset.dashboardScope;
  const key='sf:dashboard:'+scope+':'+widget.dataset.dashboardWidget;
  const set=expanded=>{widget.classList.toggle('is-expanded',expanded);button.setAttribute('aria-pressed',String(expanded));button.textContent=expanded?'Collapse':'Expand'};
  try{set(localStorage.getItem(key)==='expanded')}catch{set(false)}
  button.addEventListener('click',()=>{const expanded=!widget.classList.contains('is-expanded');set(expanded);try{localStorage.setItem(key,expanded?'expanded':'closed')}catch{}});
 });
});
