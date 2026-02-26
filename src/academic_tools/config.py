"""Unified configuration via Pydantic Settings (reads from .env)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # For installed tool usage, users can point to any external env file:
    #   ACADEMIC_TOOLS_ENV_FILE=/path/to/.env
    # Empty value disables env-file loading (env vars still work).
    _env_file = os.getenv("ACADEMIC_TOOLS_ENV_FILE", ".env").strip()
    model_config = SettingsConfigDict(
        env_file=_env_file or None,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── LLM (OpenAI-compatible) ───────────────────────────────
    LLM_API_KEY: str = ""
    LLM_BASE_URL: str = "https://api.deepseek.com"
    LLM_MODEL: str = "deepseek-chat"

    # ── Zotero ────────────────────────────────────────────────
    ZOTERO_LIBRARY_ID: Optional[str] = None
    ZOTERO_LIBRARY_TYPE: str = "user"
    ZOTERO_API_KEY: Optional[str] = None
    ZOTERO_LOCAL: bool = False

    # ── arXiv ─────────────────────────────────────────────────
    # Default to a workspace-local folder under current working directory.
    # If an absolute path is preferred, set ARXIV_STORAGE_PATH in .env.
    ARXIV_STORAGE_PATH: str = "papers"

    # ── OCR (MinerU) ──────────────────────────────────────────
    MINERU_API_BASE: str = "https://mineru.net/api/v4"
    MINERU_API_KEY_1: Optional[str] = None
    MINERU_API_KEY_2: Optional[str] = None
    MINERU_API_KEY_3: Optional[str] = None
    MINERU_API_KEY_4: Optional[str] = None
    MINERU_API_KEY_5: Optional[str] = None
    # Whether MinerU HTTP calls should inherit system proxy/env settings.
    # Keep False by default to avoid VPN/proxy interference on Windows.
    MINERU_TRUST_ENV: bool = False

    # ── Paper processing ──────────────────────────────────────
    # Max characters from full.md to send to LLM for metadata extraction
    METADATA_TEXT_LIMIT: int = 6000


# Singleton — import this everywhere
settings = Settings()
