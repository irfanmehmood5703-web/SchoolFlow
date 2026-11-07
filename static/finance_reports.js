'use strict';
document.querySelector('[data-select-journals]')?.addEventListener('change', event => {
  document.querySelectorAll('[name="journal_ids"]').forEach(input => { input.checked = event.target.checked; });
});
document.querySelectorAll('[data-open-journal]').forEach(button => button.addEventListener('click', () => {
  document.getElementById(button.dataset.openJournal)?.showModal();
}));
document.getElementById('void-journals')?.addEventListener('submit', event => {
  if (!document.querySelector('[name="journal_ids"]:checked')) { event.preventDefault(); window.alert('Select at least one transaction.'); }
});
