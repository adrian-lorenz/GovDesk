# SPDX-FileCopyrightText: 2026 GovDesk-Mitwirkende
#
# SPDX-License-Identifier: EUPL-1.2

"""Parser für TXT und Markdown (Markdown-Überschriften bleiben Struktur)."""

import re

from govdesk.documents.parsers.base import Block, ParsedDocument

_MD_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")


class TextParser:
    def parse(self, data: bytes) -> ParsedDocument:
        text = data.decode("utf-8", errors="replace")
        blocks = [
            Block(text=" ".join(paragraph.split()))
            for paragraph in re.split(r"\n\s*\n", text)
            if paragraph.strip()
        ]
        return ParsedDocument(blocks=blocks)


class MarkdownParser:
    def parse(self, data: bytes) -> ParsedDocument:
        text = data.decode("utf-8", errors="replace")
        blocks: list[Block] = []
        for raw in re.split(r"\n\s*\n", text):
            stripped = raw.strip()
            if not stripped:
                continue
            match = _MD_HEADING.match(stripped.splitlines()[0])
            if match:
                blocks.append(Block(text=match.group(2).strip(), heading_level=len(match.group(1))))
                rest = "\n".join(stripped.splitlines()[1:]).strip()
                if rest:
                    blocks.append(Block(text=" ".join(rest.split())))
            else:
                blocks.append(Block(text=" ".join(stripped.split())))
        return ParsedDocument(blocks=blocks)
