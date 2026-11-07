'use strict';
const groupSelect = document.querySelector('[data-account-group]');
if (groupSelect) {
  const preview = () => {
    if (!groupSelect.hasAttribute('data-existing-code')) {
      document.getElementById('account-code').value = groupSelect.selectedOptions[0]?.dataset.code || '';
    }
  };
  groupSelect.addEventListener('change', preview);
  preview();
  document.querySelector('[data-group-search]').addEventListener('input', event => {
    const query = event.target.value.trim().toLocaleLowerCase();
    for (const option of groupSelect.options) {
      option.hidden = !!option.value && !option.text.toLocaleLowerCase().includes(query) && !option.selected;
    }
    for (const group of groupSelect.querySelectorAll('optgroup')) {
      group.hidden = Array.from(group.children).every(option => option.hidden);
    }
  });
}
if (document.querySelector('[data-finance-print]')) window.addEventListener('load', () => window.print());
