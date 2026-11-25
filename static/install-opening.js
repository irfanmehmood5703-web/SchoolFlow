if ('serviceWorker' in navigator && window.isSecureContext && window.top === window) {
  navigator.serviceWorker.register('/schoolflow-worker.js').catch(() => {
    // A browser that blocks service workers can still use the SchoolFlow start link.
  });
}
