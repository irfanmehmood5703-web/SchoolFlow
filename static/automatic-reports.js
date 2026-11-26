/* Repeat timed lecture rows without duplicating assignments or altering shared weekdays. */
(() => {
  const form = document.querySelector('[data-lecture-form]');
  if (!form) return;
  const rows = form.querySelector('[data-lecture-rows]');
  const add = form.querySelector('[data-add-lecture]');
  const limit = 12;
  const refresh = () => {
    const list = [...rows.querySelectorAll('[data-lecture-row]')];
    list.forEach((row, index) => {
      row.querySelector('[data-lecture-label]').textContent = 'Lecture ' + (index + 1);
      row.querySelector('[data-remove-lecture]').hidden = list.length === 1;
    });
    add.disabled = list.length >= limit;
  };
  add.hidden = false;
  add.addEventListener('click', () => {
    if (rows.children.length >= limit) return;
    const row = rows.firstElementChild.cloneNode(true);
    row.querySelector('select').selectedIndex = 0;
    row.querySelector('input[type="time"]').value = '';
    rows.append(row);
    refresh();
    row.querySelector('select').focus();
  });
  rows.addEventListener('click', (event) => {
    const button = event.target.closest('[data-remove-lecture]');
    if (!button || rows.children.length < 2) return;
    button.closest('[data-lecture-row]').remove();
    refresh();
    add.focus();
  });
  refresh();
})();
