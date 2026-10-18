from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="NURSE_NG_",
        extra="ignore",
    )

    app_name: str = "Nurse.ng"
    debug: bool = False
    secret_key: str = "insecure-dev-key-change-me"
    database_url: str = "sqlite:///./nurse_ng.db"
    allowed_hosts: str = "localhost,127.0.0.1"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
