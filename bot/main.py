import asyncio
import logging
from io import BytesIO
from pathlib import Path

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery, Message, InlineKeyboardButton, InlineKeyboardMarkup,
    BufferedInputFile,
)

from bot.config import settings
from bot.database import consume_daily_usage, get_daily_usage, register_telegram_user
from bot.documents import make_docx, make_pdf, safe_filename
from bot.conversions import SUPPORTED_INPUTS, available_outputs, convert_file
from bot.pdf_tools import (
    compress_pdf, extract_pdf_text, merge_pdfs, ocr_pdf, organize_pdf,
    pdf_page_count, split_pdf_zip,
)
from bot.keyboards import main_menu


logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO))
logger = logging.getLogger("documento_pronto")
dp = Dispatcher()


async def consume_quota(telegram_user_id: int, reply_target) -> bool:
    """Consume one operation or explain why processing cannot continue."""
    try:
        result = await asyncio.to_thread(consume_daily_usage, telegram_user_id)
    except Exception:
        logger.exception("Could not check daily quota in Supabase")
        await reply_target.answer("⚠️ Não consegui verificar seu limite agora. Tente novamente em instantes.")
        return False
    if not result["allowed"]:
        await reply_target.answer(
            "⏳ <b>Limite diário atingido</b>\n\n"
            f"Você usou {result['jobs_count']}/{result['daily_limit']} operações gratuitas hoje.\n"
            "O limite será renovado automaticamente amanhã.",
            parse_mode="HTML",
        )
        return False
    return True


async def send_usage(telegram_user_id: int, reply_target) -> None:
    try:
        user = await asyncio.to_thread(register_telegram_user, telegram_user_id)
        usage = await asyncio.to_thread(get_daily_usage, user["id"])
        count = int(usage.get("jobs_count", 0))
        limit = settings.free_daily_jobs
        remaining = max(0, limit - count)
        await reply_target.answer(
            "📊 <b>Seu uso diário</b>\n\n"
            "Plano: Gratuito 🆓\n"
            f"Operações usadas: {count}/{limit}\n"
            f"Restantes hoje: {remaining}\n\n"
            "🔄 O limite renova automaticamente à meia-noite.",
            parse_mode="HTML",
        )
    except Exception:
        logger.exception("Could not read daily usage from Supabase")
        await reply_target.answer("Não consegui consultar seu uso agora. Tente novamente em instantes.")


class CreateDocument(StatesGroup):
    waiting_text = State()
    waiting_format = State()
    waiting_file = State()
    waiting_conversion = State()
    waiting_pdf_file = State()
    waiting_merge_files = State()
    waiting_organize_command = State()


def format_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📄 Word (.docx)", callback_data="create:docx")],
        [InlineKeyboardButton(text="📕 PDF (.pdf)", callback_data="create:pdf")],
        [InlineKeyboardButton(text="❌ Cancelar", callback_data="create:cancel")],
    ])


@dp.message(CommandStart())
async def start(message: Message, state: FSMContext) -> None:
    await state.clear()
    if message.from_user:
        try:
            await asyncio.to_thread(register_telegram_user, message.from_user.id)
        except Exception:
            logger.exception("Could not register Telegram user in Supabase")

    await message.answer(
        "📄 <b>DOCUMENTO PRONTO</b>\n\n"
        "Seu espaço para criar, converter e organizar documentos.\n\n"
        "Converta PDF, Excel, PowerPoint e imagens, extraia texto com OCR "
        "e compacte, reordene, gire ou remova páginas de PDFs.\n\n"
        "Escolha uma opção no menu abaixo.",
        reply_markup=main_menu(),
        parse_mode="HTML",
    )


@dp.message(Command("uso"))
async def usage_command(message: Message) -> None:
    if message.from_user:
        await send_usage(message.from_user.id, message)


