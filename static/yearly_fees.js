(() => {
  const campus = document.getElementById('yearly-campus');
  const classes = document.getElementById('yearly-class');
  const source = document.getElementById('yearly-class-options');
  if (!campus || !classes || !source) return;
  const offerings = JSON.parse(source.textContent);
  campus.addEventListener('change', () => {
    classes.replaceChildren(new Option(campus.value ? 'Select class' : 'Select campus first', ''));
    for (const name of offerings[campus.value] || []) classes.add(new Option(name, name));
    classes.disabled = !campus.value;
  });
})();
