# SPDX-FileCopyrightText: 2026 GovDesk-Mitwirkende
#
# SPDX-License-Identifier: EUPL-1.2

"""Client für den Reranker-Container (HuggingFace Text-Embeddings-Inference)."""

import httpx


class RerankerClient:
    def __init__(self, base_url: str, timeout: float = 30.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    async def rerank(self, query: str, texts: list[str]) -> list[tuple[int, float]]:
        """Liefert [(index, score)] absteigend nach Relevanz."""
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(
                f"{self._base_url}/rerank",
                json={"query": query, "texts": texts, "raw_scores": False},
            )
            response.raise_for_status()
        return [(item["index"], item["score"]) for item in response.json()]

    async def is_available(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                response = await client.get(f"{self._base_url}/health")
                return response.status_code == 200
        except httpx.HTTPError:
            return False
