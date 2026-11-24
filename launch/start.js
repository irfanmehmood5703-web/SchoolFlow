const schoolFlow = 'https://schoolflow-phase1.onrender.com';
const title = document.querySelector('#title');
const status = document.querySelector('#status');
const progress = document.querySelector('#progress');
const retry = document.querySelector('#retry');

async function isReady(timeout) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeout);
  try {
    const response = await fetch(schoolFlow + '/healthz', {
      cache: 'no-store',
      credentials: 'omit',
      redirect: 'error',
      signal: controller.signal
    });
    if (!response.ok || !response.headers.get('Content-Type')?.includes('application/json')) {
      return false;
    }
    return (await response.json()).status === 'ok';
  } catch {
    return false;
  } finally {
    clearTimeout(timer);
  }
}

async function openSchoolFlow() {
  title.textContent = 'Opening SchoolFlow';
  status.textContent = 'Getting your school workspace ready.';
  progress.hidden = false;
  retry.hidden = true;
  const deadline = Date.now() + 105_000;
  const slow = setTimeout(() => {
    status.textContent = 'Your workspace is still loading.';
  }, 10_000);
  try {
    while (Date.now() < deadline) {
      if (await isReady(Math.min(24_000, deadline - Date.now()))) {
        status.textContent = 'Workspace ready. Opening SchoolFlow.';
        window.location.replace(schoolFlow + '/');
        return;
      }
      await new Promise(resolve => setTimeout(resolve, 2_500));
    }
    title.textContent = 'SchoolFlow is taking longer than usual';
    status.textContent = 'Try again to reconnect to your school workspace.';
    progress.hidden = true;
    retry.hidden = false;
    retry.focus();
  } finally {
    clearTimeout(slow);
  }
}

retry.addEventListener('click', openSchoolFlow);
openSchoolFlow();
