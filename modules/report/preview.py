"""Content preview from the exact Word bytes offered for download."""
from html import escape
from io import BytesIO


def document_blocks(data):
    from docx import Document
    from docx.table import Table
    from docx.text.paragraph import Paragraph
    from docx.oxml.ns import qn
    doc = Document(BytesIO(data))
    blocks = []
    for element in doc.element.body.iterchildren():
        if element.tag == qn("w:p"):
            paragraph = Paragraph(element, doc)
            if paragraph.text.strip():
                blocks.append({"type": "paragraph", "style": paragraph.style.name, "text": paragraph.text})
        elif element.tag == qn("w:tbl"):
            table = Table(element, doc)
            blocks.append({"type": "table", "rows": [[cell.text for cell in row.cells] for row in table.rows]})
    return blocks


def preview_html(data):
    content = []
    for block in document_blocks(data):
        if block["type"] == "table":
            content.append("<table>" + "".join("<tr>" + "".join(f"<td>{escape(cell).replace(chr(10), '<br>')}</td>" for cell in row) + "</tr>" for row in block["rows"]) + "</table>")
        else:
            style = block["style"].lower()
            tag = "h1" if style == "title" else "h2" if "heading 1" in style else "h3" if "heading" in style else "p"
            content.append(f"<{tag}>{escape(block['text']).replace(chr(10), '<br>')}</{tag}>")
    return '<article class="wb-document">' + "".join(content) + "</article>"
