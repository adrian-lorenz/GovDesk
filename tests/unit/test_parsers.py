# SPDX-FileCopyrightText: 2026 GovDesk-Mitwirkende
#
# SPDX-License-Identifier: EUPL-1.2

from pathlib import Path

import pytest

from govdesk.documents.parsers.base import UnsupportedFormatError
from govdesk.documents.parsers.docx import DocxParser
from govdesk.documents.parsers.html import HtmlParser
from govdesk.documents.parsers.odt import OdtParser
from govdesk.documents.parsers.registry import parser_for

FIXTURES = Path(__file__).parent.parent / "fixtures"


def test_docx_ueberschriften_und_tabellen():
    parsed = DocxParser().parse((FIXTURES / "dienstanweisung.docx").read_bytes())
    headings = [b for b in parsed.blocks if b.heading_level is not None]
    assert any("IT-Sicherheit" in h.text for h in headings)
    assert any(h.heading_level == 2 for h in headings)
    assert any("zwölf Zeichen" in b.text for b in parsed.blocks)
    assert any("Sachbearbeiter | Lesen" in b.text for b in parsed.blocks)


def test_odt_ueberschriften():
    parsed = OdtParser().parse((FIXTURES / "geschaeftsordnung.odt").read_bytes())
    headings = [b for b in parsed.blocks if b.heading_level is not None]
    assert any("Geschäftsordnung" in h.text for h in headings)
    assert any("Bürgermeisterin" in b.text for b in parsed.blocks)


def test_html_hauptinhalt():
    html = """<html><head><title>Test</title><style>nav{}</style></head><body>
    <nav>Menü Menü Menü</nav>
    <main><h1>Satzung über Straßenreinigung</h1>
    <p>Die Reinigung der öffentlichen Straßen obliegt der Gemeinde, soweit diese
    Satzung nichts anderes bestimmt. Anlieger sind zur Reinigung der Gehwege
    verpflichtet und tragen die damit verbundenen Kosten anteilig.</p></main>
    <footer>Impressum</footer></body></html>"""
    parsed = HtmlParser().parse(html.encode())
    text = " ".join(b.text for b in parsed.blocks)
    assert "Straßenreinigung" in text
    assert "Gehwege" in text


def test_registry_unbekanntes_format():
    with pytest.raises(UnsupportedFormatError, match="wird noch nicht unterstützt"):
        parser_for("tabelle.xlsx")


def test_doc_legacy_ohne_flag_klare_meldung():
    with pytest.raises(UnsupportedFormatError, match="DOCX oder PDF"):
        parser_for("alt.doc").parse(b"\xd0\xcf\x11\xe0")
