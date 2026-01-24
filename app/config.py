from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Database
    database_url: str = "sqlite+aiosqlite:///./forecast_club.db"

    # Auth
    secret_key: str
    access_token_expire_minutes: int = 10080  # 7 days
    magic_link_expire_minutes: int = 15
    algorithm: str = "HS256"

    # Email (Resend)
    resend_api_key: str = ""
    email_from_address: str = ""
    email_from_name: str = "Forecast Club"

    # App
    debug: bool = False
    base_url: str = "http://localhost:8000"

    @property
    def email_enabled(self) -> bool:
        return bool(self.resend_api_key and self.email_from_address)


@lru_cache
def get_settings() -> Settings:
    return Settings()
