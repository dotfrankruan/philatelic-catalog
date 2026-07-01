from pathlib import Path
import tempfile

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Philatelic Catalog"
    database_url: str = f"sqlite:///{Path('philatelic_catalog.sqlite3').resolve()}"
    managed_archive_root: Path = Path("managed_archive").resolve()
    preview_cache_root: Path = Path(tempfile.gettempdir(), "philatelic-catalog-previews").resolve()
    upload_staging_root: Path = Path(tempfile.gettempdir(), "philatelic-catalog-uploads").resolve()

    model_config = SettingsConfigDict(env_prefix="PHILATELIC_", env_file=".env")


settings = Settings()
