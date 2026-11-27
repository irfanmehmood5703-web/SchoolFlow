const primaryFilters = new Set([
  'q', 'student_name', 'name', 'campus', 'class_name', 'bill_month', 'status', 'bill_status', 'month'
]);

for (const form of document.querySelectorAll('.admission-filter-bar')) {
  const fields = [...form.querySelectorAll(':scope > .admission-filter-field')];
  const optional = fields.filter(label => !primaryFilters.has(label.firstElementChild.nextElementSibling.name));
  const actions = form.querySelector('.admission-filter-actions');
  if (!actions || !fields.length) continue;

  const heading = document.createElement('h2');
  heading.className = 'schoolflow-filter-title';
  heading.textContent = form.getAttribute('aria-label') || 'Find records';
  form.prepend(heading);

  const applied = new URL(location.href);
  const chips = document.createElement('ul');
  chips.className = 'schoolflow-filter-chips';
  chips.setAttribute('aria-label', 'Applied filters');
  for (const label of fields) {
    const input = label.querySelector('input[name], select[name]');
    const value = applied.searchParams.get(input.name);
    if (!value || ['size', 'sort'].includes(input.name)) continue;

    const url = new URL(applied);
    for (const key of [input.name, 'page', 'export']) url.searchParams.delete(key);
    // The student roster defaults to Enrolled when there is no explicit status.
    if (input.name === 'status' && form.getAttribute('aria-label') === 'Filter students') {
      url.searchParams.set('status', '');
    }
    const name = label.firstElementChild.textContent.trim();
    const caption = input.selectedOptions?.[0]?.textContent.trim() || value;
    const link = document.createElement('a');
    link.href = url.pathname + url.search;
    link.textContent = name + ': ' + caption + ' ×';
    link.setAttribute('aria-label', 'Remove ' + name + ' filter: ' + caption);
    const item = document.createElement('li');
    item.append(link);
    chips.append(item);
  }
  if (chips.childElementCount) heading.after(chips);

  if (optional.length) {
    const groups = document.createElement('details');
    groups.className = 'schoolflow-more-filters';
    const toggle = document.createElement('summary');
    toggle.textContent = 'More filters';
    const contents = document.createElement('div');
    contents.className = 'schoolflow-filter-fields';
    contents.append(...optional);
    groups.append(toggle, contents);
    actions.before(groups);
  }
}

const feeForm = document.querySelector('[data-challan-workspace]');
if (feeForm) {
  const checks = [...feeForm.querySelectorAll('[data-challan-balance]')];
  const review = feeForm.querySelector('[data-selected-review]');
  const count = feeForm.querySelector('[data-selected-count]');
  const balance = feeForm.querySelector('[data-selected-balance]');
  const currency = new Intl.NumberFormat('en-PK', {maximumFractionDigits: 2});
  const update = () => {
    const selected = checks.filter(input => input.checked && !input.disabled);
    const remaining = selected.reduce((sum, input) => sum + Number(input.dataset.challanBalance), 0);
    count.textContent = selected.length + (selected.length === 1 ? ' challan selected' : ' challans selected');
    balance.textContent = currency.format(remaining / 100);
    review.classList.toggle('has-selection', selected.length > 0);
  };
  feeForm.addEventListener('change', () => queueMicrotask(update));
  window.addEventListener('pageshow', update);
  update();
}