@dp.message(Command("ajuda", "help"))
async def help_command(message: Message) -> None:
    await message.answer(
        "Use o menu para criar ou converter documentos e abrir as ferramentas de PDF. "
        "Para cancelar uma operação, envie /cancelar. Conversões de PDF podem alterar tabelas "
        "ou formatação; PDF para PowerPoint cria slides como imagens."
    )


@dp.message(Command("cancelar"))
async def cancel_command(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Operação cancelada. Use o menu para escolher outra ferramenta.", reply_markup=main_menu())


def conversion_menu(outputs: list[str]) -> InlineKeyboardMarkup:
    labels = {
        "pdf": "📕 PDF",
        "docx": "📄 Word (.docx)",
        "txt": "📝 Texto (.txt)",
        "xlsx": "📊 Excel (.xlsx)",
        "pptx": "📽️ PowerPoint (.pptx)",
        "jpg": "🖼️ JPG (ZIP se houver várias páginas)",
    }
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=labels[item], callback_data=f"convert:{item}")]
        for item in outputs
    ] + [[InlineKeyboardButton(text="❌ Cancelar", callback_data="convert:cancel")]])


@dp.message(Command("converter"))
async def conversion_command(message: Message, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(CreateDocument.waiting_file)
    await message.answer(
        "🔄 <b>Conversor de arquivos</b>\n\n"
        "Envie um PDF, Word (.docx), Excel (.xlsx), PowerPoint (.pptx), TXT ou imagem PNG/JPG/WEBP.\n"
        f"Tamanho máximo: {settings.max_upload_mb} MB.\n"
        "Para cancelar, envie /cancelar.",
        parse_mode="HTML",
    )


async def begin_conversion(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(CreateDocument.waiting_file)
    await callback.answer()
    if callback.message:
        await callback.message.answer(
            "🔄 <b>Converter arquivo</b>\n\n"
            "Envie um PDF, Word (.docx), Excel (.xlsx), PowerPoint (.pptx), TXT ou imagem PNG/JPG/WEBP.\n"
            f"Tamanho máximo: {settings.max_upload_mb} MB.\n"
            "PDF para PowerPoint gera slides como imagens; a extração de tabelas depende da qualidade do PDF.\n"
            "Para cancelar, envie /cancelar.",
            parse_mode="HTML",
        )


@dp.message(CreateDocument.waiting_file)
async def receive_conversion_file(message: Message, state: FSMContext) -> None:
    uploaded = message.document
    filename = uploaded.file_name if uploaded else ""
    file_id = uploaded.file_id if uploaded else ""
    if message.photo:
        uploaded_photo = message.photo[-1]
        filename = "imagem.jpg"
        file_id = uploaded_photo.file_id
    if not file_id:
        await message.answer("Envie o arquivo como anexo, ou uma imagem. Para sair, use /cancelar.")
        return

    ext = Path(filename).suffix.lower()
    if ext not in SUPPORTED_INPUTS:
        await message.answer("Formato não suportado. Envie PDF, DOCX, XLSX, PPTX, TXT, PNG, JPG, JPEG ou WEBP.")
        return
    size = uploaded.file_size if uploaded else (message.photo[-1].file_size if message.photo else 0)
    if size and size > settings.max_upload_mb * 1024 * 1024:
        await message.answer(f"O arquivo excede o limite de {settings.max_upload_mb} MB.")
        return

    buffer = BytesIO()
    try:
        await message.bot.download(file_id, destination=buffer)
        data = buffer.getvalue()
    except Exception:
        logger.exception("Failed to download uploaded conversion file")
        await message.answer("Não consegui baixar esse arquivo do Telegram. Tente enviar novamente.")
        return

    outputs = available_outputs(filename)
    if not outputs:
        await message.answer("Ainda não existe conversão disponível para esse formato.")
        return
    await state.update_data(conversion_data=data, conversion_filename=filename)
    await state.set_state(CreateDocument.waiting_conversion)
    await message.answer(
        f"📎 Arquivo recebido: <b>{filename}</b>\nEscolha o formato de saída:",
        reply_markup=conversion_menu(outputs),
        parse_mode="HTML",
    )


@dp.callback_query(F.data.startswith("convert:"))
async def run_conversion(callback: CallbackQuery, state: FSMContext) -> None:
    action = (callback.data or "").split(":", 1)[1]
    if action == "cancel":
        await state.clear()
        await callback.answer("Conversão cancelada")
        if callback.message:
            await callback.message.answer("Operação cancelada.", reply_markup=main_menu())
        return
    if await state.get_state() != CreateDocument.waiting_conversion.state:
        await callback.answer("Envie um arquivo pelo menu Converter arquivo primeiro.", show_alert=True)
        return
    data = await state.get_data()
    file_data = data.get("conversion_data")
    filename = data.get("conversion_filename", "arquivo")
    if not isinstance(file_data, bytes):
        await state.clear()
        await callback.answer("O arquivo expirou. Envie-o novamente.", show_alert=True)
        return
    if not callback.message:
        await callback.answer("Não encontrei a mensagem da operação.")
        return
    if not await consume_quota(callback.from_user.id, callback.message):
        await state.clear()
        await callback.answer()
        return

    await callback.answer("Convertendo arquivo…")
    try:
        content, output_name, mime_type = await asyncio.to_thread(convert_file, file_data, filename, action)
        await callback.message.answer_document(
            BufferedInputFile(content, filename=output_name),
            caption=f"✅ Conversão concluída: {output_name}",
        )
        if action == "pptx" and Path(filename).suffix.lower() == ".pdf":
            await callback.message.answer("ℹ️ Cada página do PDF virou uma imagem em um slide. O texto e os elementos não ficam editáveis.")
        elif action == "xlsx" and Path(filename).suffix.lower() == ".pdf":
            await callback.message.answer("ℹ️ Tabelas são extraídas quando detectadas. PDF sem tabela pode virar linhas de texto no Excel.")
        elif action == "pdf" and Path(filename).suffix.lower() in {".xlsx", ".pptx"}:
            await callback.message.answer("ℹ️ A formatação depende do arquivo original e das fontes disponíveis no servidor.")
        await callback.message.answer("Arquivo convertido. O que deseja fazer agora?", reply_markup=main_menu())
    except Exception as exc:
        logger.exception("File conversion failed for %s to %s", filename, action)
        detail = str(exc) if isinstance(exc, ValueError) else "O arquivo pode estar danificado ou usar recursos não compatíveis."
        await callback.message.answer(f"Não consegui converter esse arquivo. {detail}")
    finally:
        await state.clear()


@dp.callback_query(F.data.in_({"menu:edit", "menu:create", "menu:document", "menu:write"}))
async def begin_document(callback: CallbackQuery, state: FSMContext) -> None:
    logger.info("Document creation menu clicked: data=%s user=%s", callback.data, callback.from_user.id)
    await state.clear()
    await state.set_state(CreateDocument.waiting_text)
    await callback.answer()
    if callback.message:
        await callback.message.answer(
            "📝 <b>Criar documento</b>\n\n"
            "Envie o texto que deseja colocar no arquivo. Pode enviar várias linhas.\n"
            "Depois você escolhe Word ou PDF.\n\n"
            "Para desistir, envie /cancelar.",
            parse_mode="HTML",
        )


@dp.message(CreateDocument.waiting_text)
async def receive_document_text(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if not text:
        await message.answer("Envie o conteúdo como texto, por favor.")
        return
    if len(text) > 30000:
        await message.answer("O texto é muito longo. Nesta versão, envie até 30.000 caracteres.")
        return
    await state.update_data(document_text=text)
    await state.set_state(CreateDocument.waiting_format)
    await message.answer("Escolha o formato do seu documento:", reply_markup=format_menu())


@dp.callback_query(F.data.startswith("create:"))
async def generate_document(callback: CallbackQuery, state: FSMContext) -> None:
    action = (callback.data or "").split(":", 1)[1]
    if action == "cancel":
        await state.clear()
        await callback.answer("Cancelado")
        if callback.message:
            await callback.message.answer("Operação cancelada.", reply_markup=main_menu())
        return
    if await state.get_state() != CreateDocument.waiting_format.state:
        await callback.answer("Comece em Criar ou editar documento.", show_alert=True)
        return
    data = await state.get_data()
    text = data.get("document_text", "")
    if not text:
        await state.clear()
        await callback.answer("O texto não foi encontrado. Comece novamente.", show_alert=True)
        return
    if not callback.message:
        await callback.answer("Não encontrei a mensagem da operação.")
        return
    if not await consume_quota(callback.from_user.id, callback.message):
        await state.clear()
        await callback.answer()
        return

    await callback.answer("Preparando arquivo…")
    title = next((line.strip().lstrip("#").strip() for line in text.splitlines() if line.strip()), "Documento")
    filename = safe_filename(title)
    try:
        if action == "docx":
            content = await asyncio.to_thread(make_docx, text, title)
            document = BufferedInputFile(content, filename=f"{filename}.docx")
        elif action == "pdf":
            content = await asyncio.to_thread(make_pdf, text, title)
            document = BufferedInputFile(content, filename=f"{filename}.pdf")
        else:
            return
        await callback.message.answer_document(
            document,
            caption=f"✅ Documento criado em {'.docx' if action == 'docx' else '.pdf'}",
        )
        await callback.message.answer("Quer fazer outra coisa?", reply_markup=main_menu())
    except Exception:
        logger.exception("Document generation failed")
        await callback.message.answer("Não consegui gerar o arquivo desta vez. Tente novamente com um texto mais simples.")
    finally:
        await state.clear()


def pdf_tools_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📎 Juntar PDFs", callback_data="pdf:merge")],
        [InlineKeyboardButton(text="✂️ Dividir PDF por página", callback_data="pdf:split")],
        [InlineKeyboardButton(text="📝 Extrair texto selecionável", callback_data="pdf:extract")],
        [InlineKeyboardButton(text="🔎 OCR: PDF digitalizado", callback_data="pdf:ocr")],
        [InlineKeyboardButton(text="🗜️ Comprimir PDF", callback_data="pdf:compress")],
        [InlineKeyboardButton(text="🗂️ Organizar páginas", callback_data="pdf:organize")],
        [InlineKeyboardButton(text="⬅️ Menu principal", callback_data="pdf:back")],
    ])


def merge_control_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Juntar arquivos enviados", callback_data="pdf:merge_finish")],
        [InlineKeyboardButton(text="❌ Cancelar", callback_data="pdf:cancel")],
    ])


