# SPDX-FileCopyrightText: 2026 GovDesk-Mitwirkende
#
# SPDX-License-Identifier: EUPL-1.2

"""Notion-Connector: importiert die Seiten einer Notion-Integration als Markdown.

Voraussetzung: eine **interne Integration** in Notion anlegen
(https://www.notion.so/my-integrations), deren „Internal Integration Secret" hier
als Token eingetragen wird, und die gewünschten Seiten in Notion mit der
Integration teilen (Seite → „…" → „Verbindungen"). Der Connector durchsucht die
freigegebenen Seiten, wandelt die Blöcke in Markdown und liefert sie als Items.
"""

import logging
import re
from collections.abc import AsyncIterator
from typing import Any

import httpx

from govdesk.connectors.base import ConfigField, FetchedItem
from govdesk.connectors.registry import register

logger = logging.getLogger(__name__)

API = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"
_MAX_PAGES = 1000
_MAX_BLOCK_DEPTH = 3


def _safe_name(title: str) -> str:
    base = re.sub(r"[^A-Za-z0-9äöüÄÖÜß _-]+", "", title)[:120].strip()
    return f"{base or 'notion-seite'}.md"


def _rich(items: list[dict]) -> str:
    return "".join(part.get("plain_text", "") for part in (items or []))


def _page_title(page: dict) -> str:
    for prop in (page.get("properties") or {}).values():
        if prop.get("type") == "title":
            text = _rich(prop.get("title") or [])
            if text.strip():
                return text.strip()
    return "Unbenannt"


def _block_to_md(block: dict) -> str:
    """Einen Notion-Block in eine Markdown-Zeile übersetzen (gängige Typen)."""
    kind = block.get("type", "")
    body = block.get(kind) or {}
    text = _rich(body.get("rich_text") or [])
    match kind:
        case "heading_1":
            return f"# {text}"
        case "heading_2":
            return f"## {text}"
        case "heading_3":
            return f"### {text}"
        case "bulleted_list_item" | "toggle":
            return f"- {text}"
        case "numbered_list_item":
            return f"1. {text}"
        case "to_do":
            mark = "x" if body.get("checked") else " "
            return f"- [{mark}] {text}"
        case "quote" | "callout":
            return f"> {text}"
        case "code":
            return f"```{body.get('language', '')}\n{text}\n```"
        case "divider":
            return "---"
        case _:
            return text


class NotionConnector:
    type_id = "notion"
    label = "Notion"
    description = "Seiten einer Notion-Integration als Markdown importieren (Integrations-Token)."

    def config_fields(self) -> list[ConfigField]:
        return [
            ConfigField(
                "api_token",
                "Integrations-Token",
                kind="password",
                required=True,
                help="Secret aus notion.so/my-integrations; Seiten mit der Integration teilen.",
            ),
            ConfigField(
                "query",
                "Suchbegriff",
                kind="text",
                default="",
                help="Nur Seiten mit passendem Titel. Leer = alle freigegebenen Seiten.",
            ),
            ConfigField(
                "blacklist",
                "Ausschlussliste",
                kind="list",
                default=[],
                help="Seiten überspringen, deren Titel einen dieser Begriffe enthält.",
            ),
        ]

    async def fetch_items(self, config: dict[str, Any]) -> AsyncIterator[FetchedItem]:
        token = (config.get("api_token") or "").strip()
        query = (config.get("query") or "").strip()
        blacklist = [b.strip().lower() for b in (config.get("blacklist") or []) if b.strip()]
        if not token:
            raise ValueError("Notion: Integrations-Token ist erforderlich.")

        headers = {
            "Authorization": f"Bearer {token}",
            "Notion-Version": NOTION_VERSION,
            "Content-Type": "application/json",
        }
        yielded = 0
        async with httpx.AsyncClient(timeout=60.0, headers=headers) as client:
            async for page in self._search_pages(client, query):
                title = _page_title(page)
                if any(term in title.lower() for term in blacklist):
                    continue
                body = await self._page_markdown(client, page["id"])
                markdown = f"# {title}\n\n{body}".strip()
                if len(markdown) < 20:
                    continue  # praktisch leere Seite
                page_url = page.get("url")
                yield FetchedItem(
                    external_id=page["id"],
                    filename=_safe_name(title),
                    data=markdown.encode(),
                    content_type="text/markdown",
                    source_url=page_url,
                    content_hash=page.get("last_edited_time"),
                )
                yielded += 1
                if yielded >= _MAX_PAGES:
                    logger.warning("Notion: Obergrenze von %d Seiten erreicht.", _MAX_PAGES)
                    return

    async def _search_pages(self, client: httpx.AsyncClient, query: str) -> AsyncIterator[dict]:
        cursor: str | None = None
        while True:
            body: dict[str, Any] = {
                "filter": {"property": "object", "value": "page"},
                "page_size": 100,
            }
            if query:
                body["query"] = query
            if cursor:
                body["start_cursor"] = cursor
            resp = await client.post(f"{API}/search", json=body)
            resp.raise_for_status()
            data = resp.json()
            for page in data.get("results", []):
                yield page
            if not data.get("has_more"):
                return
            cursor = data.get("next_cursor")

    async def _page_markdown(self, client: httpx.AsyncClient, block_id: str, depth: int = 0) -> str:
        """Blöcke einer Seite/eines Blocks rekursiv als Markdown einsammeln."""
        lines: list[str] = []
        cursor: str | None = None
        while True:
            params = {"page_size": 100}
            if cursor:
                params["start_cursor"] = cursor
            try:
                resp = await client.get(f"{API}/blocks/{block_id}/children", params=params)
                resp.raise_for_status()
            except httpx.HTTPError as exc:
                logger.warning("Notion: Blöcke von %s nicht abrufbar: %s", block_id, exc)
                break
            data = resp.json()
            for block in data.get("results", []):
                line = _block_to_md(block)
                indent = "  " * depth
                if line:
                    lines.append(f"{indent}{line}")
                if block.get("has_children") and depth < _MAX_BLOCK_DEPTH:
                    child = await self._page_markdown(client, block["id"], depth + 1)
                    if child:
                        lines.append(child)
            if not data.get("has_more"):
                break
            cursor = data.get("next_cursor")
        return "\n".join(lines)


register(NotionConnector())
