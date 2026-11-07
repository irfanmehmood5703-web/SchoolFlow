'use strict';
(() => {
 const form=document.querySelector('[data-ledger-entry]');if(!form)return;
 const kind=form.dataset.ledgerEntry,body=form.querySelector('[data-ledger-rows]');
 const template=body.querySelector('[data-ledger-row]').cloneNode(true);
 const parse=value=>{const s=value.trim();if(!s)return 0n;if(!/^\d+(?:\.\d{1,2})?$/.test(s))throw Error();const [whole,fraction='']=s.split('.');const n=BigInt(whole)*100n+BigInt((fraction+'00').slice(0,2));if(n>99999999900n)throw Error();return n;};
 const fmt=n=>`${n/100n}.${String(n%100n).padStart(2,'0')}`;
 function update(){let debit=0n,credit=0n,valid=true,used=0;const selected=new Set();
  for(const row of body.querySelectorAll('[data-ledger-row]')){
   const account=row.querySelector('select').value;const inputs=row.querySelectorAll('input[type="number"]');
   const touched=account||Array.from(inputs).some(x=>x.value)||row.querySelector('textarea').value.trim();
   if(!touched)continue;used++;if(!account)valid=false;else selected.add(account);
   try{if(kind==='journal'){const d=parse(inputs[0].value),c=parse(inputs[1].value);debit+=d;credit+=c;if((d>0n)===(c>0n))valid=false;}else{const n=parse(inputs[0].value);debit+=n;if(n===0n)valid=false;}}catch{valid=false;}
  }
  if(kind==='journal')valid=valid&&used>=2&&selected.size>=2&&debit===credit;else valid=valid&&used>=1;
  form.querySelector('[data-total-debit]').textContent=fmt(debit);
  if(kind==='journal')form.querySelector('[data-total-credit]').textContent=fmt(credit);
  form.querySelector('[data-ledger-status]').textContent=valid?(kind==='journal'?'Balanced':'Total ready to post'):'Complete the accounts and amounts'+(kind==='journal'?' and balance debit/credit.':'.');
  for(const button of form.querySelectorAll('[data-ledger-save]'))button.disabled=!valid;
  const minimum=kind==='journal'?2:1;for(const button of form.querySelectorAll('[data-remove-ledger-row]'))button.disabled=body.children.length<=minimum;
 }
 function add(){if(body.children.length>=100)return;const row=template.cloneNode(true);for(const input of row.querySelectorAll('input,textarea,select'))input.value='';body.append(row);update();row.querySelector('input').focus();}
 form.querySelector('[data-add-ledger-row]').addEventListener('click',add);
 form.addEventListener('click',event=>{if(event.target.matches('[data-remove-ledger-row]')){event.target.closest('[data-ledger-row]').remove();update();}});
 form.addEventListener('keydown',event=>{if(event.key==='Enter'&&event.target.matches('input[type="number"]')){event.preventDefault();add();}});
 form.addEventListener('input',event=>{if(event.target.matches('[data-account-search]')){const query=event.target.value.toLocaleLowerCase();const select=event.target.parentElement.querySelector('select');for(const option of select.options)option.hidden=!!option.value&&!option.text.toLocaleLowerCase().includes(query)&&!option.selected;for(const group of select.querySelectorAll('optgroup'))group.hidden=Array.from(group.children).every(o=>o.hidden);}update();});
 form.addEventListener('change',update);update();
})();
