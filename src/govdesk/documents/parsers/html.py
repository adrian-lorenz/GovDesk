# SPDX-FileCopyrightText: 2026 GovDesk-Mitwirkende
#
# SPDX-License-Identifier: EUPL-1.2

"""HTML-Parser: trafilatura extrahiert den Hauptinhalt als Markdown,
danach übernimmt der Markdown-Parser die Struktur. Fällt trafilatura aus
(z. B. fehlendes lxml-Wheel), greift ein einfacher selectolax-Extraktor."""

import logging

from govdesk.documents.parsers.base import Block, ParsedDocument
from govdesk.documents.parsers.text import MarkdownParser

logger = logging.getLogger(__name__)


class HtmlParser:
    def parse(self, data: bytes) -> ParsedDocument:
        markdown = self._extract_markdown(data)
        if markdown:
            return MarkdownParser().parse(markdown.encode())
        return self._fallback(data)

    def _extract_markdown(self, data: bytes) -> str | None:
        try:
            import trafilatura
        except ImportError:
            logger.warning("trafilatura nicht verfügbar — nutze selectolax-Fallback")
            return None
        return trafilatura.extract(
            data,
            output_format="markdown",
            include_comments=False,
            include_tables=True,
            include_links=False,
        )

    def _fallback(self, data: bytes) -> ParsedDocument:
        from selectolax.parser import HTMLParser as SelectolaxParser

        tree = SelectolaxParser(data.decode("utf-8", errors="replace"))
        for selector in ("script", "style", "nav", "header", "footer", "aside"):
            for node in tree.css(selector):
                node.decompose()
        blocks: list[Block] = []
        body = tree.body
        if body is None:
            return ParsedDocument(blocks=[])
        for node in body.css("h1, h2, h3, h4, h5, h6, p, li, td"):
            text = " ".join((node.text() or "").split())
            if not text:
                continue
            if node.tag.startswith("h") and len(node.tag) == 2:
                blocks.append(Block(text=text, heading_level=int(node.tag[1])))
            else:
                blocks.append(Block(text=text))
        return ParsedDocument(blocks=blocks)
