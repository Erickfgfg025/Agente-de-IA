from functools import lru_cache

from supabase import Client, create_client

from bot.config import settings


@lru_cache(maxsize=1)
def get_supabase() -> Client:
    if not settings.supabase_url or not settings.supabase_service_role_key:
        raise RuntimeError(
            "Configure SUPABASE_URL e SUPABASE_SERVICE_ROLE_KEY no ambiente do servidor."
        )
    return create_client(settings.supabase_url, settings.supabase_service_role_key)


def register_telegram_user(telegram_user_id: int) -> dict:
    """Register a Telegram user without changing an existing plan or block status."""
    client = get_supabase()
    response = (
        client.table("bot_users")
        .upsert({"telegram_user_id": telegram_user_id}, on_conflict="telegram_user_id")
        .execute()
    )
    if not response.data:
        raise RuntimeError("Supabase não retornou o usuário registrado.")
    return response.data[0]


def get_daily_usage(user_id: str) -> dict:
    from datetime import date

    client = get_supabase()
    response = (
        client.table("usage_daily")
        .select("jobs_count,bytes_processed")
        .eq("user_id", user_id)
        .eq("usage_date", date.today().isoformat())
        .maybe_single()
        .execute()
    )
    return response.data or {"jobs_count": 0, "bytes_processed": 0}
