# SPDX-FileCopyrightText: 2026 GovDesk-Mitwirkende
#
# SPDX-License-Identifier: EUPL-1.2

from pathlib import Path

from govdesk.documents.parsers.base import Block
from govdesk.documents.parsers.text import TextParser
from govdesk.rag.chunking import chunk_blocks

FIXTURES = Path(__file__).parent.parent / "fixtures"


def test_paragraph_grenzen_trennen_chunks():
    """Ein Chunk darf nie zwei Paragraphen (§) vermischen."""
    parsed = TextParser().parse((FIXTURES / "mustersatzung.txt").read_bytes())
    chunks = chunk_blocks(parsed.blocks)

    assert len(chunks) >= 8  # 8 §§ + Präambel/Titel
    for chunk in chunks:
        # Zählt §-Marker am Zeilenanfang im Chunk-Text — je Chunk maximal einer
        markers = [line for line in chunk.text.splitlines() if line.strip().startswith("§")]
        assert len(markers) <= 1, f"Chunk vermischt Paragraphen: {chunk.text[:80]}"


def test_heading_path_enthaelt_paragraph():
    parsed = TextParser().parse((FIXTURES / "mustersatzung.txt").read_bytes())
    chunks = chunk_blocks(parsed.blocks)
    leihfrist = [c for c in chunks if "Leihfrist beträgt" in c.text]
    assert leihfrist, "§ 3-Chunk nicht gefunden"
    assert "§ 3" in (leihfrist[0].heading_path or "")


def test_lange_abschnitte_mit_ueberlappung():
    absatz = "Dies ist ein Satz über das Vergaberecht. " * 120  # ~5000 Zeichen
    chunks = chunk_blocks([Block(text=absatz)])
    assert len(chunks) >= 2
    assert all(c.token_count <= 500 for c in chunks)


def test_ueberschriften_bilden_pfad():
    blocks = [
        Block(text="Vergabeordnung", heading_level=1),
        Block(text="Abschnitt 2", heading_level=2),
        Block(text="Die Vergabe erfolgt im offenen Verfahren."),
    ]
    chunks = chunk_blocks(blocks)
    assert chunks[0].heading_path == "Vergabeordnung > Abschnitt 2"
