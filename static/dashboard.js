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

 const grid = document.querySelector('.personal-dashboard:is(.columns-2, .columns-3)');
 if (!grid || !('ResizeObserver' in window)) return;
 const widgets = [...grid.querySelectorAll(':scope > [data-dashboard-widget]')];
 if (!widgets.length) return;

 const style = getComputedStyle(grid);
 const rowUnit = parseFloat(style.getPropertyValue('--widget-row-unit'));
 const gap = parseFloat(style.getPropertyValue('--widget-gap'));
 if (!(rowUnit > 0) || !Number.isFinite(gap)) return;

 // Fine rows let the next widget start just below the shortest available
 // column while preserving the saved order and full-width expanded widgets.
 const spanFor = height => String(Math.max(1, Math.ceil((height + gap) / rowUnit)));
 const heights = widgets.map(widget => widget.getBoundingClientRect().height);
 widgets.forEach((widget, index) => widget.style.setProperty('--widget-rows', spanFor(heights[index])));
 grid.classList.add('is-packed');

 const observer = new ResizeObserver(entries => {
  for (const {target, borderBoxSize} of entries) {
   const span = spanFor(borderBoxSize?.[0]?.blockSize ?? target.getBoundingClientRect().height);
   if (span !== target.style.getPropertyValue('--widget-rows')) target.style.setProperty('--widget-rows', span);
  }
 });
 widgets.forEach(widget => observer.observe(widget, {box: 'border-box'}));
});
