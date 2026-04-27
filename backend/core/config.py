"""Application configuration using pydantic-settings.

Placeholder fields — will be expanded in S02 with AI provider config,
tool registry settings, and RAG/vector DB config.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional


class Settings(BaseSettings):
    """Application-level settings loaded from environment or .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # --- General ---
    app_name: str = "RE-AI"
    version: str = "0.1.0"
    debug: bool = True

    # --- Server ---
    host: str = "127.0.0.1"
    port: int = 8000

    # --- Database ---
    database_url: str = "sqlite+aiosqlite:///./re-ai.db"

    # --- AI Provider (placeholder — expanded in S02) ---
    ai_provider: str = "openai"
    ai_api_key: Optional[str] = None
    ai_model: str = "gpt-4o"

    # --- Vector DB (placeholder — expanded later) ---
    vector_db_type: str = "chroma"
    chroma_persist_dir: str = "./.chroma"


settings = Settings()
