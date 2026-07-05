# SPDX-FileCopyrightText: 2026 GovDesk-Mitwirkende
#
# SPDX-License-Identifier: EUPL-1.2

"""LLM-Provider (Chat-Streaming): Ollama (lokal/Cloud) und OpenAI-kompatibel
(z. B. Mistral-API, Teuken via vLLM, andere souveräne Endpunkte)."""

import json
from collections.abc import AsyncIterator
from typing import Protocol

import httpx
import ollama

from govdesk.core.app_settings import RuntimeConfig


class LLMProvider(Protocol):
    def stream_chat(
        self,
        messages: list[dict[str, str]],
        model: str,
        temperature: float = 0.2,
    ) -> AsyncIterator[str]: ...

    async def complete(
        self,
        messages: list[dict[str, str]],
        model: str,
        temperature: float = 0.2,
    ) -> str: ...

    async def list_models(self) -> list[str]: ...


class OllamaLLMProvider:
    def __init__(self, base_url: str, api_key: str | None = None) -> None:
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else None
        self._client = ollama.AsyncClient(host=base_url, headers=headers)

    async def stream_chat(
        self,
        messages: list[dict[str, str]],
        model: str,
        temperature: float = 0.2,
    ) -> AsyncIterator[str]:
        stream = await self._client.chat(
            model=model,
            messages=messages,
            stream=True,
            options={"temperature": temperature},
        )
        async for part in stream:
            content = part.message.content
            if content:
                yield content

    async def complete(
        self,
        messages: list[dict[str, str]],
        model: str,
        temperature: float = 0.2,
    ) -> str:
        """Einmalige (nicht gestreamte) Antwort — z. B. für Profil-Generierung."""
        response = await self._client.chat(
            model=model,
            messages=messages,
            stream=False,
            options={"temperature": temperature},
        )
        return response.message.content or ""

    async def list_models(self) -> list[str]:
        response = await self._client.list()
        return sorted(m.model for m in response.models if m.model)

    async def version(self) -> str:
        """Verbindungstest — wirft bei Nichterreichbarkeit."""
        # ollama-sdk hat keinen version-Call; ps() ist leichtgewichtig und auth-geprüft
        await self._client.ps()
        return "ok"

    async def pull_stream(self, model: str) -> AsyncIterator[tuple[str, int, int]]:
        """Modell-Pull mit Fortschritt: liefert (status, completed, total)."""
        stream = await self._client.pull(model=model, stream=True)
        async for part in stream:
            yield (part.status or "", part.completed or 0, part.total or 0)


class OpenAICompatProvider:
    """Provider für OpenAI-kompatible Endpunkte (Mistral-API, vLLM/Teuken, …).

    base_url sollte den API-Stamm inkl. Version enthalten,
    z. B. https://api.mistral.ai/v1 oder http://vllm:8000/v1.
    """

    def __init__(self, base_url: str, api_key: str | None = None, timeout: float = 120.0) -> None:
        self._base = base_url.rstrip("/")
        self._headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._timeout = timeout

    async def stream_chat(
        self,
        messages: list[dict[str, str]],
        model: str,
        temperature: float = 0.2,
    ) -> AsyncIterator[str]:
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "stream": True,
        }
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            async with client.stream(
                "POST", f"{self._base}/chat/completions", json=payload, headers=self._headers
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        obj = json.loads(data)
                    except ValueError:
                        continue
                    choices = obj.get("choices") or []
                    if choices:
                        content = (choices[0].get("delta") or {}).get("content")
                        if content:
                            yield content

    async def complete(
        self,
        messages: list[dict[str, str]],
        model: str,
        temperature: float = 0.2,
    ) -> str:
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "stream": False,
        }
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(
                f"{self._base}/chat/completions", json=payload, headers=self._headers
            )
            response.raise_for_status()
            data = response.json()
        choices = data.get("choices") or [{}]
        return (choices[0].get("message") or {}).get("content") or ""

    async def list_models(self) -> list[str]:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(f"{self._base}/models", headers=self._headers)
            response.raise_for_status()
            data = response.json()
        return sorted(m.get("id") for m in (data.get("data") or []) if m.get("id"))

    async def version(self) -> str:
        """Verbindungstest — listet Modelle, wirft bei Nichterreichbarkeit."""
        await self.list_models()
        return "ok"


def llm_provider_from_config(cfg: RuntimeConfig) -> LLMProvider:
    """Aktiver Chat-Provider gemäß Konfiguration (Ollama oder OpenAI-kompatibel)."""
    if cfg.llm_provider == "openai" and cfg.openai_base_url:
        return OpenAICompatProvider(cfg.openai_base_url, cfg.openai_api_key)
    return OllamaLLMProvider(cfg.ollama_base_url, cfg.ollama_api_key)
