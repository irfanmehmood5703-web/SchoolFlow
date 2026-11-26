/* Independent, configured class/subject choices for each weekly lecture. */
(() => {
  const form = document.querySelector('[data-lecture-form]');
  if (!form) return;
  const catalog = JSON.parse(form.querySelector('[data-lecture-catalog]').dataset.lectureCatalog);
  const rows = form.querySelector('[data-lecture-rows]');
  const add = form.querySelector('[data-add-lecture]');
  const limit = 12;
  const field = (row, name) => row.querySelector('[data-lecture-' + name + ']');
  const options = (select, list, placeholder, auto = false) => {
    const previous = select.value;
    select.replaceChildren(new Option(placeholder, ''));
    list.forEach(([value, label]) => select.add(new Option(label, value)));
    select.value = list.some(([value]) => value === previous) ? previous : '';
    if (auto && !select.value && list.length === 1) select.value = list[0][0];
    select.disabled = !list.length;
  };
  const update = (row, changed = '') => {
    const teacher = field(row, 'teacher'), campus = field(row, 'campus');
    const cls = field(row, 'class'), section = field(row, 'section'), subject = field(row, 'subject');
    const hint = field(row, 'hint');
    const selected = catalog.teachers.find(t => t.id === teacher.value);
    if (changed === 'teacher') { campus.value = ''; cls.value = ''; section.value = ''; subject.value = ''; }
    if (changed === 'campus') { cls.value = ''; section.value = ''; subject.value = ''; }
    if (changed === 'class') { section.value = ''; subject.value = ''; }
    if (changed === 'section') subject.value = '';
    options(campus, (selected?.campuses || []).map(c => [c,c]), 'Choose campus', true);
    const school = catalog.campuses.find(c => c.name === campus.value);
    options(cls, (school?.classes || []).map(c => [c.name,c.name]), 'Choose class');
    const cohort = school?.classes.find(c => c.name === cls.value);
    options(section, (cohort?.sections || []).map(s => [s,s]), 'Choose section', true);
    const whole = section.value && catalog.full_classes.some(a => a.teacher === teacher.value && a.campus === campus.value && a.class_name === cls.value && a.section === section.value);
    const subjects = section.value ? (cohort?.subjects || []).map(s => ['subject:' + s,s]) : [];
    if (whole) subjects.unshift(['class-period','Class period (whole class)']);
    options(subject, subjects, 'Choose subject');
    hint.textContent = !selected ? 'Choose a teacher.' :
      !selected.campuses.length ? 'No configured classes in this teacher’s permitted campuses.' :
      !cls.value ? 'Choose the class where this lecture will be taught.' :
      !section.value ? 'Choose section.' :
      !subjects.length ? 'No subjects configured for this class.' :
      !subject.value ? 'Choose the subject for this lecture.' :
      whole ? 'Uses existing whole-class access.' : 'Subject access will be assigned automatically if needed.';
  };
  const refresh = () => {
    const list = [...rows.querySelectorAll('[data-lecture-row]')];
    list.forEach((row, index) => {
      row.querySelector('[data-lecture-label]').textContent = 'Lecture ' + (index + 1);
      row.querySelector('[data-remove-lecture]').hidden = list.length === 1;
    });
    add.disabled = list.length >= limit;
  };
  const first = rows.firstElementChild;
  field(first, 'teacher').disabled = false;
  update(first);
  add.hidden = false;
  add.addEventListener('click', () => {
    if (rows.children.length >= limit) return;
    const last = rows.lastElementChild;
    const row = first.cloneNode(true);
    field(row, 'teacher').value = field(last, 'teacher').value;
    field(row, 'campus').value = field(last, 'campus').value;
    field(row, 'class').value = '';
    field(row, 'section').value = '';
    field(row, 'subject').value = '';
    row.querySelector('input[type="time"]').value = '';
    rows.append(row);
    update(row);
    refresh();
    field(row, 'class').focus();
  });
  rows.addEventListener('change', event => {
    const row = event.target.closest('[data-lecture-row]');
    if (!row) return;
    for (const name of ['teacher','campus','class','section','subject']) {
      if (event.target === field(row,name)) { update(row,name); break; }
    }
  });
  rows.addEventListener('click', (event) => {
    const button = event.target.closest('[data-remove-lecture]');
    if (!button || rows.children.length < 2) return;
    button.closest('[data-lecture-row]').remove();
    refresh(); add.focus();
  });
  form.addEventListener('submit', event => {
    for (const row of rows.querySelectorAll('[data-lecture-row]')) {
      if (['teacher','campus','class','section','subject'].some(name => !field(row,name).value)) {
        event.preventDefault();
        field(row,'hint').textContent = 'Complete all lecture details before saving.';
        row.scrollIntoView({block:'center'});
        return;
      }
    }
  });
  refresh();
})();