def organize_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="↕️ Reordenar páginas", callback_data="org:order")],
        [InlineKeyboardButton(text="🔄 Girar páginas", callback_data="org:rotate")],
        [InlineKeyboardButton(text="🗑️ Remover páginas", callback_data="org:remove")],
        [InlineKeyboardButton(text="❌ Cancelar", callback_data="pdf:cancel")],
    ])


@dp.callback_query(F.data.startswith("pdf:"))
async def pdf_tools_action(callback: CallbackQuery, state: FSMContext) -> None:
    action = (callback.data or "").split(":", 1)[1]
    await callback.answer()
    if action in {"back", "cancel"}:
        await state.clear()
        if callback.message:
            await callback.message.answer("Menu principal:", reply_markup=main_menu())
        return
    if action == "merge":
        await state.clear()
        await state.update_data(merge_files=[])
        await state.set_state(CreateDocument.waiting_merge_files)
        if callback.message:
            await callback.message.answer(
                "📎 <b>Juntar PDFs</b>\nEnvie pelo menos 2 arquivos PDF, um por vez. Máximo: 10 arquivos. Quando terminar, toque em “Juntar arquivos enviados”.",
                parse_mode="HTML", reply_markup=merge_control_menu())
        return
    if action in {"split", "extract", "ocr", "compress", "organize"}:
        await state.clear()
        await state.update_data(pdf_action=action)
        await state.set_state(CreateDocument.waiting_pdf_file)
        prompts = {
            "split": "✂️ Envie o PDF que deseja dividir em arquivos de uma página.",
            "extract": "📝 Envie o PDF do qual deseja extrair texto selecionável.",
            "ocr": "🔎 Envie o PDF digitalizado. O OCR criará um PDF pesquisável em português e inglês. Limite: 30 páginas.",
            "compress": "🗜️ Envie o PDF que deseja otimizar. A economia de espaço depende do conteúdo.",
            "organize": "🗂️ Envie o PDF cujas páginas deseja reordenar, girar ou remover.",
        }
        if callback.message:
            await callback.message.answer(prompts[action])
        return
    if action == "merge_finish":
        if await state.get_state() != CreateDocument.waiting_merge_files.state:
            if callback.message:
                await callback.message.answer("Inicie a operação pelo menu Ferramentas de PDF.")
            return
        data = await state.get_data()
        files_to_merge = data.get("merge_files", [])
        if len(files_to_merge) < 2:
            if callback.message:
                await callback.message.answer("Envie pelo menos 2 PDFs antes de juntar.", reply_markup=merge_control_menu())
            return
        if not callback.message or not await consume_quota(callback.from_user.id, callback.message):
            await state.clear()
            return
        try:
            result = await asyncio.to_thread(merge_pdfs, files_to_merge)
            await callback.message.answer_document(BufferedInputFile(result, filename="pdfs_unidos.pdf"), caption="✅ PDFs unidos com sucesso.")
            await callback.message.answer("O que deseja fazer agora?", reply_markup=main_menu())
        except Exception as exc:
            logger.exception("Erro ao juntar PDFs")
            await callback.message.answer(f"Não foi possível juntar os PDFs: {exc}")
        finally:
            await state.clear()


