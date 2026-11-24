const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');
const sandbox={document:{addEventListener(){}}};
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(path.join(__dirname,'../static/exam_grading.js'),'utf8'),sandbox);
const result=(eligible,selected)=>Array.from(sandbox.dateSheetTestNames(eligible,selected));
const north=['Monthly','First Term','Second Term','Final Term'],south=['Monthly','Weekly','First Term'];
assert.deepEqual(result([north],[]),north);
assert.deepEqual(result([north,south],[]),[...north,'Weekly']);
assert.deepEqual(result([north,south],[north]),north);
assert.deepEqual(result([north,south],[north,south]),['Monthly','First Term']);
assert.deepEqual(result([],[]),[]);
assert.deepEqual(result([north,south],[[]]),[]);
console.log('PASS Date sheet test types: initial list, selected campus, intersection, empty selection');

const subjects=(eligible,selected)=>Array.from(sandbox.dateSheetSubjectNames(eligible,selected));
assert.deepEqual(subjects([['Math','English'],['Physics']],[]),['Math','English','Physics']);
assert.deepEqual(subjects([['Math','English'],['Physics']],[['Math','English'],['Physics']]),['Math','English','Physics']);
assert.deepEqual(subjects([['Math','English'],['Physics']],[['Physics']]),['Physics']);
assert.deepEqual(subjects([['Math'],['Math','English']],[['Math'],['Math','English']]),['Math','English']);
assert.deepEqual(subjects([],[]),[]);
console.log('PASS Date sheet subjects: disjoint classes, selected class, duplicates, initial list, empty list');


