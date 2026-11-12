(()=>{
const search=document.getElementById('diary-class-search'), classSelect=document.getElementById('class_name');
if(search&&classSelect) search.addEventListener('input',()=>{[...classSelect.options].forEach(o=>o.hidden=!!o.value&&!o.text.toLowerCase().includes(search.value.toLowerCase()));});
const all=document.getElementById('all-students'), list=document.getElementById('class-checks');
if(all&&list){
const boxes=[...list.querySelectorAll('input')];
const sync=()=>{boxes.forEach(b=>{b.disabled=all.checked;if(all.checked)b.checked=false;});};
all.addEventListener('change',sync);sync();
document.getElementById('clear-classes').addEventListener('click',()=>{all.checked=false;boxes.forEach(b=>b.checked=false);sync();});
document.getElementById('class-search').addEventListener('input',e=>{list.querySelectorAll('label').forEach(l=>l.hidden=!l.textContent.toLowerCase().includes(e.target.value.toLowerCase()));});
}
})();
