# SPDX-FileCopyrightText: 2026 GovDesk-Mitwirkende
#
# SPDX-License-Identifier: EUPL-1.2

"""robots.txt-Prüfung (protego) mit Cache pro Host und Crawl-Delay."""

from urllib.parse import urlsplit

import httpx
from protego import Protego

from govdesk.agents.crawler.fetch import USER_AGENT

MIN_DELAY_SECONDS = 1.0


class RobotsCache:
    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client
        self._cache: dict[str, Protego | None] = {}

    async def _get(self, url: str) -> Protego | None:
        host = urlsplit(url).netloc
        if host not in self._cache:
            robots_url = f"{urlsplit(url).scheme}://{host}/robots.txt"
            try:
                response = await self._client.get(robots_url)
                self._cache[host] = (
                    Protego.parse(response.text) if response.status_code == 200 else None
                )
            except httpx.HTTPError:
                self._cache[host] = None
        return self._cache[host]

    async def allowed(self, url: str) -> bool:
        robots = await self._get(url)
        return True if robots is None else robots.can_fetch(url, USER_AGENT)

    async def crawl_delay(self, url: str) -> float:
        robots = await self._get(url)
        delay = robots.crawl_delay(USER_AGENT) if robots is not None else None
        return max(float(delay or 0), MIN_DELAY_SECONDS)
