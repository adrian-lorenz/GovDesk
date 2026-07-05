# SPDX-FileCopyrightText: 2026 GovDesk-Mitwirkende
#
# SPDX-License-Identifier: EUPL-1.2

"""URL-Frontier: Normalisierung, Deduplizierung, Tiefen-/Domain-/Muster-Regeln."""

import hashlib
import re
from collections import deque
from urllib.parse import urljoin, urlsplit, urlunsplit

from selectolax.parser import HTMLParser


def normalize_url(url: str) -> str:
    """Fragment entfernen, Host kleinschreiben, Query sortiert lassen wie sie ist."""
    parts = urlsplit(url.strip())
    return urlunsplit(
        (parts.scheme.lower(), parts.netloc.lower(), parts.path or "/", parts.query, "")
    )


def url_hash(url: str) -> str:
    return hashlib.sha256(normalize_url(url).encode()).hexdigest()


def extract_links(base_url: str, html: bytes) -> list[str]:
    tree = HTMLParser(html.decode("utf-8", errors="replace"))
    links = []
    for node in tree.css("a[href]"):
        href = node.attributes.get("href") or ""
        if href.startswith(("mailto:", "javascript:", "tel:", "#")):
            continue
        links.append(normalize_url(urljoin(base_url, href)))
    return links


def extract_links_with_text(base_url: str, html: bytes) -> list[tuple[str, str]]:
    """Wie ``extract_links``, aber mit Ankertext — als Entscheidungshilfe fürs
    LLM. Dedupliziert nach URL (erster gefundener Text gewinnt)."""
    tree = HTMLParser(html.decode("utf-8", errors="replace"))
    pairs: list[tuple[str, str]] = []
    seen: set[str] = set()
    for node in tree.css("a[href]"):
        href = node.attributes.get("href") or ""
        if href.startswith(("mailto:", "javascript:", "tel:", "#")):
            continue
        url = normalize_url(urljoin(base_url, href))
        if url in seen:
            continue
        seen.add(url)
        text = " ".join((node.text() or "").split())[:120]
        pairs.append((url, text))
    return pairs


class Frontier:
    """Warteschlange mit allen Crawl-Regeln einer Quelle."""

    def __init__(
        self,
        start_url: str,
        max_depth: int,
        max_pages: int,
        allowed_domains: list[str] | None = None,
        include_pattern: str | None = None,
        exclude_pattern: str | None = None,
    ) -> None:
        start = normalize_url(start_url)
        self.max_depth = max_depth
        self.max_pages = max_pages
        self.allowed_domains = [d.lower() for d in (allowed_domains or [])] or [
            urlsplit(start).netloc
        ]
        self.include = re.compile(include_pattern) if include_pattern else None
        self.exclude = re.compile(exclude_pattern) if exclude_pattern else None
        self._queue: deque[tuple[str, int]] = deque([(start, 0)])
        self._seen: set[str] = {start}

    def _admissible(self, url: str) -> bool:
        parts = urlsplit(url)
        if parts.scheme not in ("http", "https"):
            return False
        if not any(
            parts.netloc == d or parts.netloc.endswith(f".{d}") for d in self.allowed_domains
        ):
            return False
        if self.include is not None and not self.include.search(url):
            return False
        if self.exclude is not None and self.exclude.search(url):
            return False
        return True

    def add(self, url: str, depth: int) -> None:
        url = normalize_url(url)
        if depth > self.max_depth or url in self._seen or not self._admissible(url):
            return
        self._seen.add(url)
        self._queue.append((url, depth))

    def pop(self) -> tuple[str, int] | None:
        return self._queue.popleft() if self._queue else None

    def __len__(self) -> int:
        return len(self._queue)
