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
        print(fmt+': two salary slips / two pages; long register retained; voucher one page',flush=True)
    browser.close()