function verifyCampusControls(source,names=['North','South']){
 const assert=(ok,message)=>{if(!ok)throw Error(message);};
 const callbacks=[];
 const doc={addEventListener(type,fn){callbacks.push(fn);}};
 const mk=(kind,attrs={})=>({kind,checked:false,disabled:false,hidden:false,dataset:{},value:'',options:[],...attrs,handlers:{},addEventListener(type,fn){this.handlers[type]=fn;},matches(selector){return selector===this.kind;},setCustomValidity(){},replaceChildren(...o){this.options=o;this.value=o[0]?.value||'';},add(o){this.options.push(o);this.value=o.value;},remove(){},scrollIntoView(){}});
 const master=mk('[data-date-all-campuses]'), session=mk('session',{value:'2027'}), count=mk('count'), subjectStatus=mk('status'), tests=mk('test'), subjects=mk('subjects'), table=mk('table'), body=mk('body');
 table.querySelector=()=>body;
 const choices=[],campuses=[],classes=[],leaves=[],classToggles=[],sectionToggles=[];
 for(const name of names){
  const choice=mk('[data-date-campus-choice]',{value:name});choice.closest=()=>mk('label');choices.push(choice);
  const group=mk('campus',{dataset:{campusName:name,testTypes:'["Monthly"]'}}),toggle=mk('[data-date-toggle]');campuses.push(group);
  const cls=mk('class',{dataset:{session:'2027',subjects:'["Math"]'}}),ct=mk('[data-date-toggle]'),leaf=mk('[data-date-leaf]');classes.push(cls);leaves.push(leaf);
  group.querySelectorAll=s=>s==='[data-date-class]'?[cls]:[leaf];group.querySelector=()=>toggle;
  cls.querySelectorAll=()=>[leaf];cls.querySelector=()=>ct;cls.closest=()=>group;
  group.closest=()=>group;
  leaf.closest=s=>s==='[data-date-class]'?cls:group;toggle.closest=()=>group;ct.closest=()=>cls;
  classToggles.push(toggle);sectionToggles.push(ct);
 }
 const panel=mk('panel'),form=mk('form');panel.closest=()=>form;
 panel.querySelectorAll=s=>({'[data-date-campus-choice]':choices,'[data-date-campus]':campuses,'[data-date-class]':classes,'[data-date-leaf]':leaves}[s]||[]);
 panel.querySelector=s=>({'[data-date-all-campuses]':master,'[data-date-count]':count}[s]);
 form.querySelector=s=>({'[data-date-session]':session,'#exam_test_type':tests,'#subjects':subjects,'[data-date-subject-status]':subjectStatus,'.repeat-table':table}[s]);
 form.querySelectorAll=()=>[];doc.querySelector=()=>panel;
 new Function('document','Option','MutationObserver',source)(doc,function(label,value){this.value=value;this.label=label;},function(){this.observe=()=>{};});
 callbacks[1]();
 const change=t=>panel.handlers.change({target:t});
 assert(campuses.every(c=>c.hidden),'Initial campus panels hidden');
 choices[0].checked=true;change(choices[0]);
 if(names.length===1){
  assert(choices[0].checked&&!master.checked&&!master.indeterminate,'Selecting RazaAbad alone must not tick All Campuses');
  assert(!campuses[0].hidden&&!leaves[0].checked,'Individual campus opens its classes without selecting them');
  leaves[0].checked=true;change(leaves[0]);
  assert(!master.checked,'Selecting a class must not tick All Campuses');
  assert(!sectionToggles[0].checked&&!classToggles[0].checked,'Selecting Section A must not tick All Sections or All Classes');
  sectionToggles[0].checked=true;change(sectionToggles[0]);
  assert(sectionToggles[0].checked&&leaves[0].checked&&!classToggles[0].checked,'Explicit All Sections selects leaves but not All Classes');
  leaves[0].checked=false;change(leaves[0]);
  assert(!sectionToggles[0].checked&&!classToggles[0].checked,'Individual deselection clears bulk controls');
  leaves[0].checked=true;change(leaves[0]);
  assert(!sectionToggles[0].checked&&!classToggles[0].checked,'Individual reselection does not tick bulk controls');
  classToggles[0].checked=true;change(classToggles[0]);
  assert(classToggles[0].checked&&leaves[0].checked&&!sectionToggles[0].checked,'Explicit All Classes selects sections without ticking All Sections');
  classToggles[0].checked=false;change(classToggles[0]);
  assert(!leaves[0].checked&&!sectionToggles[0].checked,'Explicit All Classes deselects leaves');
  leaves[0].checked=true;change(leaves[0]);
  master.checked=true;change(master);
  assert(master.checked&&choices[0].checked,'Explicit All Campuses selection works with one campus');
  master.checked=false;change(master);
  assert(!choices[0].checked&&!leaves[0].checked&&campuses[0].hidden,'Explicit All Campuses deselection clears its campus and classes');
  choices[0].checked=true;change(choices[0]);
  assert(!master.checked,'Reselecting the sole campus is still independent');
  return 13;
 }
 assert(!campuses[0].hidden&&campuses[1].hidden,'Only selected campus shown');
 assert(!leaves[0].checked&&!leaves[1].checked,'Campus selection does not select classes');
 leaves[0].checked=true;change(leaves[0]);
 assert(choices[0].checked&&!choices[1].checked&&!master.checked,'Class selection does not select another campus');
 assert(!sectionToggles[0].checked&&!classToggles[0].checked,'Manual section remains independent');
 sectionToggles[0].checked=true;change(sectionToggles[0]);
 assert(sectionToggles[0].checked&&!classToggles[0].checked&&!leaves[1].checked,'All Sections only affects its own class');
 master.checked=true;change(master);
 assert(choices.every(c=>c.checked)&&!leaves[1].checked,'All campuses does not select classes');
 choices[0].checked=false;change(choices[0]);
 assert(leaves[0].disabled&&!leaves[0].checked&&campuses[0].hidden,'Deselect clears only its classes');
 choices[0].checked=true;change(choices[0]);
 assert(choices.every(c=>c.checked)&&!master.checked,'Individually selecting all campuses does not tick the explicit bulk control');
 master.checked=true;change(master);
 assert(master.checked,'Explicit bulk control remains ticked until changed');
 return 10;
}

console.log('PASS '+verifyCampusControls(fs.readFileSync(path.join(__dirname,'../static/exam_grading.js'),'utf8'))+' independent campus selection interaction checks');

console.log('PASS '+verifyCampusControls(fs.readFileSync(path.join(__dirname,'../static/exam_grading.js'),'utf8'),['RazaAbad'])+' single-campus interaction checks');
