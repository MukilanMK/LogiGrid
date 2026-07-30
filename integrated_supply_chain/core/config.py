"""
core/config.py
Centralised Pydantic Settings — single source of truth for all env vars.
All modules import `settings` from here; no module reads os.getenv() directly.
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Loaded once at import time from the .env file in the project root.
    All fields have safe defaults so the app can start even without a .env
    (useful for CI / testing); production values must be set via .env.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── MongoDB ──────────────────────────────────────────────────────────────
    mongo_uri: str = "mongodb://localhost:27017"
    db_name: str = "supply_chain_ecosystem"

    # ── Groq LLM ─────────────────────────────────────────────────────────────
    groq_api_key: str = ""
    groq_model: str = "llama-3.3-70b-versatile"
    groq_model_fast: str = "llama-3.1-8b-instant"

    # ── Email ─────────────────────────────────────────────────────────────────
    email_address: str = ""
    email_password: str = ""
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    imap_host: str = "imap.gmail.com"
    imap_port: int = 993

    # ── FastAPI ───────────────────────────────────────────────────────────────
    api_host: str = "0.0.0.0"
    api_port: int = 8000

    # ── Supervisor ────────────────────────────────────────────────────────────
    agent_timeout_seconds: int = 120


# Singleton instance — import this everywhere
settings = Settings()
