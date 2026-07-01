from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Philatelic Catalog"
    database_url: str = f"sqlite:///{Path('philatelic_catalog.sqlite3').resolve()}"

    model_config = SettingsConfigDict(env_prefix="PHILATELIC_", env_file=".env")


settings = Settings()
