'use strict';
document.addEventListener('DOMContentLoaded', () => {
  const photo = document.getElementById('photo');
  const preview = document.getElementById('photo-preview');
  const photoFeedback = document.getElementById('photo-feedback');
  const savedPreview = preview?.innerHTML;
  let photoURL;
  function clearPhotoURL() { if (photoURL) { URL.revokeObjectURL(photoURL); photoURL = null; } }
  photo?.addEventListener('change', () => {
    clearPhotoURL();
    preview.innerHTML = savedPreview;
    photoFeedback.textContent = '';
    const file = photo.files[0];
    if (!file) return;
    if (!['image/jpeg', 'image/png', 'image/webp'].includes(file.type) || file.size > 5 * 1024 * 1024 || !file.size) {
      photoFeedback.textContent = 'Choose a JPG, PNG or WebP photo up to 5 MB.';
      photo.value = ''; return;
    }
    const image = document.createElement('img');
    image.alt = 'Selected photo preview';
    image.onload = () => { photoFeedback.textContent = 'Photo selected. Save the record to keep it.'; clearPhotoURL(); };
    image.onerror = () => { photoFeedback.textContent = 'This image could not be opened. Choose another photo.'; photo.value = ''; preview.innerHTML = savedPreview; clearPhotoURL(); };
    photoURL = URL.createObjectURL(file); image.src = photoURL;
    preview.replaceChildren(image);
    const remove = document.querySelector('[name="remove_photo"]');
    if (remove) remove.checked = false;
  });
  window.addEventListener('pagehide', clearPhotoURL);
  document.querySelectorAll('.option-editor').forEach(editor => {
    const input = editor.querySelector('input');
    const button = editor.querySelector('button');
    const status = editor.querySelector('.option-feedback');
    input.addEventListener('keydown', event => { if (event.key === 'Enter') { event.preventDefault(); button.click(); } });
    button.addEventListener('click', async () => {
      if (!input.value.trim()) { status.textContent = 'Enter an option first.'; input.focus(); return; }
      button.disabled = true; status.textContent = 'Saving option…';
      try {
        const body = new URLSearchParams({_csrf: document.querySelector('[name="_csrf"]').value,
          category: editor.dataset.category, value: input.value.trim(),
          class_name: document.getElementById('class_name')?.value || ''});
        const response = await fetch('/records/options', {method: 'POST', body});
        if (!response.ok) throw new Error('Could not save. Reload if your session expired.');
        const item = await response.json();
        document.querySelectorAll('.option-editor').forEach(other => {
          if (other.dataset.category !== item.category) return;
          const select = document.getElementById(other.dataset.target);
          let option = [...select.options].find(o => o.value === item.value && (o.dataset.class || '') === item.class_name);
          if (!option) { option = new Option(item.label, item.value); if (item.category === 'subject') option.dataset.class = item.class_name; select.add(option); }
          if (other === editor) option.selected = true;
        });
        document.getElementById(editor.dataset.target).dispatchEvent(new Event('change'));
        status.textContent = 'Option added and selected.'; input.value = ''; editor.open = false;
      } catch (error) { status.textContent = error.message; }
      finally { button.disabled = false; }
    });
  });
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