@dp.message(CreateDocument.waiting_merge_files)
async def receive_merge_pdf(message: Message, state: FSMContext) -> None:
    doc = message.document
    if not doc or not (doc.file_name or "").lower().endswith(".pdf"):
        await message.answer("Envie um arquivo PDF como documento.", reply_markup=merge_control_menu())
        return
    if doc.file_size and doc.file_size > settings.max_upload_mb * 1024 * 1024:
        await message.answer(f"Arquivo acima do limite de {settings.max_upload_mb} MB.")
        return
    data = await state.get_data()
    files_to_merge = data.get("merge_files", [])
    if len(files_to_merge) >= 10:
        await message.answer("Limite de 10 PDFs por operação atingido.", reply_markup=merge_control_menu())
        return
    buf = BytesIO()
    try:
        await message.bot.download(doc.file_id, destination=buf)
    except Exception:
        logger.exception("Falha ao baixar PDF para junção")
        await message.answer("Não consegui baixar esse PDF do Telegram. Tente enviá-lo novamente.")
        return
    files_to_merge.append((doc.file_name or f"arquivo_{len(files_to_merge)+1}.pdf", buf.getvalue()))
    await state.update_data(merge_files=files_to_merge)
    await message.answer(
        f"PDF recebido ({len(files_to_merge)}/10). " +
        ("Envie mais PDFs ou finalize." if len(files_to_merge) >= 2 else "Envie pelo menos mais um PDF."),
        reply_markup=merge_control_menu(),
    )


