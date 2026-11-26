(() => {
  'use strict';
  for (const button of document.querySelectorAll('[data-password-icon]')) {
    const field = document.getElementById(button.getAttribute('aria-controls'));
    if (!(field instanceof HTMLInputElement) || field.type !== 'password') continue;
    const noun = button.dataset.passwordNoun || 'password';
    const setVisible = visible => {
      const start = field.selectionStart, end = field.selectionEnd;
      field.type = visible ? 'text' : 'password';
      if (start !== null && end !== null) field.setSelectionRange(start, end);
      const label = (visible ? 'Hide ' : 'Show ') + noun;
      button.setAttribute('aria-label', label);
      button.title = label;
      button.setAttribute('aria-pressed', String(visible));
    };
    button.addEventListener('click', () => setVisible(field.type === 'password'));
    // A revealed secret should not remain visible once the user submits or leaves the app.
    field.form?.addEventListener('submit', () => setVisible(false));
    document.addEventListener('visibilitychange', () => { if (document.hidden) setVisible(false); });
    window.addEventListener('schoolflow:pause', () => setVisible(false));
  }
})();
