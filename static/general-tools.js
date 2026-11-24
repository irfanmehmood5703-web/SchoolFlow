(()=>{document.querySelectorAll('[data-copy-release]').forEach(button=>button.addEventListener('click',async()=>{const status=document.getElementById('release-copy-status');try{await navigator.clipboard.writeText(button.dataset.copyRelease);status.textContent='Link copied.';}catch{status.textContent='Copy the link from the download button.';}}));document.querySelectorAll('[data-widget-expand]').forEach(button=>button.addEventListener('click',()=>{const detail=button.closest('.widget').querySelector('.widget-expanded');detail.hidden=!detail.hidden;button.setAttribute('aria-expanded',String(!detail.hidden));button.textContent=detail.hidden?'Expand':'Collapse';}));document.querySelectorAll('[data-widget-move]').forEach(button=>button.addEventListener('click',()=>{const row=button.closest('[data-widget-choice]');if(button.dataset.widgetMove==='up'&&row.previousElementSibling)row.previousElementSibling.before(row);else if(button.dataset.widgetMove==='down'&&row.nextElementSibling)row.nextElementSibling.after(row);}));})();

(() => {
  const status = document.querySelector('[data-build-status-url]');
  if (!status) return;
  const deadline = Date.now() + 30 * 60 * 1000;
  async function refreshBuild() {
    if (!document.hidden) {
      try {
        const response = await fetch(status.dataset.buildStatusUrl, {
          cache: 'no-store',
          headers: { Accept: 'application/json' },
          redirect: 'error'
        });
        if (response.ok) {
          const {state} = await response.json();
          if (state === 'ready' || state === 'failed') {
            window.location.reload();
            return;
          }
          if (state === 'queued' || state === 'building') status.textContent = state;
        }
      } catch {
        // Keep the visible state and retry when the server is reachable.
      }
    }
    if (Date.now() < deadline) setTimeout(refreshBuild, 25000);
  }
  setTimeout(refreshBuild, 25000);
})();
