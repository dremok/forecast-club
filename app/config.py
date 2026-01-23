from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # Database
    database_url: str = "sqlite+aiosqlite:///./forecast_club.db"

    # Auth
    secret_key: str
    access_token_expire_minutes: int = 10080  # 7 days
    magic_link_expire_minutes: int = 15
    algorithm: str = "HS256"

    # App
    debug: bool = False
    base_url: str = "http://localhost:8000"


@lru_cache
def get_settings() -> Settings:
    return Settings()
