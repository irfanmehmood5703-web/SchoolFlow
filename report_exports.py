"""Spreadsheet exports for the same filtered, saved report rows shown on screen."""
import io,re
from decimal import Decimal
from flask import Response,request
from openpyxl import Workbook
from openpyxl.cell import WriteOnlyCell
from openpyxl.styles import Font,PatternFill,Alignment
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

CURRENCY={'Payable','Discount','Paid','Remaining','Collected','Amount','Deducted','Earnings','Deductions','Net','Lecture amount'}


def report_xlsx(headers,rows,name):
    if len(rows)>50000:raise ValueError('Narrow this export to at most 50,000 report rows.')
    book=Workbook(write_only=True);sheet=book.create_sheet('Report');sheet.freeze_panes='A2';sheet.sheet_properties.pageSetUpPr.fitToPage=True
    sheet.page_setup.orientation='landscape';sheet.page_setup.paperSize=Worksheet.PAPERSIZE_A4;sheet.page_setup.fitToWidth=1;sheet.page_setup.fitToHeight=0
    for i,heading in enumerate(headers,1):sheet.column_dimensions[get_column_letter(i)].width=30 if any(x in heading.lower() for x in ('name','student','father','date','class','account')) else 18
    def cell(ws,value,header=False):
        c=WriteOnlyCell(ws,value=value)
        if isinstance(value,str):c.data_type='s'
        if header:c.font=Font(bold=True,color='FFFFFF');c.fill=PatternFill('solid',fgColor='176B4A')
        c.alignment=Alignment(vertical='top',wrap_text=True);return c
    sheet.append([cell(sheet,h,True) for h in headers])
    for row in rows:
        values=[]
        for i,value in enumerate(row):
            if headers[i] in CURRENCY and isinstance(value,str) and re.fullmatch(r'-?\d[\d,]*\.\d{2}',value):value=float(Decimal(value.replace(',','')))
            c=cell(sheet,value)
            if headers[i] in CURRENCY and isinstance(value,(int,float)):c.number_format='#,##0.00'
            values.append(c)
        sheet.append(values)
    sheet.auto_filter.ref=f'A1:{get_column_letter(len(headers))}{len(rows)+1}'
    filters=book.create_sheet('Filters');filters.append([cell(filters,'Filter',True),cell(filters,'Value',True)]);filters.column_dimensions['A'].width=24;filters.column_dimensions['B'].width=60
    filters.append([cell(filters,'Report'),cell(filters,name)])
    for key in sorted(request.args):filters.append([cell(filters,key),cell(filters,', '.join(request.args.getlist(key)))])
    stream=io.BytesIO();book.save(stream)
    return Response(stream.getvalue(),mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',headers={'Content-Disposition':f'attachment; filename="schoolflow-{name}.xlsx"','Cache-Control':'no-store'})
