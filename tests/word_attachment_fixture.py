"""Small ordinary OOXML document for attachment tests (no third-party dependency)."""
from io import BytesIO
from zipfile import ZipFile, ZIP_DEFLATED

def word_attachment(extra=None,main_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml'):
    body=BytesIO()
    with ZipFile(body,'w',ZIP_DEFLATED) as document:
        document.writestr('[Content_Types].xml',
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            f'<Override PartName="/word/document.xml" ContentType="{main_type}"/></Types>')
        document.writestr('_rels/.rels',
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
            '</Relationships>')
        document.writestr('word/document.xml',
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            '<w:body><w:p><w:r><w:t>Fictional worksheet</w:t></w:r></w:p></w:body></w:document>')
        for name,data in (extra or {}).items():
            document.writestr(name,data)
    return body.getvalue()
