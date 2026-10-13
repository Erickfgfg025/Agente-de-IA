from io import BytesIO
from pathlib import Path

from PIL import Image
from docx import Document
from pypdf import PdfReader

from bot.documents import make_docx, make_pdf


SUPPORTED_INPUTS = {".pdf", ".docx", ".txt", ".png", ".jpg", ".jpeg", ".webp"}


def available_outputs(filename: str) -> list[str]:
    ext = Path(filename).suffix.lower()
    if ext == ".pdf":
        return ["txt", "docx"]
    if ext == ".docx":
        return ["txt"]
    if ext == ".txt":
        return ["pdf", "docx"]
    if ext in {".png", ".jpg", ".jpeg", ".webp"}:
        return ["pdf"]
    return []


def convert_file(data: bytes, filename: str, output_format: str) -> tuple[bytes, str, str]:
    ext = Path(filename).suffix.lower()
    stem = Path(filename).stem or "arquivo"

    if ext == ".pdf":
        reader = PdfReader(BytesIO(data))
        text = "\n\n".join(page.extract_text() or "" for page in reader.pages).strip()
        if not text:
            raise ValueError("Este PDF não contém texto extraível. Se for digitalizado, será necessário OCR.")
        if output_format == "txt":
            return text.encode("utf-8"), f"{stem}.txt", "text/plain"
        if output_format == "docx":
            return make_docx(text, stem), f"{stem}.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

    elif ext == ".docx" and output_format == "txt":
        doc = Document(BytesIO(data))
        text = "\n".join(p.text for p in doc.paragraphs).strip()
        for table in doc.tables:
            for row in table.rows:
                text += "\n" + "\t".join(cell.text for cell in row.cells)
        return text.encode("utf-8"), f"{stem}.txt", "text/plain"

    elif ext == ".txt":
        text = data.decode("utf-8-sig")
        if output_format == "pdf":
            return make_pdf(text, stem), f"{stem}.pdf", "application/pdf"
        if output_format == "docx":
            return make_docx(text, stem), f"{stem}.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

    elif ext in {".png", ".jpg", ".jpeg", ".webp"} and output_format == "pdf":
        with Image.open(BytesIO(data)) as image:
            if image.width * image.height > 40_000_000:
                raise ValueError("A imagem tem resolução muito alta para converter com segurança.")
            if image.mode not in ("RGB", "L"):
                image = image.convert("RGB")
            output = BytesIO()
            image.save(output, format="PDF", resolution=150.0)
            return output.getvalue(), f"{stem}.pdf", "application/pdf"

    raise ValueError("Esta combinação de formato não é compatível.")
