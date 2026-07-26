# SPDX-FileCopyrightText: 2026 GovDesk-Mitwirkende
#
# SPDX-License-Identifier: EUPL-1.2

"""Laufzeit-Konfiguration in der Tabelle app_settings.

Umgebungsvariablen (core.config.Settings) liefern die Initial-/Fallback-Werte;
was der Wizard bzw. /admin/settings speichert, gewinnt.
"""

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from govdesk.core.config import get_settings
from govdesk.db.models import AppSetting


async def get_setting(db: AsyncSession, key: str, default: Any = None) -> Any:
    result = await db.execute(select(AppSetting.value).where(AppSetting.key == key))
    row = result.scalar_one_or_none()
    return default if row is None else row


async def set_setting(db: AsyncSession, key: str, value: Any) -> None:
    stmt = pg_insert(AppSetting).values(key=key, value=value)
    stmt = stmt.on_conflict_do_update(index_elements=["key"], set_={"value": value})
    await db.execute(stmt)


async def get_all_settings(db: AsyncSession) -> dict[str, Any]:
    result = await db.execute(select(AppSetting.key, AppSetting.value))
    return {key: value for key, value in result.all()}


@dataclass(frozen=True)
class RuntimeConfig:
    """Effektive KI-Konfiguration (app_settings mit env-Fallback)."""

    ollama_base_url: str
    ollama_api_key: str | None
    default_llm_model: str
    embedding_model: str
    reranker_url: str
    reranker_enabled: bool
    setup_completed: bool
    # Externer, OpenAI-kompatibler LLM-Provider (Mistral-API, Teuken/vLLM, …)
    llm_provider: str  # "ollama" | "openai"
    openai_base_url: str | None
    openai_api_key: str | None
    openai_model: str | None
    # OCR beim Einbetten: Bilddateien und PDF-Seiten ohne Textebene (Scans)
    # per Vision-Modell (Ollama) auslesen.
    ocr_enabled: bool
    ocr_model: str
    # Plattformweite Freigabe für Profile, die RAG vollständig überspringen.
    model_chat_enabled: bool

    @property
    def chat_model(self) -> str:
        """Standard-Chatmodell des aktiven Providers."""
        if self.llm_provider == "openai" and self.openai_model:
            return self.openai_model
        return self.default_llm_model


async def get_runtime_config(db: AsyncSession) -> RuntimeConfig:
    env = get_settings()
    stored = await get_all_settings(db)
    return RuntimeConfig(
        ollama_base_url=stored.get("ollama_base_url", env.ollama_base_url),
        ollama_api_key=stored.get("ollama_api_key", env.ollama_api_key),
        default_llm_model=stored.get("default_llm_model", env.default_llm_model),
        embedding_model=stored.get("embedding_model", env.embedding_model),
        reranker_url=stored.get("reranker_url", env.reranker_url),
        reranker_enabled=bool(stored.get("reranker_enabled", True)),
        setup_completed=bool(stored.get("setup_completed", False)),
        llm_provider=stored.get("llm_provider", "ollama") or "ollama",
        openai_base_url=stored.get("openai_base_url") or None,
        openai_api_key=stored.get("openai_api_key") or None,
        openai_model=stored.get("openai_model") or None,
        ocr_enabled=bool(stored.get("ocr_enabled", False)),
        ocr_model=stored.get("ocr_model") or "glm-ocr:latest",
        model_chat_enabled=bool(stored.get("model_chat_enabled", False)),
    )
