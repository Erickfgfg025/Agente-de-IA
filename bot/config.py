from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    telegram_bot_token: str = ""
    supabase_url: str = ""
    supabase_service_role_key: str = ""
    max_upload_mb: int = 20
    free_daily_jobs: int = 5
    premium_daily_jobs: int = 50
    temp_file_ttl_minutes: int = 30
    log_level: str = "INFO"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)


settings = Settings()
