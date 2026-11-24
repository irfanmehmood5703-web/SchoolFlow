document.addEventListener('DOMContentLoaded',()=>{
 const form=document.querySelector('[data-award-import]');if(!form)return;
 const sources=JSON.parse(document.getElementById('award-date-sources').textContent);
 const cls=form.elements.class_name,typ=form.elements.exam_test_type,source=form.elements.source_sheet_id,rev=form.elements.source_revision,cat=form.elements.assessment_category;
 const preview=form.querySelector('[data-award-preview]'),body=form.querySelector('[data-award-papers]'),scope=form.querySelector('[data-award-scope]'),status=form.querySelector('[data-award-status]'),submit=form.querySelector('[data-award-submit]');
 const categories={'weekly':'Weekly','weekly test':'Weekly','monthly':'Monthly','monthly test':'Monthly','first term':'First Term','second term':'Second Term'};
 function show(){
  const s=sources.find(x=>String(x.id)===source.value&&x.class_name===cls.value&&x.exam_type===typ.value);
  rev.value=s?s.revision:'';submit.disabled=!s||!s.papers.length;preview.hidden=!s;body.replaceChildren();
  if(!s){scope.textContent='';return;}
  scope.textContent=[s.name,s.campus,s.class_name,s.section||'All sections',s.session].join(' · ');
  for(const p of s.papers){const tr=document.createElement('tr');for(const val of [p.subject,p.date,p.type,p.grading&&p.grading!=='Marks'?'Qualitative':p.total,p.time||'—']){const td=document.createElement('td');td.textContent=String(val??'');tr.append(td);}body.append(tr);}
  status.textContent=s.papers.length+' paper(s) loaded. No subject entry needed.';
 }
 function filter(){
  const prev=source.value,match=sources.filter(s=>s.class_name===cls.value&&s.exam_type===typ.value);
  source.replaceChildren(new Option('Select matching Date Sheet',''),...match.map(s=>new Option([s.name,s.campus,s.section||'All sections',s.session].join(' · '),String(s.id))));
  if(match.length===1)source.value=String(match[0].id);else if(match.some(s=>String(s.id)===prev))source.value=prev;
  status.textContent=!cls.value||!typ.value?'Choose a class and exam type to load papers.':!match.length?'No matching saved date sheet. Create one or use advanced manual creation.':'Select the correct campus, section and session if several sheets match.';
  show();
 }
 cls.addEventListener('change',filter);
 typ.addEventListener('change',()=>{cat.value=categories[typ.value.trim().toLowerCase()]||'';filter();});
 source.addEventListener('change',show);
 window.addEventListener('pageshow',filter);
 filter();
});