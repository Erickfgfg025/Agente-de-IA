from io import BytesIO

import pytest
from pypdf import PdfWriter

from bot.conversions import convert_file


def blank_pdf() -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=300, height=300)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def test_rejects_fake_pdf_named_txt_conversion():
    with pytest.raises(ValueError, match="não parece ser um PDF válido"):
        convert_file(b"isto não é um PDF", "arquivo.pdf", "txt")


def test_converts_txt_to_docx():
    result, name, mime = convert_file("Olá, mundo!".encode(), "saudacao.txt", "docx")
    assert name == "saudacao.docx"
    assert mime.startswith("application/vnd.openxmlformats")
    assert result.startswith(b"PK")


def test_rejects_empty_file():
    with pytest.raises(ValueError, match="arquivo está vazio"):
        convert_file(b"", "vazio.txt", "docx")
