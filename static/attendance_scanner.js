(() => {
  const root = document.querySelector('[data-attendance-scanner]');
  if (!root) return;
  const field = name => root.querySelector(`[name="${name}"]`);
  const result = root.querySelector('[data-scan-result]'), video = root.querySelector('video');
  const retry = root.querySelector('[data-qr-retry]');
  let stream, timer, heartbeatTimer, active = false, busy = false, last = null, recent = '', recentAt = 0;
  const status = text => result.textContent = text;
  const connectButton=root.querySelector('[data-connect]'), disconnectButton=root.querySelector('[data-disconnect]'), cameraButton=root.querySelector('[data-camera-start]'), recordButton=root.querySelector('[data-qr-send]'), connectionState=root.querySelector('[data-connection-state]');
  let connected=false, pairingBusy=false;
  function setConnection(info) {
    connected=!!info?.connected;
    connectionState.textContent=connected?'Connected · '+info.name+' · '+info.campus:'Disconnected · connect a registered QR device.';
    connectionState.dataset.connected=connected?'yes':'no';
    if(connected){field('device').value=info.device_id;field('key').value='';}
    field('device').disabled=connected;field('key').disabled=connected;field('remember').disabled=connected;
    connectButton.disabled=connected;disconnectButton.disabled=!connected;
    cameraButton.disabled=!connected;recordButton.disabled=!connected;
    if(!connected){stop();retry.disabled=true;last=null;}
  }
  async function call(action, fields={}) {
    const body=new URLSearchParams({_csrf:field('scanner_csrf').value,action,...fields});
    const response=await fetch(window.location.pathname.replace(/\/$/,'')+'/connection',{method:'POST',credentials:'same-origin',body,cache:'no-store'});
    const data=await response.json().catch(()=>({}));
    if(!response.ok){if(response.status===401||response.redirected){setConnection(null);throw new Error(data.error||'Sign in and reconnect the scanner.');}throw new Error(data.error||'Connection request refused ('+response.status+').');}
    if(response.redirected||!Object.keys(data).length){setConnection(null);throw new Error('Sign in to SchoolFlow again.');}
    return data;
  }
  function connection(){if(!connected)throw new Error('Connect this device first.');}
  async function post(path,payload){connection();return call(path,path==='events'?{payload:JSON.stringify(payload)}:{});}
  connectButton.addEventListener('click',async()=>{
    if(pairingBusy)return;pairingBusy=true;connectButton.disabled=true;
    try{const info=await call('connect',{device:field('device').value.trim(),key:field('key').value.trim(),remember:field('remember').checked?'1':'0'});setConnection(info);status('Device connected. Ready to scan.');}
    catch(error){status(error.message);}finally{pairingBusy=false;connectButton.disabled=connected;}
  });
  disconnectButton.addEventListener('click',async()=>{
    if(pairingBusy)return;pairingBusy=true;disconnectButton.disabled=true;stop();
    try{await call('disconnect');setConnection(null);field('key').value='';status('Device disconnected.');}
    catch(error){status(error.message);disconnectButton.disabled=!connected;}finally{pairingBusy=false;}
  });
  connectButton.disabled=true;
  call('status').then(info=>{setConnection(info);status('Saved device connected. Ready to scan.');}).catch(error=>{setConnection(null);status(error.message);});
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
      if (!info.connected) throw new Error('This device is disconnected.');
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
  window.addEventListener('pageshow',event=>{if(event.persisted)call('status').then(setConnection).catch(()=>setConnection(null));});
})();
