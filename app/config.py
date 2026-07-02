from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', extra='ignore')

    rawg_api_key: str = ''
    rawg_base_url: str = 'https://api.rawg.io/api'
    database_url: str = f"sqlite:///{PROJECT_ROOT / 'gametracker.db'}"
    log_level: str = 'INFO'
    http_timeout_seconds: float = 10.0
    http_retries: int = 2

    # RAWG quota conservation: game facts rarely change, so cache aggressively.
    game_refresh_days: int = 30          # re-fetch stored game details at most this often
    cache_ttl_search: int = 86400        # search results (seconds)
    cache_ttl_list: int = 86400          # browse/top lists (seconds)
    cache_ttl_catalog: int = 604800      # genres/platforms catalogs (seconds)
    cache_ttl_game: int = 2592000        # individual game payloads (seconds)


settings = Settings()

# Backwards-compatible module-level constants (imported throughout the app).
RAWG_API_KEY = settings.rawg_api_key
RAWG_BASE_URL = settings.rawg_base_url
DB_URL = settings.database_url

STATUSES = ['PLAN', 'PLAYING', 'COMPLETED', 'DROPPED']
