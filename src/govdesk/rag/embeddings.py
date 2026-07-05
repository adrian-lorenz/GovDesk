# SPDX-FileCopyrightText: 2026 GovDesk-Mitwirkende
#
# SPDX-License-Identifier: EUPL-1.2

"""Embedding-Provider. Ollama deckt lokal UND Cloud ab (Bearer-Token)."""

from typing import Protocol

import ollama

from govdesk.core.app_settings import RuntimeConfig


class EmbeddingProvider(Protocol):
    async def embed(self, texts: list[str], model: str) -> list[list[float]]: ...


class OllamaEmbeddingProvider:
    def __init__(self, base_url: str, api_key: str | None = None) -> None:
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else None
        self._client = ollama.AsyncClient(host=base_url, headers=headers)

    async def embed(self, texts: list[str], model: str) -> list[list[float]]:
        vectors: list[list[float]] = []
        # Batches begrenzen: Ollama verarbeitet Embeddings weitgehend seriell
        batch_size = 16
        for start in range(0, len(texts), batch_size):
            batch = texts[start : start + batch_size]
            response = await self._client.embed(model=model, input=batch)
            vectors.extend([list(v) for v in response.embeddings])
        return vectors


def embedding_provider_from_config(cfg: RuntimeConfig) -> OllamaEmbeddingProvider:
    return OllamaEmbeddingProvider(cfg.ollama_base_url, cfg.ollama_api_key)
