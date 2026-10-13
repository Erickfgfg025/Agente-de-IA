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
from bot.database import register_telegram_user
from bot.documents import make_docx, make_pdf, safe_filename
from bot.conversions import SUPPORTED_INPUTS, available_outputs, convert_file
from bot.pdf_tools import extract_pdf_text, merge_pdfs, split_pdf_zip
from bot.keyboards import main_menu


logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO))
logger = logging.getLogger("documento_pronto")
dp = Dispatcher()


class CreateDocument(StatesGroup):
    waiting_text = State()
    waiting_format = State()
    waiting_file = State()
    waiting_conversion = State()
    waiting_pdf_file = State()
    waiting_merge_files = State()


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
        "Seu espaço para criar, converter, organizar e trabalhar com arquivos.\n\n"
        "Escolha uma opção no menu abaixo.",
        reply_markup=main_menu(),
        parse_mode="HTML",
    )


@dp.message(Command("ajuda", "help"))
async def help_command(message: Message) -> None:
    await message.answer(
        "Use o menu para criar um documento. Para começar novamente, envie /start. "
        "Não envie senhas nem documentos de terceiros sem autorização."
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
        "Envie um arquivo PDF, Word (.docx), TXT ou uma imagem PNG/JPG/WEBP.\n"
        "Tamanho máximo: " + str(settings.max_upload_mb) + " MB.\n"
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
            "Envie um arquivo PDF, Word (.docx), TXT ou uma imagem PNG/JPG/WEBP.\n"
            f"Tamanho máximo: {settings.max_upload_mb} MB.\n"
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
        await message.answer("Formato não suportado. Envie PDF, DOCX, TXT, PNG, JPG, JPEG ou WEBP.")
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

    await callback.answer("Convertendo arquivo…")
    try:
        content, output_name, mime_type = await asyncio.to_thread(convert_file, file_data, filename, action)
        if callback.message:
            await callback.message.answer_document(
                BufferedInputFile(content, filename=output_name),
                caption=f"✅ Conversão concluída: {output_name}",
            )
            await callback.message.answer("Arquivo convertido. O que deseja fazer agora?", reply_markup=main_menu())
    except Exception as exc:
        logger.exception("File conversion failed for %s to %s", filename, action)
        detail = str(exc) if isinstance(exc, ValueError) else "O arquivo pode estar danificado ou usar recursos não compatíveis."
        if callback.message:
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
        if callback.message:
            await callback.message.answer_document(
                document,
                caption=f"✅ Documento criado em {'.docx' if action == 'docx' else '.pdf'}",
            )
            await callback.message.answer("Quer fazer outra coisa?", reply_markup=main_menu())
    except Exception:
        logger.exception("Document generation failed")
        if callback.message:
            await callback.message.answer("Não consegui gerar o arquivo desta vez. Tente novamente com um texto mais simples.")
    finally:
        await state.clear()



def pdf_tools_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📎 Juntar PDFs", callback_data="pdf:merge")],
        [InlineKeyboardButton(text="✂️ Dividir PDF por página", callback_data="pdf:split")],
        [InlineKeyboardButton(text="📝 Extrair texto do PDF", callback_data="pdf:extract")],
        [InlineKeyboardButton(text="⬅️ Menu principal", callback_data="pdf:back")],
    ])


def merge_control_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Juntar arquivos enviados", callback_data="pdf:merge_finish")],
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
    if action in {"split", "extract"}:
        await state.clear()
        await state.update_data(pdf_action=action)
        await state.set_state(CreateDocument.waiting_pdf_file)
        prompt = "✂️ Envie o PDF que deseja dividir em arquivos de uma página." if action == "split" else "📝 Envie o PDF do qual deseja extrair o texto selecionável."
        if callback.message:
            await callback.message.answer(prompt)
        return
    if action == "merge_finish":
        if await state.get_state() != CreateDocument.waiting_merge_files.state:
            if callback.message:
                await callback.message.answer("Inicie a operação pelo menu Ferramentas de PDF.")
            return
        data = await state.get_data()
        files = data.get("merge_files", [])
        if len(files) < 2:
            if callback.message:
                await callback.message.answer("Envie pelo menos 2 PDFs antes de juntar.", reply_markup=merge_control_menu())
            return
        try:
            result = await asyncio.to_thread(merge_pdfs, files)
            if callback.message:
                await callback.message.answer_document(BufferedInputFile(result, filename="pdfs_unidos.pdf"), caption="✅ PDFs unidos com sucesso.")
                await callback.message.answer("O que deseja fazer agora?", reply_markup=main_menu())
        except Exception as exc:
            logger.exception("Erro ao juntar PDFs")
            if callback.message:
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
    files = data.get("merge_files", [])
    if len(files) >= 10:
        await message.answer("Limite de 10 PDFs por operação atingido.", reply_markup=merge_control_menu())
        return
    buf = BytesIO()
    try:
        await message.bot.download(doc.file_id, destination=buf)
    except Exception:
        logger.exception("Falha ao baixar PDF para junção")
        await message.answer("Não consegui baixar esse PDF do Telegram. Tente enviá-lo novamente.")
        return
    files.append((doc.file_name or f"arquivo_{len(files)+1}.pdf", buf.getvalue()))
    await state.update_data(merge_files=files)
    await message.answer(f"PDF recebido ({len(files)}/10). " + ("Envie mais PDFs ou finalize." if len(files) >= 2 else "Envie pelo menos mais um PDF."), reply_markup=merge_control_menu())


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
    buf = BytesIO()
    try:
        await message.bot.download(doc.file_id, destination=buf)
        raw = buf.getvalue()
        if action == "extract":
            result = await asyncio.to_thread(extract_pdf_text, raw)
            filename = "texto_extraido.txt"
        elif action == "split":
            result = await asyncio.to_thread(split_pdf_zip, raw, doc.file_name or "documento.pdf")
            filename = "pdf_dividido.zip"
        else:
            await message.answer("Operação inválida. Abra novamente Ferramentas de PDF.")
            return
        await message.answer_document(BufferedInputFile(result, filename=filename), caption="✅ PDF processado com sucesso.")
        await message.answer("O que deseja fazer agora?", reply_markup=main_menu())
    except Exception as exc:
        logger.exception("Erro na ferramenta PDF")
        await message.answer(f"Não foi possível processar o PDF: {exc}")
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
    messages = {
        "convert": "🔄 <b>Converter arquivo</b>\n\nO próximo módulo será a conversão de arquivos enviados. Por enquanto, a criação de Word e PDF já está disponível.",
        "pdf": "📑 <b>Ferramentas de PDF</b>\n\nJunte vários PDFs, divida um PDF em páginas separadas ou extraia texto selecionável para TXT.",
        "usage": "📊 O painel de uso detalhado ainda será implementado.",
        "premium": "⭐ Nenhuma cobrança está ativa. Os planos serão definidos depois de medir custos e uso real.",
        "help": "Use Criar ou editar documento para gerar arquivos Word ou PDF a partir de texto. Envie /cancelar para interromper uma operação.",
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
