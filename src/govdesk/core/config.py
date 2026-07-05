# SPDX-FileCopyrightText: 2026 GovDesk-Mitwirkende
#
# SPDX-License-Identifier: EUPL-1.2

"""Zentrale Konfiguration über Umgebungsvariablen (Prefix GOVDESK_)."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="GOVDESK_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Sicherheit
    secret_key: str = "dev-unsicher-bitte-aendern"  # noqa: S105 — Dev-Fallback, Compose erzwingt eigenen Wert
    cookie_secure: bool = True
    session_idle_hours: int = 8
    session_max_days: int = 7

    # Dienste
    database_url: str = "postgresql+psycopg://govdesk:govdesk@localhost:5432/govdesk"
    qdrant_url: str = "http://localhost:6333"
    ollama_base_url: str = "http://localhost:11434"
    ollama_api_key: str | None = None
    reranker_url: str = "http://localhost:8081"

    # Modelle (Initialwerte — Laufzeitwerte stehen in app_settings)
    default_llm_model: str = "gemma3:4b"
    embedding_model: str = "bge-m3"
    embedding_dimensions: int = 1024

    # Ablage
    data_dir: Path = Path("./data")

    # OIDC / Keycloak
    oidc_enabled: bool = False
    oidc_issuer: str | None = None
    oidc_client_id: str | None = None
    oidc_client_secret: str | None = None
    local_login_enabled: bool = True

    # Features
    enable_doc_convert: bool = False

    @property
    def database_url_psycopg(self) -> str:
        """Reine psycopg-DSN (ohne SQLAlchemy-Dialekt-Prefix), z. B. für procrastinate."""
        return self.database_url.replace("postgresql+psycopg://", "postgresql://", 1)


@lru_cache
def get_settings() -> Settings:
    return Settings()
