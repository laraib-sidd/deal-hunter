from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Project root (where pyproject.toml and .env live)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


class TelegramConfig(BaseSettings):
    enabled: bool = False
    bot_token: str = ""
    chat_id: str = ""


class SearchFilter(BaseSettings):
    keywords: list[str] = Field(default_factory=lambda: ["gpu", "rtx", "gtx", "ryzen", "laptop"])
    min_price: float | None = None
    max_price: float | None = None
    categories: list[str] = Field(default_factory=lambda: ["gpu", "cpu", "laptop", "monitor", "ram", "ssd"])
    locations: list[str] = Field(default_factory=list)


class AppConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="DEAL_HUNTER_",
        env_nested_delimiter="__",
        env_file=str(_PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    db_path: Path = Path.home() / ".deal-hunter" / "deals.db"
    data_dir: Path = Path(__file__).parent / "data"
    sources: list[str] = Field(default_factory=lambda: ["techenclave", "reddit"])
    search: SearchFilter = Field(default_factory=SearchFilter)
    telegram: TelegramConfig = Field(default_factory=TelegramConfig)
    scrape_interval_seconds: int = 7200
    max_concurrent_requests: int = 5

    # AI config — Groq free tier (Llama 4 Scout, 500K tokens/day, no credit card)
    ai_provider: str = "groq"
    ai_model: str = "meta-llama/llama-4-scout-17b-16e-instruct"
    groq_api_key: str = ""

    # Reddit
    reddit_client_id: str = ""
    reddit_client_secret: str = ""
