(() => {
  const form = document.querySelector('form[data-check-signin]');
  if (!form || typeof form.requestSubmit !== 'function') return;

  const status = document.createElement('p');
  status.setAttribute('role', 'status');
  status.className = 'muted';
  form.after(status);
  let checking = false;
  let ready = false;

  form.addEventListener('submit', async event => {
    if (ready) {
      ready = false;
      return;
    }
    event.preventDefault();
    if (checking) return;

    checking = true;
    status.textContent = 'Connecting to SchoolFlow…';
    form.setAttribute('aria-busy', 'true');
    const deadline = Date.now() + 105_000;
    try {
      while (Date.now() < deadline) {
        if (await isReady(Math.min(24_000, deadline - Date.now()))) {
          status.textContent = 'Connected. Continuing sign-in…';
          ready = true;
          form.requestSubmit(event.submitter || undefined);
          ready = false;
          return;
        }
        if (Date.now() < deadline) await new Promise(resolve => setTimeout(resolve, 2_500));
      }
      status.textContent = 'SchoolFlow is taking longer than usual. Press the button again to retry.';
    } finally {
      checking = false;
      form.removeAttribute('aria-busy');
    }
  });

  async function isReady(timeout) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeout);
    try {
      const response = await fetch('/healthz', {
        cache: 'no-store',
        credentials: 'omit',
        redirect: 'error',
        signal: controller.signal
      });
      return response.ok && response.headers.get('Content-Type')?.includes('application/json')
        && (await response.json()).status === 'ok';
    } catch {
      return false;
    } finally {
      clearTimeout(timer);
    }
  }
})();
