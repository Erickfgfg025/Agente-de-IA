from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Converter arquivo", callback_data="menu:convert")],
        [InlineKeyboardButton(text="📑 Ferramentas de PDF", callback_data="menu:pdf")],
        [InlineKeyboardButton(text="📝 Criar ou editar documento", callback_data="menu:edit")],
        [InlineKeyboardButton(text="📊 Meu uso", callback_data="menu:usage"), InlineKeyboardButton(text="⭐ Premium", callback_data="menu:premium")],
        [InlineKeyboardButton(text="ℹ️ Ajuda", callback_data="menu:help")],
    ])
