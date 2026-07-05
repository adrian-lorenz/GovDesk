# SPDX-FileCopyrightText: 2026 GovDesk-Mitwirkende
#
# SPDX-License-Identifier: EUPL-1.2

"""HTTP-Abruf mit Größen-Cap, Timeout und höflichem User-Agent."""

from dataclasses import dataclass

import httpx

from govdesk import __version__

USER_AGENT = f"GovDeskCrawler/{__version__} (+https://gitlab.opencode.de/govdesk)"
MAX_RESPONSE_BYTES = 10 * 1024 * 1024
TIMEOUT_SECONDS = 20.0


@dataclass(frozen=True)
class FetchResult:
    url: str  # finale URL nach Redirects
    status_code: int
    content: bytes
    content_type: str


def new_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        follow_redirects=True,
        timeout=TIMEOUT_SECONDS,
        headers={"User-Agent": USER_AGENT, "Accept-Language": "de"},
    )


async def fetch_page(client: httpx.AsyncClient, url: str) -> FetchResult:
    async with client.stream("GET", url) as response:
        chunks: list[bytes] = []
        size = 0
        async for chunk in response.aiter_bytes():
            size += len(chunk)
            if size > MAX_RESPONSE_BYTES:
                raise ValueError(f"Antwort größer als {MAX_RESPONSE_BYTES // (1024 * 1024)} MB")
            chunks.append(chunk)
        return FetchResult(
            url=str(response.url),
            status_code=response.status_code,
            content=b"".join(chunks),
            content_type=response.headers.get("content-type", ""),
        )
