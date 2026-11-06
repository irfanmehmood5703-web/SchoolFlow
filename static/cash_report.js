'use strict';
const picker = document.querySelector('.cash-account-picker');
if (picker) {
  const accounts = () => [...picker.querySelectorAll('[name="account_id"]')];
  const sync = () => picker.querySelectorAll('[data-cash-toggle]').forEach(toggle => {
    const rows = [...toggle.closest('[data-cash-group],[data-cash-class]').querySelectorAll('[name="account_id"]')];
    toggle.checked = rows.length > 0 && rows.every(row => row.checked);
    toggle.indeterminate = rows.some(row => row.checked) && !toggle.checked;
  });
  picker.addEventListener('change', event => {
    if (event.target.matches('[data-cash-toggle]')) event.target.closest('[data-cash-group],[data-cash-class]').querySelectorAll('[name="account_id"]').forEach(row => { row.checked = event.target.checked; });
    sync();
  });
  picker.querySelector('[data-cash-all]').addEventListener('click', () => { accounts().forEach(row => { row.checked = true; }); sync(); });
  picker.querySelector('[data-cash-clear]').addEventListener('click', () => { accounts().forEach(row => { row.checked = false; }); sync(); });
  picker.querySelector('[data-cash-search]').addEventListener('input', event => {
    const query = event.target.value.trim().toLocaleLowerCase();
    picker.querySelectorAll('[data-cash-option]').forEach(row => { row.hidden = !row.textContent.toLocaleLowerCase().includes(query); });
    picker.querySelectorAll('[data-cash-group],[data-cash-class]').forEach(group => { group.hidden = [...group.querySelectorAll('[data-cash-option]')].every(row => row.hidden); });
  });
  sync();
}
