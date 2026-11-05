(() => {
  const root = document.querySelector('[data-attendance-scanner]');
  if (!root) return;
  const field = name => root.querySelector(`[name="${name}"]`);
  const result = root.querySelector('[data-scan-result]'), video = root.querySelector('video');
  const retry = root.querySelector('[data-qr-retry]');
  let stream, timer, heartbeatTimer, active = false, busy = false, last = null, recent = '', recentAt = 0;
  const status = text => result.textContent = text;
  function connection() {
    const id = field('device').value.trim(), code = field('institute').value.trim().toUpperCase(), key = field('key').value.trim();
    if (!/^[1-9]\d*$/.test(id) || !/^[A-Z0-9][A-Z0-9-]{2,39}$/.test(code) || !/^[A-Za-z0-9_-]{40,60}$/.test(key)) throw new Error('Enter institute code, device ID and connection key.');
    return { id, headers: { 'Content-Type': 'application/json', 'X-Institute-Code': code, 'Authorization': `Bearer ${key}` } };
  }
  async function post(path, payload) {
    const { id, headers } = connection();
    const response = await fetch(`/api/attendance/devices/${id}/${path}`, { method: 'POST', headers, body: JSON.stringify(payload), credentials: 'omit' });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.error || `Device request refused (${response.status}).`);
    return data;
  }
  async function send(value, repeat = false) {
    if (busy) return;
    if (!repeat && !/^schoolflow:(student|employee):[a-f0-9]{64}$/.test(value)) { status('Use a SchoolFlow student or employee QR code.'); return; }
    busy = true;
    try {
      connection();
      if (!repeat) last = { event_id: crypto.randomUUID().replaceAll('-', ''), qr_token: value, direction: field('direction').value, occurred_at: new Date().toISOString() };
      if (!last) return;
      const data = await post('events', last);
      retry.disabled = true;
      status(`${data.outcome}: ${data.reason}${data.replayed ? ' Original submission confirmed.' : ''}`);
    } catch (error) { retry.disabled = !last; status(`${error.message} Retry keeps the same event ID.`); }
    finally { busy = false; }
  }
  function stop() { active = false; clearTimeout(timer); clearInterval(heartbeatTimer); stream?.getTracks().forEach(track => track.stop()); stream = null; video.srcObject = null; video.hidden = true; }
  root.querySelector('[data-camera-start]').addEventListener('click', async () => {
    stop();
    try {
      if (!('BarcodeDetector' in window) || !navigator.mediaDevices?.getUserMedia) throw new Error('This browser cannot scan QR with its camera. Use a USB scanner or paste the QR value below.');
      const detector = new BarcodeDetector({ formats: ['qr_code'] });
      const info = await post('heartbeat', { model: 'SchoolFlow browser QR scanner', client_version: '1' });
      if (info.status === 'Suspended') throw new Error('This device is suspended.');
      stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: 'environment' }, audio: false });
      video.srcObject = stream; video.hidden = false; await video.play(); active = true; status('Camera ready.');
      heartbeatTimer = setInterval(() => post('heartbeat', { model: 'SchoolFlow browser QR scanner', client_version: '1' }).catch(error => { stop(); status(error.message); }), 40000);
      const scan = async () => {
        if (!active) return;
        try {
          const codes = await detector.detect(video);
          const value = codes[0]?.rawValue;
          if (value && (value !== recent || Date.now() - recentAt > 4000)) { recent = value; recentAt = Date.now(); await send(value); }
        } catch { /* Camera frames can be temporarily unavailable. */ }
        if (active) timer = setTimeout(scan, 300);
      };
      scan();
    } catch (error) { stop(); status(error.message); }
  });
  root.querySelector('[data-camera-stop]').addEventListener('click', () => { stop(); status('Camera stopped.'); });
  root.querySelector('[data-qr-send]').addEventListener('click', () => send(field('qr').value.trim()));
  field('qr').addEventListener('keydown', event => { if (event.key === 'Enter') { event.preventDefault(); send(field('qr').value.trim()); } });
  retry.addEventListener('click', () => send('', true));
  window.addEventListener('pagehide', () => { stop(); field('key').value = ''; last = null; });
})();
