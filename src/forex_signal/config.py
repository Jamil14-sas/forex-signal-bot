"""Pydantic v2 settings for Forex Signal Bot."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Tuple

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def _resolve_env_file() -> str:
    return str(Path(__file__).resolve().parent.parent.parent / ".env")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_resolve_env_file(),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ---- Runtime ----
    environment: str = Field(default="production")
    log_level: str = Field(default="INFO")

    # ---- Telegram ----
    telegram_bot_token: str = Field(default="", description="Telegram bot token from @BotFather")

    # ---- OANDA ----
    oanda_api_key: str = Field(default="", description="OANDA API key (practice or live)")
    oanda_api_url: str = Field(
        default="https://api-fxpractice.oanda.com/v3",
        description="OANDA API base URL",
    )

    # ---- News API ----
    news_api_key: str = Field(default="", description="NewsAPI.org key for sentiment")
    news_enabled: bool = Field(default=True)

    # ---- Defaults ----
    default_timeframe: str = Field(default="1h", description="Default analysis timeframe")
    default_period_days: int = Field(default=90, description="Default data lookback in days")
    cache_ttl_seconds: int = Field(default=300, description="Data cache TTL in seconds")

    # ---- Rate limiting ----
    user_daily_limit: int = Field(default=100, description="Max analyses per user per day")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
