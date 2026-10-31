'use strict';
document.addEventListener('DOMContentLoaded', () => {
  const admissionForm = document.querySelector('form[data-kind="student"]');
  let admissionMappings;
  let applyAdmissionMap = () => {};
  if (admissionForm) {
    const keys = ['campus','class_name','section','group_name','academic_session','fee_plan'];
    const fields = Object.fromEntries(keys.map(key => [key, document.getElementById(key)]));
    const original = Object.fromEntries(keys.map(key => [key, fields[key].value]));
    const catalog = Object.fromEntries(keys.map(key => [key, [...fields[key].options].filter(o => o.value).map(o => ({value:o.value,label:o.textContent}))]));
    const feedback = document.getElementById('admission-map-feedback');
    function setChoices(key, allowed, preserve) {
      const select = fields[key], value = select.value;
      const values = allowed === null ? catalog[key].map(o => o.value) : allowed;
      select.replaceChildren(new Option('Select ' + select.labels[0].textContent.replace('*','').trim(),''));
      [...new Set(values)].forEach(v => select.add(new Option(v,v)));
      if (value && !values.includes(value) && preserve) select.add(new Option(value + ' (saved selection)',value));
      select.value = [...select.options].some(o => o.value === value) ? value : '';
    }
    applyAdmissionMap = () => {
      if (!admissionMappings) return;
      const preserve = admissionForm.dataset.existing === 'true' && keys.every(k => fields[k].value === original[k]);
      const campus = fields.campus.value;
      const inactive = admissionMappings.campuses[campus] === false;
      const mapped = Object.prototype.hasOwnProperty.call(admissionMappings.maps,campus);
      const maps = admissionMappings.maps[campus] || [];
      setChoices('class_name',mapped ? maps.map(r => r.class_name) : null,preserve);
      const row = maps.find(r => r.class_name === fields.class_name.value);
      for (const [key,source] of [['section','sections'],['group_name','groups'],['fee_plan','fee_plans']]) {
        setChoices(key,mapped ? (row?.[source] || []) : null,preserve);
      }
      setChoices('academic_session',mapped ? (row ? [row.academic_session] : []) : null,preserve);
      if (row && !fields.academic_session.value) fields.academic_session.value = row.academic_session;
      feedback.textContent = inactive ? 'This campus is inactive. New admissions need an active campus.' : mapped ?
        'Choices follow the saved campus/class map. Change the map in Core Settings → Institute Setup to offer another combination.' :
        'This campus has no class map yet. Existing catalog choices remain available; set up its links in Core Settings → Institute Setup.';
      document.getElementById('class_name').dispatchEvent(new Event('subjects-refresh'));
    };
    fields.campus.addEventListener('change',applyAdmissionMap);
    fields.class_name.addEventListener('change',applyAdmissionMap);
    fetch('/workspace/core/admission-options').then(r => { if (!r.ok) throw new Error(); return r.json(); }).then(data => { admissionMappings = data; applyAdmissionMap(); }).catch(() => {
      feedback.textContent = 'Could not load the class map. Reload before saving; the server still checks your selections.';
    });
    admissionForm.addEventListener('catalog-option-added', event => {
      const category = event.detail.category;
      if (catalog[category]) catalog[category].push({value:event.detail.value,label:event.detail.label});
      applyAdmissionMap();
    });
  }
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
        admissionForm?.dispatchEvent(new CustomEvent('catalog-option-added',{detail:item}));
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
  let subjectMappings;
  function filterSubjects() {
    if (!subjects || !classSelect) return;
    [...subjects.options].forEach(option => {
      const campus=document.getElementById('campus')?.value;
      const linked=subjectMappings?.[campus]?.[classSelect.value];
      const allowed = (!option.dataset.class || option.dataset.class === classSelect.value) && (!linked || linked.includes(option.value));
      option.hidden = !allowed;
      option.disabled = !allowed;
      if (!allowed) option.selected = false;
    });
  }
  classSelect?.addEventListener('change', filterSubjects);
  classSelect?.addEventListener('subjects-refresh', filterSubjects);
  if(subjects){
    document.getElementById('campus')?.addEventListener('change',filterSubjects);
    fetch('/workspace/core/exam/subject-options').then(r=>r.ok?r.json():Promise.reject()).then(data=>{subjectMappings=data;filterSubjects()}).catch(()=>{});
  }
  const role=document.getElementById('role'),group=document.getElementById('designation_group');
  if(role&&group)fetch('/workspace/core/hrm/designation-options').then(r=>r.ok?r.json():Promise.reject()).then(links=>{
    const update=()=>[...role.options].forEach(o=>{const valid=!links[o.value]||links[o.value]===group.value;o.hidden=!valid;o.disabled=!valid;if(!valid&&o.selected)role.value=''});
    group.addEventListener('change',update);update();
  }).catch(()=>{});
  filterSubjects();
});