@dp.message(CreateDocument.waiting_pdf_file)
async def receive_single_pdf_tool(message: Message, state: FSMContext) -> None:
    doc = message.document
    if not doc or not (doc.file_name or "").lower().endswith(".pdf"):
        await message.answer("Envie um arquivo PDF como documento.")
        return
    if doc.file_size and doc.file_size > settings.max_upload_mb * 1024 * 1024:
        await message.answer(f"Arquivo acima do limite de {settings.max_upload_mb} MB.")
        return
    data = await state.get_data()
    action = data.get("pdf_action")
    if action not in {"extract", "split", "ocr", "compress", "organize"}:
        await state.clear()
        await message.answer("Operação inválida. Abra novamente Ferramentas de PDF.")
        return
    if not message.from_user:
        await message.answer("Não consegui identificar o usuário desta operação.")
        return

    buf = BytesIO()
    try:
        await message.bot.download(doc.file_id, destination=buf)
        raw = buf.getvalue()
        pages = await asyncio.to_thread(pdf_page_count, raw)
        if action == "organize":
            await state.update_data(organization_data=raw, organization_filename=doc.file_name or "documento.pdf")
            await state.set_state(CreateDocument.waiting_organize_command)
            await message.answer(f"🗂️ O PDF tem {pages} página(s). O que deseja fazer?", reply_markup=organize_menu())
            return
        if not await consume_quota(message.from_user.id, message):
            await state.clear()
            return

        if action == "extract":
            result = await asyncio.to_thread(extract_pdf_text, raw)
            filename = "texto_extraido.txt"
            caption = "✅ Texto extraído."
        elif action == "split":
            result = await asyncio.to_thread(split_pdf_zip, raw, doc.file_name or "documento.pdf")
            filename = "pdf_dividido.zip"
            caption = "✅ PDF dividido por página."
        elif action == "ocr":
            result = await asyncio.to_thread(ocr_pdf, raw)
            filename = "documento_com_ocr.pdf"
            caption = "✅ PDF pesquisável criado com OCR."
        elif action == "compress":
            result = await asyncio.to_thread(compress_pdf, raw)
            filename = "pdf_comprimido.pdf"
            reduction = (1 - len(result) / max(1, len(raw))) * 100
            caption = f"✅ PDF otimizado. Redução aproximada: {reduction:.1f}%." if reduction > 0 else "✅ PDF otimizado. O tamanho não diminuiu neste arquivo."
        else:
            raise ValueError("Operação PDF inválida.")
        await message.answer_document(BufferedInputFile(result, filename=filename), caption=caption)
        await message.answer("O que deseja fazer agora?", reply_markup=main_menu())
    except Exception as exc:
        logger.exception("Erro na ferramenta PDF")
        detail = str(exc) if isinstance(exc, ValueError) else "Verifique se o PDF está íntegro e tente novamente."
        await message.answer(f"Não foi possível processar o PDF: {detail}")
    finally:
        if action != "organize":
            await state.clear()


