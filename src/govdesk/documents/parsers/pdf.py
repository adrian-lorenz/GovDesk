# SPDX-FileCopyrightText: 2026 GovDesk-Mitwirkende
#
# SPDX-License-Identifier: EUPL-1.2

"""PDF-Parser auf pypdf-Basis (pure Python, Seitenzahlen bleiben erhalten)."""

import io
import re

from pypdf import PdfReader

from govdesk.documents.parsers.base import Block, ParsedDocument


class PdfParser:
    def parse(self, data: bytes) -> ParsedDocument:
        reader = PdfReader(io.BytesIO(data))
        blocks: list[Block] = []
        for page_no, page in enumerate(reader.pages, start=1):
            text = page.extract_text() or ""
            # Absätze: Leerzeilen oder Zeilenumbrüche nach Satzende
            for paragraph in re.split(r"\n\s*\n", text):
                cleaned = " ".join(paragraph.split())
                if cleaned:
                    blocks.append(Block(text=cleaned, page_no=page_no))
        return ParsedDocument(blocks=blocks)
