from datetime import datetime
from functools import lru_cache
from zoneinfo import ZoneInfo

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
    client = get_supabase()
    response = (
        client.table("usage_daily")
        .select("jobs_count,bytes_processed")
        .eq("user_id", user_id)
        .eq("usage_date", datetime.now(ZoneInfo("America/Sao_Paulo")).date().isoformat())
        .execute()
    )
    rows = response.data or []
    return rows[0] if rows else {"jobs_count": 0, "bytes_processed": 0}


def consume_daily_usage(telegram_user_id: int) -> dict:
    """Atomically consume one free daily operation; the database resets by date."""
    client = get_supabase()
    response = client.rpc(
        "record_daily_usage",
        {
            "p_telegram_user_id": telegram_user_id,
            "p_daily_limit": settings.free_daily_jobs,
        },
    ).execute()
    if not response.data:
        raise RuntimeError("Supabase não retornou o resultado do limite diário.")
    result = response.data[0]
    return {
        "allowed": bool(result["allowed"]),
        "jobs_count": int(result["jobs_count"]),
        "daily_limit": int(result["daily_limit"]),
        "resets_on": result["resets_on"],
    }
