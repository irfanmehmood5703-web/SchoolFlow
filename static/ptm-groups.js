(()=>{
const form=document.getElementById('ptm-group-form');if(!form)return;
const campus=document.getElementById('ptm-campus'),cls=document.getElementById('ptm-class'),sessions=document.getElementById('ptm-sessions'),sections=document.getElementById('ptm-sections'),teachers=document.getElementById('ptm-teachers'),subjects=document.getElementById('ptm-subjects'),types=document.getElementById('ptm-test-type'),students=document.getElementById('ptm-students'),status=document.getElementById('ptm-options-status'),submit=document.getElementById('ptm-create');let serial=0,pending=false;
const selected=s=>[...s.selectedOptions].map(o=>o.value);
function options(s,values,prompt,reset=false){const previous=reset?[]:selected(s);s.replaceChildren();if(prompt)s.add(new Option(prompt,''));values.forEach(v=>{const id=String(v.id??v),name=v.name??v;s.add(new Option(name,id,false,previous.includes(id)));});s.disabled=!values.length;}
async function load(level){const id=++serial;pending=true;submit.disabled=true;students.replaceChildren();status.textContent='Loading meeting choices…';const q=new URLSearchParams({campus:campus.value,class_name:level==='campus'?'':cls.value});if(!['campus','class'].includes(level)){selected(sessions).forEach(v=>q.append('sessions',v));selected(sections).forEach(v=>q.append('sections',v));}
if(!campus.value){options(cls,[],'Pick a campus first');options(sessions,[]);options(sections,[]);options(teachers,[]);options(subjects,[]);status.textContent='Pick a campus first.';pending=false;return;}
try{const r=await fetch(form.dataset.optionsUrl+'?'+q,{credentials:'same-origin'});if(!r.ok)throw Error();const data=await r.json();if(id!==serial)return;
if(level==='campus')options(cls,data.classes,'Select class',true);
if(['campus','class'].includes(level)){options(sessions,data.sessions,null,true);options(sections,data.sections,null,true);options(teachers,data.teachers,null,true);options(subjects,data.subjects,null,true);options(types,data.test_types,'Any test type',true);}
for(const pupil of data.students){const label=document.createElement('label'),input=document.createElement('input');input.type='checkbox';input.name='students';input.value=pupil.id;input.checked=true;label.append(input,document.createTextNode(' '+pupil.name+' · '+pupil.admission_no+' / '+pupil.section+' / '+pupil.session));students.append(label);}
status.textContent=data.students.length?data.students.length+' active students. Clear any students who are not attending.':'Pick sessions and sections. No matching active students yet.';
}catch(e){if(id===serial)status.textContent='Could not load choices. Check your access or reload.';}finally{if(id===serial){pending=false;submit.disabled=!students.querySelector('input:checked');}}}
campus.addEventListener('change',()=>load('campus'));cls.addEventListener('change',()=>load('class'));sessions.addEventListener('change',()=>load('roster'));sections.addEventListener('change',()=>load('roster'));
students.addEventListener('change',()=>submit.disabled=pending||!students.querySelector('input:checked'));
for(const [button,value] of [['ptm-select-all',true],['ptm-clear-students',false]])document.getElementById(button).addEventListener('click',()=>{students.querySelectorAll('input').forEach(i=>i.checked=value);submit.disabled=pending||!students.querySelector('input:checked');});
form.addEventListener('submit',e=>{if(pending){e.preventDefault();status.textContent='Wait for student choices to load.';}});
})();
