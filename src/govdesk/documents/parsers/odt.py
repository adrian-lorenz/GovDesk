# SPDX-FileCopyrightText: 2026 GovDesk-Mitwirkende
#
# SPDX-License-Identifier: EUPL-1.2

"""ODT/ODF-Parser (odfpy): text:h mit outline-level wird Struktur."""

import io

from odf import teletype
from odf.opendocument import load as odf_load
from odf.table import Table, TableRow
from odf.text import H, P

from govdesk.documents.parsers.base import Block, ParsedDocument


class OdtParser:
    def parse(self, data: bytes) -> ParsedDocument:
        document = odf_load(io.BytesIO(data))
        blocks: list[Block] = []

        for element in document.text.childNodes:
            tag = getattr(element, "qname", (None, None))[1]
            if tag == "h":
                text = " ".join(teletype.extractText(element).split())
                if text:
                    level = int(element.getAttribute("outlinelevel") or 1)
                    blocks.append(Block(text=text, heading_level=min(level, 6)))
            elif tag == "p":
                text = " ".join(teletype.extractText(element).split())
                if text:
                    blocks.append(Block(text=text))

        for table in document.text.getElementsByType(Table):
            for row in table.getElementsByType(TableRow):
                cells = [" ".join(teletype.extractText(c).split()) for c in row.childNodes]
                line = " | ".join(c for c in cells if c)
                if line:
                    blocks.append(Block(text=line))

        # Unbenutzte Importe vermeiden (H/P dienen der Dokumentation der Struktur)
        _ = (H, P)
        return ParsedDocument(blocks=blocks)
