from io import BytesIO
from pathlib import Path
import re
from zipfile import ZIP_DEFLATED, ZipFile

import fitz
from PIL import Image
import pytesseract
from pypdf import PdfReader, PdfWriter


MAX_GENERAL_PAGES = 500
MAX_OCR_PAGES = 30
MAX_JPG_PAGES = 100


def _reader(data: bytes) -> PdfReader:
    if not data:
        raise ValueError("O PDF está vazio.")
    if b"%PDF-" not in data[:1024]:
        raise ValueError("O conteúdo enviado não parece ser um PDF válido.")
    reader = PdfReader(BytesIO(data))
    if reader.is_encrypted:
        raise ValueError("Este PDF está protegido por senha. Remova a senha e tente novamente.")
    if not reader.pages:
        raise ValueError("O PDF não contém páginas.")
    return reader


def pdf_page_count(data: bytes) -> int:
    return len(_reader(data).pages)


def extract_pdf_text(data: bytes) -> bytes:
    reader = _reader(data)
    text = "\n\n".join(page.extract_text() or "" for page in reader.pages).strip()
    if not text:
        raise ValueError("Não foi encontrado texto selecionável neste PDF. Use a ferramenta OCR.")
    return text.encode("utf-8")


def merge_pdfs(files: list[tuple[str, bytes]]) -> bytes:
    if len(files) < 2:
        raise ValueError("Envie pelo menos dois PDFs.")
    writer = PdfWriter()
    total = 0
    for name, data in files:
        reader = _reader(data)
        total += len(reader.pages)
        if total > MAX_GENERAL_PAGES:
            raise ValueError("Limite de 500 páginas por arquivo combinado.")
        for page in reader.pages:
            writer.add_page(page)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def split_pdf_zip(data: bytes, filename: str) -> bytes:
    reader = _reader(data)
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


def compress_pdf(data: bytes) -> bytes:
    _reader(data)
    try:
        with fitz.open(stream=data, filetype="pdf") as document:
            output = BytesIO()
            document.save(
                output,
                garbage=4,
                deflate=True,
                deflate_images=True,
                deflate_fonts=True,
                clean=True,
            )
            result = output.getvalue()
    except Exception as exc:
        raise ValueError("Não consegui otimizar este PDF. Ele pode estar danificado ou protegido.") from exc
    if not result:
        raise ValueError("A otimização não gerou um PDF válido.")
    return result


def pdf_to_jpg(data: bytes, filename: str) -> tuple[bytes, str, str]:
    _reader(data)
    stem = Path(filename).stem or "documento"
    try:
        with fitz.open(stream=data, filetype="pdf") as document:
            if len(document) > MAX_JPG_PAGES:
                raise ValueError("O limite para exportar imagens é de 100 páginas.")
            images: list[tuple[str, bytes]] = []
            matrix = fitz.Matrix(150 / 72, 150 / 72)
            for index, page in enumerate(document, 1):
                pixmap = page.get_pixmap(matrix=matrix, alpha=False)
                if pixmap.width * pixmap.height > 40_000_000:
                    raise ValueError("Uma página tem resolução excessiva para exportar com segurança.")
                image = Image.frombytes("RGB", [pixmap.width, pixmap.height], pixmap.samples)
                output = BytesIO()
                image.save(output, format="JPEG", quality=88, optimize=True)
                images.append((f"{stem}_pagina_{index:03d}.jpg", output.getvalue()))
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError("Não consegui transformar este PDF em imagens JPG.") from exc

    if len(images) == 1:
        name, content = images[0]
        return content, name, "image/jpeg"

    archive_output = BytesIO()
    with ZipFile(archive_output, "w", compression=ZIP_DEFLATED) as archive:
        for name, content in images:
            archive.writestr(name, content)
    return archive_output.getvalue(), f"{stem}_imagens_jpg.zip", "application/zip"


