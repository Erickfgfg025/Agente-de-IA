import logging
import os

from aiohttp import web
from aiogram import Bot
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application

from bot.config import settings
from bot.main import dp

logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO))
logger = logging.getLogger("documento_pronto.web")


async def healthcheck(request: web.Request) -> web.Response:
    return web.json_response({"status": "ok", "service": "documento-pronto"})


async def configure_webhook(bot: Bot) -> None:
    external_url = os.getenv("RENDER_EXTERNAL_URL", "").rstrip("/")
    secret = os.getenv("WEBHOOK_SECRET_TOKEN", "")
    if not external_url:
        raise RuntimeError("RENDER_EXTERNAL_URL não foi definido pelo Render.")
    if not secret:
        raise RuntimeError("Configure WEBHOOK_SECRET_TOKEN nas variáveis do serviço.")
    await bot.set_webhook(
        url=f"{external_url}/telegram/webhook",
        secret_token=secret,
        allowed_updates=dp.resolve_used_update_types(),
        drop_pending_updates=False,
    )
    logger.info("Webhook do Telegram configurado.")


def main() -> None:
    if not settings.telegram_bot_token:
        raise RuntimeError("Configure TELEGRAM_BOT_TOKEN nas variáveis do serviço.")
    secret = os.getenv("WEBHOOK_SECRET_TOKEN", "")
    if not secret:
        raise RuntimeError("Configure WEBHOOK_SECRET_TOKEN nas variáveis do serviço.")

    bot = Bot(token=settings.telegram_bot_token)
    dp.startup.register(configure_webhook)

    app = web.Application()
    app.router.add_get("/", healthcheck)
    app.router.add_get("/healthz", healthcheck)

    webhook_handler = SimpleRequestHandler(
        dispatcher=dp,
        bot=bot,
        secret_token=secret,
    )
    webhook_handler.register(app, path="/telegram/webhook")
    setup_application(app, dp, bot=bot)

    port = int(os.getenv("PORT", "10000"))
    web.run_app(app, host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