@dp.callback_query(F.data.startswith("org:"))
async def choose_organization_action(callback: CallbackQuery, state: FSMContext) -> None:
    if await state.get_state() != CreateDocument.waiting_organize_command.state:
        await callback.answer("Envie um PDF pelo menu Organizar páginas primeiro.", show_alert=True)
        return
    action = (callback.data or "").split(":", 1)[1]
    prompts = {
        "order": "Envie a nova ordem de TODAS as páginas separadas por vírgula. Exemplo para 3 páginas: 3,1,2.",
        "rotate": "Envie as páginas e o ângulo de giro (90, 180 ou 270, sentido horário). Exemplo: 2,4 90.",
        "remove": "Envie os números das páginas que deseja remover, separados por vírgula. Exemplo: 2,4.",
    }
    if action not in prompts:
        await callback.answer("Ação não reconhecida.", show_alert=True)
        return
    await state.update_data(organize_operation=action)
    await callback.answer()
    if callback.message:
        await callback.message.answer(prompts[action] + "\nPara cancelar, envie /cancelar.")


@dp.message(CreateDocument.waiting_organize_command)
async def apply_organization(message: Message, state: FSMContext) -> None:
    instruction = (message.text or "").strip()
    data = await state.get_data()
    raw = data.get("organization_data")
    operation = data.get("organize_operation")
    if not isinstance(raw, bytes):
        await state.clear()
        await message.answer("O PDF expirou. Abra Organizar páginas e envie o arquivo novamente.")
        return
    if operation not in {"order", "rotate", "remove"}:
        await message.answer("Escolha primeiro reordenar, girar ou remover páginas.", reply_markup=organize_menu())
        return
    if not instruction:
        await message.answer("Envie os números das páginas conforme o exemplo.")
        return
    if not message.from_user:
        await state.clear()
        await message.answer("Não consegui identificar o usuário desta operação.")
        return
    try:
        result = await asyncio.to_thread(organize_pdf, raw, operation, instruction)
        if not await consume_quota(message.from_user.id, message):
            await state.clear()
            return
        filename = {
            "order": "pdf_reordenado.pdf",
            "rotate": "pdf_girado.pdf",
            "remove": "pdf_sem_paginas_selecionadas.pdf",
        }[operation]
        labels = {"order": "Páginas reordenadas", "rotate": "Páginas giradas", "remove": "Páginas removidas"}
        await message.answer_document(BufferedInputFile(result, filename=filename), caption=f"✅ {labels[operation]} com sucesso.")
        await message.answer("O que deseja fazer agora?", reply_markup=main_menu())
    except Exception as exc:
        logger.exception("Falha ao organizar PDF")
        detail = str(exc) if isinstance(exc, ValueError) else "Não consegui modificar este PDF."
        await message.answer(f"Não foi possível organizar o PDF: {detail}")
    finally:
        await state.clear()


