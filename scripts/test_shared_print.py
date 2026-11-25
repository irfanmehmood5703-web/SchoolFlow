"""Shared print policy smoke test on synthetic documents, no production records."""
import io
from pathlib import Path
from playwright.sync_api import sync_playwright
from pypdf import PdfReader
root=Path(__file__).resolve().parents[1]
css=(root/'static/style.css').read_text()
shared=(root/'static/compact_print.css').read_text()
def rows(n):
    return ''.join(f'<tr><td>Entry {i}</td><td>Sample description</td><td>50</td></tr>' for i in range(1,n+1))
def table(n):
    return '<table><thead><tr><th>Reference</th><th>Description</th><th>Total</th></tr></thead><tbody>'+rows(n)+'</tbody></table>'
def pdf(page,fmt):
    return PdfReader(io.BytesIO(page.pdf(format=fmt,prefer_css_page_size=True,print_background=True)))
with sync_playwright() as p:
    browser=p.chromium.launch(args=['--no-sandbox'])
    page=browser.new_page()
    for fmt in ('A4','Letter'):
        def setup(body):
            page.set_content('<html><head><style>'+css+'</style><style>'+shared+'</style><style>@page{size:'+fmt+';margin:10mm 12mm}</style></head><body><main><div class="page-content">'+body+'</div></main></body></html>')
        setup(''.join('<section class="challan sf-print-unit sf-salary-slip"><h2>Salary Slip '+str(i)+'</h2>'+table(12)+'<p>Authorized signature '+str(i)+'</p></section>' for i in (1,2)))
        result=pdf(page,fmt)
        assert len(result.pages)==2,(fmt,len(result.pages))
        for i,pg in enumerate(result.pages,1):
            t=pg.extract_text();assert 'Salary Slip '+str(i) in t and 'Entry 12' in t and 'Authorized signature '+str(i) in t
        setup('<section class="form-card table"><h2>Long Register</h2>'+table(110)+'</section>')
        result=pdf(page,fmt)
        assert len(result.pages)>1
        joined=' '.join(pg.extract_text() for pg in result.pages)
        assert 'Entry 1' in joined and 'Entry 110' in joined
        assert all('Reference' in pg.extract_text() for pg in result.pages)
        setup('<section class="form-card sf-print-unit sf-journal-voucher"><h2>Journal</h2>'+table(12)+'<p>Balanced total</p></section>')
        result=pdf(page,fmt)
        assert len(result.pages)==1 and 'Balanced total' in result.pages[0].extract_text()
        report=(root/'static/report_print.css').read_text()
        dates=''.join('<th><span class="attendance-day-full">%02d-Nov</span><span class="attendance-day-print">%02d<small>Nov</small></span></th>'%(i,i) for i in range(1,31))
        attendance_rows=''.join('<tr><td>%d</td><td>%d</td><td>Student %d Example</td>'%(i,i,i)+'<td>P</td>'*30+'</tr>' for i in range(1,5))
        page.set_content('<html><head><style>'+css+'</style><style>'+shared+'</style><style>'+report+'</style><style>@page sf-report-table{size:'+fmt+' landscape;margin:10mm}</style></head><body><main><div class="page-content"><div class="school-print-header">Duplicate school heading</div><div class="report-print-document attendance-sheet-print"><div class="page-heading">Screen heading</div><p>November 2026</p><div class="report-branding-header has-branding"><div><h2>Example School</h2><h3>Student Attendance Sheet</h3></div></div><section class="form-card report-table-output" data-day-count="30"><h2>4 matching rows</h2><div class="table"><table><thead><tr><th>ID</th><th>Roll No</th><th>Name</th>'+dates+'</tr></thead><tbody>'+attendance_rows+'</tbody></table></div></section><div class="report-branding-footer"><p>Date: 2026-11-25</p><p>Class Teacher: ______ Principal: ______</p></div></div></div></main></body></html>')
        result=pdf(page,fmt)
        assert len(result.pages)==1,(fmt,'attendance page count',len(result.pages))
        text=result.pages[0].extract_text()
        assert 'Student 4 Example' in text and 'Principal' in text and '30' in text and 'Duplicate school heading' not in text
        for n in (10,110):
            page.set_content('<html><head><style>'+css+'</style><style>'+shared+'</style><style>'+report+'</style><style>@page sf-report-table{size:'+fmt+';margin:10mm}</style></head><body><main><div class="page-content"><div class="school-print-header">Duplicate school heading</div><div class="report-print-document student-attendance-report-print"><div class="page-heading">Screen heading</div><p>November 2026</p><div class="report-branding-header has-branding"><div><h2>Example School</h2><h3>Individual Attendance Report</h3></div></div><div class="report-branding-body"><p>Saved attendance records</p></div><section class="form-card report-table-output"><h2>'+str(n)+' matching rows</h2><div class="table">'+table(n)+'</div></section><div class="report-branding-footer"><p>Date: 2026-11-25</p><p>Class Teacher: ______ Principal: ______</p></div></div></div></main></body></html>')
            result=pdf(page,fmt)
            assert (len(result.pages)==1 if n==10 else len(result.pages)>1),(fmt,n,len(result.pages))
            pages=[pg.extract_text() for pg in result.pages]
            assert 'Entry '+str(n) in pages[-1] and 'Principal' in pages[-1]
            assert 'Duplicate school heading' not in ' '.join(pages)
            assert all('Reference' in t for t in pages)
        print(fmt+': salary slips, long register, voucher and attendance reports print passed',flush=True)
    browser.close()
