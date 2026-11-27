(() => {
  const form = document.querySelector('[data-monthly-roster]');
  if (!form) return;
  const picks = [...form.querySelectorAll('[data-monthly-pick]:not(:disabled)')];
  const all = form.querySelector('[data-monthly-all]');
  const count = form.querySelector('[data-monthly-count]');
  const buttons = [...form.querySelectorAll('[data-monthly-save]')];
  const sync = () => {
    const selected = picks.filter(p => p.checked).length;
    count.textContent = selected + ' selected';
    all.checked = selected > 0 && selected === picks.length;
    all.indeterminate = selected > 0 && selected < picks.length;
    all.disabled = !picks.length;
    buttons.forEach(b => b.disabled = !selected);
  };
  all.addEventListener('change', () => { picks.forEach(p => p.checked = all.checked); sync(); });
  form.addEventListener('change', e => {
    if (e.target.matches('[data-monthly-pick]')) sync();
  });
  form.addEventListener('input', e => {
    if (e.target.matches('[data-monthly-number], input[name^="notes_"]')) {
      const pick = e.target.closest('[data-monthly-row]').querySelector('[data-monthly-pick]');
      if (!pick.disabled) pick.checked = true;
      const print = e.target.parentElement.querySelector('.monthly-print-value');
      if (print) print.textContent = e.target.value;
      sync();
    }
  });
  // Only selected rows should participate in native validation or submission.
  form.addEventListener('submit', e => {
    if (!picks.some(p => p.checked)) { e.preventDefault(); return; }
    for (const p of picks.filter(p => p.checked)) {
      for (const input of p.closest('[data-monthly-row]').querySelectorAll('input:not(:disabled)')) {
        if (!input.reportValidity()) { e.preventDefault(); return; }
      }
    }
    picks.filter(p => !p.checked).forEach(p => p.closest('[data-monthly-row]').querySelectorAll('input').forEach(i => i.disabled = true));
  });
  sync();
})();
