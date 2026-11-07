'use strict';
const form = document.querySelector('[data-requisition-form]');
if (form) {
  const body = form.querySelector('[data-req-items]');
  const fixed = (raw, decimals) => {
    if (raw.length>32) return null;
    if (!new RegExp('^\\d+(?:\\.\\d{1,'+decimals+'})?$').test(raw)) return null;
    const [a,b=''] = raw.split('.'); return BigInt(a)*10n**BigInt(decimals)+BigInt(b.padEnd(decimals,'0'));
  };
  const cash = value => `${value/100n}.${(value%100n).toString().padStart(2,'0')}`;
  const totals = () => {
    let total = 0n;
    body.querySelectorAll('[data-req-item]').forEach(row => {
      const q=fixed(row.querySelector('[name="qty"]').value,3), p=fixed(row.querySelector('[name="unit_price"]').value,2);
      const amount=q!==null && p!==null ? (q*p+500n)/1000n : 0n;
      row.querySelector('[data-req-amount]').textContent=cash(amount); total+=amount;
    });
    form.querySelector('[data-req-total]').textContent=cash(total);
  };
  form.querySelector('[data-req-add]').addEventListener('click', () => {
    if (body.children.length>=100) return;
    const row=body.firstElementChild.cloneNode(true);
    row.querySelectorAll('input').forEach(input => { input.value=input.name==='qty'?'1':''; }); body.append(row); totals();
  });
  body.addEventListener('click', event => {
    if (event.target.matches('[data-req-remove]') && body.children.length>1) { event.target.closest('[data-req-item]').remove(); totals(); }
  });
  body.addEventListener('input',totals);totals();
}
