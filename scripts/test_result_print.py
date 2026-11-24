"""Chromium pagination check using real Flask result cards and fictional pupils."""
import os, sys, io
from pathlib import Path
os.environ['DATABASE_URL']='sqlite:///:memory:'
os.environ['IDENTITY_DATABASE_URL']=''
root=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(root),str(root/'tests')]
from test_branding_values import BrandingValueTests, db, Student, app
from playwright.sync_api import sync_playwright
from pypdf import PdfReader

def main():
    case=BrandingValueTests()
    case.setUp()
    try:
        other=Student(admission_no='PRINT-2',name='Second Print Pupil',class_name='Class A',status='Active')
        db.session.add(other);db.session.flush()
        db.session.add(case.rm['student'](student_id=other.id,data={'campus':'Campus A','section':'A','academic_session':'2026-27','roll_no':'2'}))
        award=case.award()
        css=(root/'static/style.css').read_text()
        with sync_playwright() as p:
            browser=p.chromium.launch(args=['--no-sandbox'])
            page=browser.new_page()
            for count in (8,10,12):
                papers=[dict(subject='Subject '+str(i+1),type='Written',total=50) for i in range(count)]
                award.data={**award.data,'papers':papers}
                db.session.commit()
                scores=case.ops['score']
                scores.query.filter_by(award_id=award.id).delete()
                for sid in (case.student.id,other.id):
                    for i in range(count):db.session.add(scores(award_id=award.id,student_id=sid,paper=i,obtained=40,state=''))
                db.session.commit()
                path='/workspace/core/exam/results/'+str(award.id)
                response=case.c.get(path)
                assert response.status_code==200
                page.set_content(response.data.decode(),wait_until='domcontentloaded')
                page.add_style_tag(content=css)
                for fmt in ('A4','Letter'):
                    # Override the generic A4 page rule to emulate the user's paper choice.
                    size=page.add_style_tag(content='@page { size: '+fmt+'; margin:10mm 12mm; }')
                    pdf=PdfReader(io.BytesIO(page.pdf(format=fmt,prefer_css_page_size=True,print_background=True)))
                    assert len(pdf.pages)==2,(count,fmt,len(pdf.pages))
                    texts=[x.extract_text() for x in pdf.pages]
                    for name in ('Fictional Pupil','Second Print Pupil'):
                        matches=[t for t in texts if name in t]
                        assert len(matches)==1,(count,fmt,name)
                        assert 'Subject '+str(count) in matches[0] and 'Principal' in matches[0],(count,fmt,name)
                    print(f'{count} papers, {fmt}: 2 students / 2 pages, final subject and signature retained',flush=True)
                    size.evaluate('(el)=>el.remove()')
            browser.close()
    finally:case.tearDown()
if __name__=='__main__':main()