def ocr_pdf(data: bytes, languages: str = "por+eng") -> bytes:
    reader = _reader(data)
    if len(reader.pages) > MAX_OCR_PAGES:
        raise ValueError("O OCR está limitado a 30 páginas por operação para manter o serviço estável.")
    searchable_writer = PdfWriter()
    try:
        with fitz.open(stream=data, filetype="pdf") as document:
            for page_index, page in enumerate(document):
                if (reader.pages[page_index].extract_text() or "").strip():
                    searchable_writer.add_page(reader.pages[page_index])
                    continue
                pixmap = page.get_pixmap(matrix=fitz.Matrix(180 / 72, 180 / 72), alpha=False)
                if pixmap.width * pixmap.height > 25_000_000:
                    raise ValueError("Uma página tem resolução excessiva para executar OCR com segurança.")
                image = Image.frombytes("RGB", [pixmap.width, pixmap.height], pixmap.samples)
                pdf_bytes = pytesseract.image_to_pdf_or_hocr(image, extension="pdf", lang=languages)
                ocr_reader = PdfReader(BytesIO(pdf_bytes))
                for ocr_page in ocr_reader.pages:
                    searchable_writer.add_page(ocr_page)
    except pytesseract.TesseractNotFoundError as exc:
        raise ValueError("O mecanismo OCR não está disponível no servidor. Verifique o deploy Docker.") from exc
    except pytesseract.TesseractError as exc:
        raise ValueError("O OCR falhou. Envie um PDF mais nítido ou com até 30 páginas.") from exc
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError("Não consegui executar OCR neste PDF. Verifique se o arquivo está íntegro.") from exc

    output = BytesIO()
    searchable_writer.write(output)
    return output.getvalue()


def organize_pdf(data: bytes, operation: str, instruction: str) -> bytes:
    reader = _reader(data)
    page_count = len(reader.pages)
    if page_count > MAX_GENERAL_PAGES:
        raise ValueError("Esta ferramenta aceita até 500 páginas por operação.")
    writer = PdfWriter()

    if operation == "order":
        try:
            order = [int(item.strip()) for item in instruction.split(",") if item.strip()]
        except ValueError as exc:
            raise ValueError("Use apenas números separados por vírgula, por exemplo: 3,1,2.") from exc
        expected = set(range(1, page_count + 1))
        if len(order) != page_count or set(order) != expected:
            raise ValueError(f"Informe todas as páginas, sem repetir, de 1 a {page_count}. Exemplo: 3,1,2.")
        for page_number in order:
            writer.add_page(reader.pages[page_number - 1])

    elif operation == "rotate":
        match = re.fullmatch(r"\s*(\d+(?:\s*,\s*\d+)*)\s+(90|180|270)\s*", instruction)
        if not match:
            raise ValueError("Formato: números das páginas, espaço e ângulo. Exemplo: 2,4 90.")
        pages = [int(item.strip()) for item in match.group(1).split(",")]
        angle = int(match.group(2))
        if any(number < 1 or number > page_count for number in pages):
            raise ValueError(f"As páginas devem estar entre 1 e {page_count}.")
        for index, page in enumerate(reader.pages, 1):
            if index in pages:
                page.rotate(angle)
            writer.add_page(page)

    elif operation == "remove":
        try:
            pages_to_remove = {int(item.strip()) for item in instruction.split(",") if item.strip()}
        except ValueError as exc:
            raise ValueError("Informe os números separados por vírgula, por exemplo: 2,4.") from exc
        if not pages_to_remove or any(number < 1 or number > page_count for number in pages_to_remove):
            raise ValueError(f"Informe páginas válidas entre 1 e {page_count}.")
        if len(pages_to_remove) >= page_count:
            raise ValueError("A operação não pode remover todas as páginas do PDF.")
        for index, page in enumerate(reader.pages, 1):
            if index not in pages_to_remove:
                writer.add_page(page)
    else:
        raise ValueError("Operação de organização não reconhecida.")

    output = BytesIO()
    writer.write(output)
    return output.getvalue()
