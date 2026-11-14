(() => {
  'use strict';
  const dialog = document.querySelector('#new-conversation');
  document.querySelectorAll('[data-new-conversation]').forEach(button => button.addEventListener('click', () => dialog.showModal()));
  document.querySelectorAll('[data-close-dialog]').forEach(button => button.addEventListener('click', () => dialog.close()));
  const form = document.querySelector('[data-conversation-form]');
  if (form) {
    let controller, timer, generation = 0;
    const recipient = form.elements.recipient, status = document.querySelector('#recipient-status');
    async function load() {
      const current = ++generation;
      if (controller) controller.abort();
      controller = new AbortController(); recipient.replaceChildren();
      const category = form.querySelector('[name=category]:checked').value;
      form.querySelector('.message-student-note').hidden = category !== 'Student';
      const query = new URLSearchParams({category, campus: form.elements.campus.value, q: form.querySelector('[data-recipient-search]').value});
      if (form.elements.student_id) query.set('student_id', form.elements.student_id.value);
      if (!query.get('campus')) {status.textContent = 'Choose a campus first.'; return;}
      status.textContent = 'Loading available contacts…';
      try {
        const response = await fetch(form.dataset.directory + '?' + query, {signal: controller.signal, headers: {Accept: 'application/json'}});
        if (!response.ok) throw Error('Could not load contacts. Check your access and selected child.');
        const data = await response.json(); if (current !== generation) return;
        data.people.forEach(person => {const option = document.createElement('option'); option.value = person.value; option.textContent = person.label; recipient.append(option);});
        status.textContent = data.people.length ? 'Choose a person from the list (up to 100 matches).' : 'No available contacts. Check school setup, teacher assignments and Messages permissions.';
      } catch (error) {if (error.name !== 'AbortError' && current === generation) status.textContent = error.message;}
    }
    form.querySelectorAll('[name=category], [name=campus]').forEach(input => input.addEventListener('change', load));
    if (form.elements.student_id) form.elements.student_id.addEventListener('change', () => {const option=form.elements.student_id.selectedOptions[0]; if(option?.dataset.campus)form.elements.campus.value=option.dataset.campus; load();});
    form.querySelector('[data-recipient-search]').addEventListener('input', () => {clearTimeout(timer);timer=setTimeout(load,200);});
    dialog.addEventListener('close', () => {generation++; if(controller)controller.abort();});
  }
  const read = document.querySelector('[data-mark-read]');
  if (read) {
    let sent = false;
    const mark = async () => {if(sent || document.visibilityState !== 'visible')return; sent=true;
      try {const response=await fetch(read.action,{method:'POST',body:new FormData(read)}); if(response.status===204)read.hidden=true;else sent=false;} catch {sent=false;}
    };
    document.addEventListener('visibilitychange',mark); mark();
  }
  document.querySelectorAll('[data-transcript-export]').forEach(button=>button.addEventListener('click',event=>{
    if(!button.form.elements.confirm.checked || !confirm('Export the full text of every conversation in the current filter, including blocked messages? Each export is recorded in the access log.'))event.preventDefault();
  }));
  // Record PCM WAV so the server can validate duration independently of the
  // browser timer. Microphone samples never leave this page until Send.
  document.querySelectorAll('[data-voice-controls]').forEach(panel => {
    const record=panel.querySelector('[data-record]'), stop=panel.querySelector('[data-stop]'), remove=panel.querySelector('[data-remove-voice]'), status=panel.querySelector('[data-voice-status]'), preview=panel.querySelector('audio'), input=panel.querySelector('input');
    let stream, context, processor, source, chunks=[], count=0, timer, url, stopped=true, captureRequest=0;
    const clear = () => {if(url)URL.revokeObjectURL(url);url=null;preview.removeAttribute('src');preview.hidden=true;input.value='';remove.hidden=true;};
    const cleanup = () => {clearTimeout(timer);stream?.getTracks().forEach(track=>track.stop());processor?.disconnect();source?.disconnect();if(context && context.state!=='closed')context.close();record.disabled=false;stop.disabled=true;};
    const finish = () => {
      if(stopped)return;stopped=true;
      const inputRate=context.sampleRate, rate=16000, sourceCount=Math.min(count,Math.floor(inputRate*Number(panel.dataset.maxSeconds))), n=Math.floor(sourceCount*rate/inputRate), samples=new Float32Array(sourceCount), buffer=new ArrayBuffer(44+n*2), view=new DataView(buffer);
      let copied=0;for(const chunk of chunks){const remaining=sourceCount-copied;if(remaining<=0)break;const part=chunk.subarray(0,remaining);samples.set(part,copied);copied+=part.length;}
      const text=(offset,value)=>{for(let i=0;i<value.length;i++)view.setUint8(offset+i,value.charCodeAt(i));};
      text(0,'RIFF');view.setUint32(4,36+n*2,true);text(8,'WAVE');text(12,'fmt ');view.setUint32(16,16,true);view.setUint16(20,1,true);view.setUint16(22,1,true);view.setUint32(24,rate,true);view.setUint32(28,rate*2,true);view.setUint16(32,2,true);view.setUint16(34,16,true);text(36,'data');view.setUint32(40,n*2,true);
      let offset=44;for(let index=0;index<n;index++){const position=index*inputRate/rate, left=Math.floor(position), fraction=position-left, sample=samples[left]*(1-fraction)+(samples[Math.min(left+1,sourceCount-1)]||0)*fraction;const value=Math.max(-1,Math.min(1,sample));view.setInt16(offset,value<0?value*32768:value*32767,true);offset+=2;}
      cleanup();chunks=[];clear();
      if(!n){status.textContent='No audio recorded.';return;}
      const file=new File([buffer],'voice-note.wav',{type:'audio/wav'}), transfer=new DataTransfer();transfer.items.add(file);input.files=transfer.files;url=URL.createObjectURL(file);preview.src=url;preview.hidden=false;remove.hidden=false;status.textContent='Voice note ready. Review before sending.';
    };
    record.addEventListener('click',async()=>{
      const requestNumber=++captureRequest;record.disabled=true;status.textContent='Requesting microphone permission…';
      try {clear();const captured=await navigator.mediaDevices.getUserMedia({audio:true});if(requestNumber!==captureRequest || document.visibilityState!=='visible' || (panel.closest('dialog') && !panel.closest('dialog').open)){captured.getTracks().forEach(track=>track.stop());return;}stream=captured;context=new AudioContext();await context.resume();if(requestNumber!==captureRequest || document.visibilityState!=='visible' || (panel.closest('dialog') && !panel.closest('dialog').open)){stopped=true;cleanup();return;}source=context.createMediaStreamSource(stream);processor=context.createScriptProcessor(4096,1,1);chunks=[];count=0;stopped=false;processor.onaudioprocess=event=>{if(stopped)return;const data=new Float32Array(event.inputBuffer.getChannelData(0));chunks.push(data);count+=data.length;};source.connect(processor);processor.connect(context.destination);record.disabled=true;stop.disabled=false;status.textContent='Recording… press Stop to review.';timer=setTimeout(finish,Number(panel.dataset.maxSeconds)*1000);
      } catch {stopped=true;cleanup();status.textContent='Microphone recording is unavailable. Check browser permission or attach an audio file.';}
    });
    document.addEventListener('visibilitychange',()=>{if(document.visibilityState==='hidden'){captureRequest++;if(!stopped)finish();else record.disabled=false;}});
    stop.addEventListener('click',finish);remove.addEventListener('click',()=>{clear();status.textContent='Recording removed.';});
    panel.closest('form').addEventListener('submit',event=>{if(!stopped){event.preventDefault();status.textContent='Stop and review the recording before sending.';}});
    dialog?.addEventListener('close',()=>{captureRequest++;record.disabled=false;if(!stopped){stopped=true;cleanup();chunks=[];status.textContent='Recording cancelled.';}});
    const pauseCapture=()=>{captureRequest++;stopped=true;cleanup();if(url){URL.revokeObjectURL(url);url=null;}};
    window.addEventListener('pagehide',pauseCapture);
    window.addEventListener('schoolflow:pause',()=>{captureRequest++;if(!stopped)finish();else record.disabled=false;});
  });
})();
