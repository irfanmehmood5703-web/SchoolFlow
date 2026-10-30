'use strict';
document.addEventListener('DOMContentLoaded', () => {
  const add = document.getElementById('add-document');
  const rows = document.getElementById('document-rows');
  add?.addEventListener('click', () => {
    if (rows.children.length >= 20) return;
    const row = rows.firstElementChild.cloneNode(true);
    row.querySelectorAll('input').forEach(input => { input.value = ''; });
    rows.appendChild(row);
  });
  rows?.addEventListener('click', event => {
    const button = event.target.closest('.remove-document');
    if (!button) return;
    if (rows.children.length === 1) {
      rows.querySelectorAll('input').forEach(input => { input.value = ''; });
    } else button.closest('tr').remove();
  });
  const familySelect = document.getElementById('family_id');
  const familyMode = document.getElementById('family_mode');
  const feedback = document.getElementById('family-feedback');
  let familyRequest;
  familySelect?.addEventListener('change', async () => {
    if (!familySelect.value) return;
    familyRequest?.abort();
    familyRequest = new AbortController();
    familyMode.value = 'existing';
    feedback.textContent = 'Loading family details…';
    try {
      const response = await fetch(`/records/families/${encodeURIComponent(familySelect.value)}`, {signal: familyRequest.signal});
      if (!response.ok) throw new Error('Could not load family');
      const family = await response.json();
      Object.entries(family).forEach(([key, value]) => {
        const field = document.getElementById(key);
        if (field) field.value = value || '';
      });
      feedback.textContent = 'Existing family linked. Its saved information will be used when saving this student.';
    } catch (error) {
      if (error.name !== 'AbortError') feedback.textContent = 'Could not load the family. Select it again before saving.';
    }
  });
  const classSelect = document.getElementById('class_name');
  const subjects = document.getElementById('subjects');
  function filterSubjects() {
    if (!subjects || !classSelect) return;
    [...subjects.options].forEach(option => {
      const allowed = !option.dataset.class || option.dataset.class === classSelect.value;
      option.hidden = !allowed;
      option.disabled = !allowed;
      if (!allowed) option.selected = false;
    });
  }
  classSelect?.addEventListener('change', filterSubjects);
  filterSubjects();
});
