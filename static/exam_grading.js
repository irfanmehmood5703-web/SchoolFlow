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
 const form=panel.closest('form'), session=form.querySelector('[data-date-session]'), master=panel.querySelector('[data-date-all-campuses]');
 const campusChoices=[...panel.querySelectorAll('[data-date-campus-choice]')];
 const campuses=[...panel.querySelectorAll('[data-date-campus]')], classes=[...panel.querySelectorAll('[data-date-class]')], leaves=[...panel.querySelectorAll('[data-date-leaf]')];
 const test=form.querySelector('#exam_test_type'), subjects=form.querySelector('#subjects'), count=panel.querySelector('[data-date-count]');
 const selected=()=>leaves.filter(l=>l.checked&&!l.disabled);
 const available=scope=>[...scope.querySelectorAll('[data-date-leaf]')].filter(l=>!l.disabled);
 const subjectStatus=form.querySelector('[data-date-subject-status]');
 const table=form.querySelector('.repeat-table');
 let currentSubjects=[],lastScopeState='';
 // Mobile browsers can restore checked controls without emitting change.
 const scopeState=()=>JSON.stringify([session.value,campusChoices.map(c=>c.checked),leaves.map(l=>l.checked)]);
 const reconcile=()=>{if(lastScopeState!==scopeState())sync();};
 function fillSubject(input,names){
  const prev=input.value;
  input.replaceChildren(new Option('Select Subject',''),...names.map(v=>new Option(v,v)));
  if(prev&&names.includes(prev))input.value=prev;
  else if(prev){const invalid=new Option(prev+' (not available)',prev,true,true);invalid.disabled=true;input.add(invalid);}
  input.setCustomValidity(prev&&!names.includes(prev)?'Choose a subject assigned to a selected class.':'');
 }
 
 // Bulk controls remain explicit, including the single-section and
 // single-class cases. Individual selections never turn on a bulk control.
 function syncToggle(toggle,items){if(!toggle)return;toggle.disabled=!items.length;toggle.indeterminate=false;if(toggle.disabled||items.some(l=>!l.checked))toggle.checked=false;}
 function sync(){
  const eligible=campuses.filter(group=>[...group.querySelectorAll('[data-date-class]')].some(cls=>Boolean(session.value)&&cls.dataset.session===session.value));
  const eligibleNames=eligible.map(group=>group.dataset.campusName);
  campusChoices.forEach(choice=>{choice.disabled=!eligibleNames.includes(choice.value);if(choice.disabled)choice.checked=false;choice.closest('[data-date-campus-option]').hidden=choice.disabled;});
  const enabledChoices=campusChoices.filter(choice=>!choice.disabled);
  const chosenNames=enabledChoices.filter(choice=>choice.checked).map(choice=>choice.value);
  const chosenCampuses=eligible.filter(group=>chosenNames.includes(group.dataset.campusName));
  // All Campuses is an explicit bulk-selection control, not a derived
  // checked state. Selecting the sole campus individually must not tick it.
  if(master){
   master.disabled=!enabledChoices.length;
   master.indeterminate=false;
   if(master.disabled||enabledChoices.some(choice=>!choice.checked))master.checked=false;
  }
  classes.forEach(group=>{const visible=Boolean(session.value)&&group.dataset.session===session.value&&chosenCampuses.includes(group.closest('[data-date-campus]'));group.hidden=!visible;group.querySelectorAll('[data-date-leaf]').forEach(l=>{l.disabled=!visible;if(!visible)l.checked=false;});syncToggle(group.querySelector('[data-date-toggle]'),available(group));});
  campuses.forEach(group=>{group.hidden=!chosenCampuses.includes(group);syncToggle(group.querySelector(':scope > label [data-date-toggle]'),available(group));});
  const checked=selected();
  if(count)count.textContent=chosenNames.length+' campus(es) selected · '+checked.length+' class/section selection(s)';
  const testNames=dateSheetTestNames(eligible.map(group=>JSON.parse(group.dataset.testTypes)),chosenCampuses.map(group=>JSON.parse(group.dataset.testTypes)));
  const eligibleClasses=classes.filter(group=>Boolean(session.value)&&group.dataset.session===session.value&&(!chosenCampuses.length||chosenCampuses.includes(group.closest('[data-date-campus]'))));
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
  lastScopeState=scopeState();
  return subjectNames;
 }
 panel.addEventListener('change',e=>{
  const t=e.target;
  if(t.matches('[data-date-all-campuses]'))campusChoices.filter(c=>!c.disabled).forEach(c=>c.checked=t.checked);
  else if(t.matches('[data-date-campus-choice]')){if(master)master.checked=false;}
  else if(t.matches('[data-date-toggle]')){
   const scope=t.closest('fieldset');
   available(scope).forEach(l=>l.checked=t.checked);
   const campus=scope.closest('[data-date-campus]');
   if(campus&&scope!==campus){
    const parent=campus.querySelector(':scope > label [data-date-toggle]');
    if(parent)parent.checked=false;
   }else if(scope===campus){
    classes.filter(cls=>cls.closest('[data-date-campus]')===campus).forEach(cls=>{
     const child=cls.querySelector('[data-date-toggle]');if(child)child.checked=false;
    });
   }
  }else if(t.matches('[data-date-leaf]')){
   const cls=t.closest('[data-date-class]'),campus=t.closest('[data-date-campus]');
   const sectionToggle=cls.querySelector('[data-date-toggle]'),classToggle=campus.querySelector(':scope > label [data-date-toggle]');
   if(sectionToggle)sectionToggle.checked=false;if(classToggle)classToggle.checked=false;
  }
  sync();
 });
 session.addEventListener('change',()=>{if(master)master.checked=false;classes.forEach(cls=>{const t=cls.querySelector('[data-date-toggle]');if(t)t.checked=false;});campuses.forEach(c=>{const t=c.querySelector(':scope > label [data-date-toggle]');if(t)t.checked=false;});sync();});
 test.addEventListener('change',()=>{test.setCustomValidity('');[...test.options].filter(o=>o.disabled).forEach(o=>o.remove());});
 form.addEventListener('change',e=>{if(e.target.name==='subject'){e.target.setCustomValidity('');[...e.target.options].filter(o=>o.disabled).forEach(o=>o.remove());}});
 new MutationObserver(records=>records.forEach(record=>record.addedNodes.forEach(node=>{
  if(node.nodeType!==1)return;
  const input=node.querySelector('select[name=subject]');
  if(input){input.value='';fillSubject(input,currentSubjects);input.dispatchEvent(new Event('change',{bubbles:true}));}
 }))).observe(table.querySelector('tbody'),{childList:true});
 // Reconcile restored form state before interacting with other fields or saving.
 form.addEventListener('focusin',reconcile);
 form.addEventListener('input',e=>{if(!panel.contains(e.target))reconcile();});
 document.defaultView?.addEventListener('pageshow',()=>{reconcile();document.defaultView.requestAnimationFrame(reconcile);});
 document.addEventListener('visibilitychange',()=>{if(!document.hidden)reconcile();});
 form.addEventListener('submit',e=>{reconcile();const chosen=campusChoices.filter(c=>c.checked&&!c.disabled);const used=new Set(selected().map(l=>l.closest('[data-date-campus]').dataset.campusName));if(!chosen.length||!selected().length||chosen.some(c=>!used.has(c.value))){e.preventDefault();if(count){count.textContent='Select a campus and at least one class/section in every selected campus.';count.scrollIntoView({block:'nearest'});}else session.focus();}});
 sync();
});
