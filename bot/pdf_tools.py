from io import BytesIO
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile
from pypdf import PdfReader, PdfWriter

def extract_pdf_text(data: bytes) -> bytes:
    reader = PdfReader(BytesIO(data))
    if reader.is_encrypted:
        raise ValueError("Este PDF está protegido por senha.")
    text = "\n\n".join(page.extract_text() or "" for page in reader.pages).strip()
    if not text:
        raise ValueError("Não foi encontrado texto selecionável neste PDF.")
    return text.encode("utf-8")

def merge_pdfs(files: list[tuple[str, bytes]]) -> bytes:
    if len(files) < 2:
        raise ValueError("Envie pelo menos dois PDFs.")
    writer = PdfWriter()
    total = 0
    for name, data in files:
        reader = PdfReader(BytesIO(data))
        if reader.is_encrypted:
            raise ValueError(f"O arquivo {name} está protegido por senha.")
        total += len(reader.pages)
        if total > 500:
            raise ValueError("Limite de 500 páginas por arquivo combinado.")
        for page in reader.pages:
            writer.add_page(page)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()

def split_pdf_zip(data: bytes, filename: str) -> bytes:
    reader = PdfReader(BytesIO(data))
    if reader.is_encrypted:
        raise ValueError("Este PDF está protegido por senha.")
    if len(reader.pages) < 2:
        raise ValueError("Este PDF tem apenas uma página.")
    if len(reader.pages) > 100:
        raise ValueError("O limite desta ferramenta é de 100 páginas.")
    stem = Path(filename).stem or "documento"
    output = BytesIO()
    with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
        for index, page in enumerate(reader.pages, 1):
            writer = PdfWriter()
            writer.add_page(page)
            part = BytesIO()
            writer.write(part)
            archive.writestr(f"{stem}_pagina_{index:03d}.pdf", part.getvalue())
    return output.getvalue()
