import asyncio
import logging

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command
from aiogram.types import CallbackQuery, Message

from bot.config import settings
from bot.database import register_telegram_user
from bot.keyboards import main_menu


logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO))
logger = logging.getLogger("documento_pronto")
dp = Dispatcher()


@dp.message(CommandStart())
async def start(message: Message) -> None:
    if message.from_user:
        try:
            await asyncio.to_thread(register_telegram_user, message.from_user.id)
        except Exception:
            # Keep the basic menu available while deployment secrets are being configured.
            logger.exception("Could not register Telegram user in Supabase")

    await message.answer(
        "📄 <b>DOCUMENTO PRONTO</b>\n\n"
        "Seu espaço para converter, organizar e trabalhar com arquivos.\n\n"
        "Escolha uma opção no menu. As ferramentas serão ativadas por etapas; formatos incompatíveis serão informados com clareza.",
        reply_markup=main_menu(),
        parse_mode="HTML",
    )


@dp.message(Command("ajuda", "help"))
async def help_command(message: Message) -> None:
    await message.answer(
        "Envie /start para abrir o menu. Nunca envie senhas, documentos de terceiros sem autorização ou dados que não queira processar."
    )


@dp.callback_query(F.data.startswith("menu:"))
async def menu_action(callback: CallbackQuery) -> None:
    assert callback.data is not None
    action = callback.data.split(":", 1)[1]
    messages = {
        "convert": "🔄 <b>Converter arquivo</b>\n\nO fluxo de conversão está preparado para implementação. Primeiro serão habilitados formatos de documentos comuns.",
        "pdf": "📑 <b>Ferramentas de PDF</b>\n\nAs ferramentas de PDF serão liberadas por etapas, começando por extrair texto, juntar e dividir arquivos.",
        "edit": "📝 <b>Criar ou editar documento</b>\n\nEste módulo receberá modelos e ferramentas de edição na próxima etapa.",
        "usage": "📊 O painel de uso será exibido quando a integração de métricas estiver implementada.",
        "premium": "⭐ O plano Premium será definido depois de medir custos e uso real. Nenhuma cobrança está ativa.",
        "help": "Envie /start para abrir o menu. O bot ainda está em fase inicial de construção.",
    }
    await callback.answer()
    if callback.message:
        await callback.message.answer(
            messages.get(action, "Opção não reconhecida."),
            parse_mode="HTML",
            reply_markup=main_menu(),
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
