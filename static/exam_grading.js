document.addEventListener('DOMContentLoaded',()=>{
 const modes=JSON.parse(document.getElementById('subject-grading').textContent),table=document.querySelector('.repeat-table');
 const update=row=>{const subject=row.querySelector('[name=subject]'),total=row.querySelector('[name=total]');if(!subject||!total)return;const numeric=(modes[subject.value]||'Marks')==='Marks';if(!numeric&&!total.readOnly){total.dataset.previous=total.value;total.value='0'}else if(numeric&&total.readOnly){total.value=total.dataset.previous||''}total.required=numeric;total.readOnly=!numeric;total.min=numeric?'0.01':'0';total.setAttribute('aria-label',numeric?'Total marks':'Qualitative subject: no numeric total');};
 const onSubject=e=>{if(e.target.name==='subject')update(e.target.closest('tr'))};
 table.addEventListener('input',onSubject);table.addEventListener('change',onSubject);
 new MutationObserver(()=>table.querySelectorAll('tbody tr').forEach(update)).observe(table.querySelector('tbody'),{childList:true});
 table.querySelectorAll('tbody tr').forEach(update);
});

function dateSheetTestNames(eligible,selected){
 if(selected.length)return [...new Set(selected[0])].filter(name=>selected.every(list=>list.includes(name)));
 return [...new Set(eligible.flat())];
}

function dateSheetSubjectNames(eligible,selected){
 return [...new Set((selected.length?selected:eligible).flat())];
}
 
/* Mapped date-sheet cohort selection. Only the checked, session-matched leaves submit. */
document.addEventListener('DOMContentLoaded',()=>{
 const panel=document.querySelector('[data-date-scope]');if(!panel)return;
 const form=panel.closest('form'), session=form.querySelector('[data-date-session]'), master=panel.querySelector('[data-date-all]');
 const campuses=[...panel.querySelectorAll('[data-date-campus]')], classes=[...panel.querySelectorAll('[data-date-class]')], leaves=[...panel.querySelectorAll('[data-date-leaf]')];
 const test=form.querySelector('#exam_test_type'), subjects=form.querySelector('#subjects'), count=panel.querySelector('[data-date-count]');
 const selected=()=>leaves.filter(l=>l.checked&&!l.disabled);
 const available=scope=>[...scope.querySelectorAll('[data-date-leaf]')].filter(l=>!l.disabled);
 const subjectStatus=form.querySelector('[data-date-subject-status]');
 const table=form.querySelector('.repeat-table');
 let currentSubjects=[];
 function fillSubject(input,names){
  const prev=input.value;
  input.replaceChildren(new Option('Select Subject',''),...names.map(v=>new Option(v,v)));
  if(prev&&names.includes(prev))input.value=prev;
  else if(prev){const invalid=new Option(prev+' (not available)',prev,true,true);invalid.disabled=true;input.add(invalid);}
  input.setCustomValidity(prev&&!names.includes(prev)?'Choose a subject assigned to a selected class.':'');
 }
 
 function syncToggle(toggle,items){if(!toggle)return;const n=items.filter(l=>l.checked).length;toggle.checked=items.length>0&&n===items.length;toggle.indeterminate=n>0&&n<items.length;toggle.disabled=!items.length;}
 function sync(){
  classes.forEach(group=>{const visible=Boolean(session.value)&&group.dataset.session===session.value;group.hidden=!visible;group.querySelectorAll('[data-date-leaf]').forEach(l=>{l.disabled=!visible;if(!visible)l.checked=false;});syncToggle(group.querySelector('[data-date-toggle]'),available(group));});
  campuses.forEach(group=>{const items=available(group);group.hidden=!items.length;syncToggle(group.querySelector(':scope > label [data-date-toggle]'),items);});
  syncToggle(master,available(panel));const checked=selected();
  if(count)count.textContent=checked.length+' class/section selection(s)';
  // Before any class is checked, show configured tests from campuses available
  // in this session. Once selected, only tests common to all chosen campuses apply.
  const eligible=campuses.filter(group=>available(group).length);
  const chosenCampuses=[...new Set(checked.map(l=>l.closest('[data-date-campus]')))];
  const testNames=dateSheetTestNames(eligible.map(group=>JSON.parse(group.dataset.testTypes)),chosenCampuses.map(group=>JSON.parse(group.dataset.testTypes)));
  const eligibleClasses=classes.filter(group=>available(group).length);
  const chosenClasses=[...new Set(checked.map(l=>l.closest('[data-date-class]')))];
  const subjectNames=dateSheetSubjectNames(eligibleClasses.map(group=>JSON.parse(group.dataset.subjects)),chosenClasses.map(group=>JSON.parse(group.dataset.subjects)));
  const prev=test.value;test.replaceChildren(new Option('Unclassified',''),...testNames.map(v=>new Option(v,v)));
  if(testNames.includes(prev))test.value=prev;
  if(prev&&!testNames.includes(prev)){
   const unavailable=new Option(prev+' (not available for selection)',prev,true,true);unavailable.disabled=true;test.add(unavailable);
   test.setCustomValidity('Choose an exam test type available in every selected campus.');
  }else test.setCustomValidity('');
  
  currentSubjects=subjectNames;
  subjects.replaceChildren(...subjectNames.map(v=>new Option(v,v)));
  form.querySelectorAll('select[name=subject]').forEach(input=>fillSubject(input,subjectNames));
  if(subjectStatus)subjectStatus.textContent=subjectNames.length?subjectNames.length+' configured subject(s) available. Each selected class receives only its assigned papers.':'No configured subjects for this selection. Check Subjects in Classes.';
  return subjectNames;
 }
 panel.addEventListener('change',e=>{const t=e.target;if(t.matches('[data-date-all]'))available(panel).forEach(l=>l.checked=t.checked);else if(t.matches('[data-date-toggle]'))available(t.closest('fieldset')).forEach(l=>l.checked=t.checked);sync();});
 session.addEventListener('change',sync);
 test.addEventListener('change',()=>{test.setCustomValidity('');[...test.options].filter(o=>o.disabled).forEach(o=>o.remove());});
 form.addEventListener('change',e=>{if(e.target.name==='subject'){e.target.setCustomValidity('');[...e.target.options].filter(o=>o.disabled).forEach(o=>o.remove());}});
 new MutationObserver(records=>records.forEach(record=>record.addedNodes.forEach(node=>{
  if(node.nodeType!==1)return;
  const input=node.querySelector('select[name=subject]');
  if(input){input.value='';fillSubject(input,currentSubjects);input.dispatchEvent(new Event('change',{bubbles:true}));}
 }))).observe(table.querySelector('tbody'),{childList:true});
 form.addEventListener('submit',e=>{if(!selected().length){e.preventDefault();if(count){count.textContent='Select at least one class and section.';count.scrollIntoView({block:'nearest'});}else session.focus();}});
 sync();
});