@dp.callback_query(F.data.startswith("menu:"))
async def menu_action(callback: CallbackQuery, state: FSMContext) -> None:
    assert callback.data is not None
    logger.info("Menu callback received: data=%s user=%s", callback.data, callback.from_user.id)
    action = callback.data.split(":", 1)[1]
    if action == "convert":
        await begin_conversion(callback, state)
        return
    if action in {"create", "document", "write"}:
        await state.clear()
        await state.set_state(CreateDocument.waiting_text)
        await callback.answer()
        if callback.message:
            await callback.message.answer(
                "📝 <b>Criar documento</b>\n\nEnvie o texto que deseja colocar no arquivo.\n"
                "Depois você escolhe Word ou PDF. Para cancelar, envie /cancelar.",
                parse_mode="HTML",
            )
        return
    if action == "usage":
        if callback.message:
            await send_usage(callback.from_user.id, callback.message)
        await callback.answer()
        return
    messages = {
        "convert": "🔄 <b>Converter arquivo</b>\n\nEnvie um PDF, DOCX, XLSX, PPTX, TXT ou uma imagem.",
        "pdf": "📑 <b>Ferramentas de PDF</b>\n\nJunte, divida, extraia texto, aplique OCR, comprima ou organize páginas de PDFs.",
        "usage": "📊 Consulte seu uso diário.",
        "premium": "⭐ Nenhuma cobrança está ativa. Os planos serão definidos depois de medir custos e uso real.",
        "help": "Use Converter arquivo ou Ferramentas de PDF para começar. Envie /cancelar para interromper uma operação.",
    }
    await callback.answer()
    if callback.message:
        await callback.message.answer(
            messages.get(action, "Opção não reconhecida."),
            parse_mode="HTML",
            reply_markup=pdf_tools_menu() if action == "pdf" else main_menu(),
        )


async def main() -> None:
    if not settings.telegram_bot_token:
        raise RuntimeError("Configure TELEGRAM_BOT_TOKEN no arquivo .env antes de iniciar o bot.")
    bot = Bot(token=settings.telegram_bot_token)
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())


@dp.callback_query()
async def unknown_callback(callback: CallbackQuery) -> None:
    logger.warning("Unhandled callback query: data=%r user=%s", callback.data, callback.from_user.id)
    await callback.answer("Atualizei o menu. Envie /start e tente novamente.", show_alert=True)
