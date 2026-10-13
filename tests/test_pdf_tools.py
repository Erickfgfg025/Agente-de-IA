from io import BytesIO
from zipfile import ZipFile

import pytest
from pypdf import PdfReader, PdfWriter

from bot.pdf_tools import extract_pdf_text, merge_pdfs, split_pdf_zip


def make_pdf(*texts: str) -> bytes:
    writer = PdfWriter()
    for text in texts:
        page = writer.add_blank_page(width=300, height=300)
        # Blank pages are sufficient for merge/split; text extraction is tested
        # separately with a PDF containing a text content stream below.
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def test_merge_requires_at_least_two_pdfs():
    with pytest.raises(ValueError, match="pelo menos dois"):
        merge_pdfs([("um.pdf", make_pdf("pagina"))])


def test_merge_combines_pages():
    result = merge_pdfs([("a.pdf", make_pdf("a")), ("b.pdf", make_pdf("b", "c"))])
    assert len(PdfReader(BytesIO(result)).pages) == 3


def test_split_creates_one_pdf_per_page():
    result = split_pdf_zip(make_pdf("a", "b"), "relatorio.pdf")
    with ZipFile(BytesIO(result)) as archive:
        names = archive.namelist()
        assert names == ["relatorio_pagina_001.pdf", "relatorio_pagina_002.pdf"]
        assert all(len(PdfReader(BytesIO(archive.read(name))).pages) == 1 for name in names)


def test_split_rejects_single_page_pdf():
    with pytest.raises(ValueError, match="apenas uma página"):
        split_pdf_zip(make_pdf("a"), "unico.pdf")


def test_extract_rejects_pdf_without_selectable_text():
    with pytest.raises(ValueError, match="Não foi encontrado texto selecionável"):
        extract_pdf_text(make_pdf("pagina vazia"))
