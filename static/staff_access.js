(() => {
  const modules = [...document.querySelectorAll('[data-permission-module]')];
  document.querySelector('[data-permission-expand]')?.addEventListener('click', () => modules.forEach(m => m.open = true));
  document.querySelector('[data-permission-collapse]')?.addEventListener('click', () => modules.forEach(m => m.open = false));
  document.querySelector('[data-permission-search]')?.addEventListener('input', event => {
    const value = event.target.value.trim().toLowerCase();
    modules.forEach(m => { m.hidden = !m.textContent.toLowerCase().includes(value); if (value && !m.hidden) m.open = true; });
  });
  document.querySelectorAll('[data-permission-campus]').forEach(button => button.addEventListener('click', () => {
    const boxes = [...button.closest('details').querySelectorAll('input[type=checkbox]')].filter(box => box.value === button.dataset.permissionCampus);
    const checked = boxes.some(box => !box.checked);
    boxes.forEach(box => box.checked = checked);
  }));
})();
