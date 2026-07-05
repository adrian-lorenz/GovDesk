# SPDX-FileCopyrightText: 2026 GovDesk-Mitwirkende
#
# SPDX-License-Identifier: EUPL-1.2

"""Gemeinsames Parser-Interface: jedes Format wird zu Blöcken normalisiert."""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class Block:
    text: str
    heading_level: int | None = None  # None = Fließtext, 1..6 = Überschrift
    page_no: int | None = None


@dataclass(frozen=True)
class ParsedDocument:
    blocks: list[Block]


class DocumentParser(Protocol):
    def parse(self, data: bytes) -> ParsedDocument: ...


class UnsupportedFormatError(Exception):
    """Dateiformat wird (noch) nicht unterstützt."""
