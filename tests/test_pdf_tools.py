from io import BytesIO
from zipfile import ZipFile

import pytest
from pypdf import PdfReader, PdfWriter

from bot.pdf_tools import compress_pdf, extract_pdf_text, merge_pdfs, organize_pdf, pdf_to_jpg, split_pdf_zip


def make_pdf(*pages: str) -> bytes:
    writer = PdfWriter()
    for _ in pages:
        writer.add_blank_page(width=300, height=300)
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


def test_compress_keeps_pages():
    assert len(PdfReader(BytesIO(compress_pdf(make_pdf("a", "b")))).pages) == 2


def test_reorder_requires_every_page_once():
    with pytest.raises(ValueError, match="todas as páginas"):
        organize_pdf(make_pdf("a", "b", "c"), "order", "3,1")


def test_reorder_preserves_page_count():
    result = organize_pdf(make_pdf("a", "b", "c"), "order", "3,1,2")
    assert len(PdfReader(BytesIO(result)).pages) == 3


def test_rotate_rejects_invalid_angle():
    with pytest.raises(ValueError, match="Formato"):
        organize_pdf(make_pdf("a"), "rotate", "1 45")


def test_remove_page_keeps_at_least_one():
    with pytest.raises(ValueError, match="não pode remover todas"):
        organize_pdf(make_pdf("a"), "remove", "1")


def test_pdf_to_jpg_zips_multiple_pages():
    result, name, mime = pdf_to_jpg(make_pdf("a", "b"), "original.pdf")
    assert name.endswith(".zip")
    assert mime == "application/zip"
    with ZipFile(BytesIO(result)) as archive:
        assert len(archive.namelist()) == 2
