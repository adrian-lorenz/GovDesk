# SPDX-FileCopyrightText: 2026 GovDesk-Mitwirkende
#
# SPDX-License-Identifier: EUPL-1.2

from govdesk.connectors.gesetze_im_internet.plugin import (
    LAW_CHOICES,
    GesetzeImInternetConnector,
    LawEntry,
    _parse_catalog,
    _resolve_entries,
    _xml_to_markdown,
)
from govdesk.documents.parsers.text import MarkdownParser
from govdesk.rag.chunking import chunk_blocks

TOC = b"""<?xml version="1.0" encoding="UTF-8"?>
<items>
  <item>
    <title>Grundgesetz f\xc3\xbcr die Bundesrepublik Deutschland</title>
    <link>http://www.gesetze-im-internet.de/gg/xml.zip</link>
  </item>
  <item>
    <title>B\xc3\xbcrgerliches Gesetzbuch</title>
    <link>http://www.gesetze-im-internet.de/bgb/xml.zip</link>
  </item>
</items>
"""

LAW_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<dokumente builddate="20260722000000" doknr="TEST">
  <norm>
    <metadaten>
      <jurabk>GG</jurabk>
      <langue>Grundgesetz f\xc3\xbcr die Bundesrepublik Deutschland</langue>
      <standangabe><standkommentar>Zuletzt ge\xc3\xa4ndert 2025</standkommentar></standangabe>
    </metadaten>
    <textdaten><text><Content><P>Vorbemerkung</P></Content></text></textdaten>
  </norm>
  <norm>
    <metadaten>
      <jurabk>GG</jurabk>
      <gliederungseinheit>
        <gliederungsbez>I.</gliederungsbez>
        <gliederungstitel>Die Grundrechte</gliederungstitel>
      </gliederungseinheit>
    </metadaten>
  </norm>
  <norm>
    <metadaten>
      <jurabk>GG</jurabk>
      <enbez>Art 1</enbez>
      <titel>Menschenw\xc3\xbcrde</titel>
    </metadaten>
    <textdaten>
      <text><Content><P>(1) Die W\xc3\xbcrde des Menschen ist unantastbar.</P>
      <P>(2) Das Deutsche Volk bekennt sich zu den Menschenrechten.</P></Content></text>
    </textdaten>
  </norm>
  <norm>
    <metadaten>
      <jurabk>GG</jurabk>
      <enbez>Art 2</enbez>
      <titel>Freie Entfaltung</titel>
    </metadaten>
    <textdaten>
      <text><Content><P>Jeder hat das Recht auf freie Entfaltung.</P></Content></text>
    </textdaten>
  </norm>
</dokumente>
"""


def test_katalog_und_eindeutige_auswahl():
    catalog = _parse_catalog(TOC)

    assert catalog == [
        LawEntry("gg", "Grundgesetz für die Bundesrepublik Deutschland"),
        LawEntry("bgb", "Bürgerliches Gesetzbuch"),
    ]
    assert _resolve_entries(catalog, ["GG", "Bürgerliches Gesetzbuch"]) == catalog


def test_formular_bietet_vorausgefuellte_checkboxen():
    connector = GesetzeImInternetConnector()
    field = connector.config_fields()[0]

    assert connector.default_name == "Bundesgesetze"
    assert connector.default_sync_interval_hours == 24
    assert field.kind == "checkboxes"
    assert field.default == ["gg", "bgb"]
    assert ("gg", "GG — Grundgesetz") in LAW_CHOICES
    assert ("bdsg_2018", "BDSG — Bundesdatenschutzgesetz") in LAW_CHOICES


def test_nicht_eindeutige_auswahl_wird_abgelehnt():
    catalog = [
        LawEntry("foo", "Erstes Testgesetz"),
        LawEntry("bar", "Zweites Testgesetz"),
    ]

    try:
        _resolve_entries(catalog, ["Testgesetz"])
    except ValueError as exc:
        assert "nicht eindeutig" in str(exc)
    else:
        raise AssertionError("Mehrdeutige Auswahl wurde akzeptiert")


def test_xml_wird_paragraphentreu_gechunkt():
    markdown, filename = _xml_to_markdown(LAW_XML, "Fallback", "gg")
    chunks = chunk_blocks(MarkdownParser().parse(markdown.encode()).blocks)

    assert filename == "gg.md"
    assert "# Grundgesetz für die Bundesrepublik Deutschland (GG)" in markdown
    assert "###### Art 1 – Menschenwürde" in markdown
    assert any("Würde des Menschen" in chunk.text for chunk in chunks)
    assert any("Art 1" in (chunk.heading_path or "") for chunk in chunks)
    assert any("Art 2" in (chunk.heading_path or "") for chunk in chunks)
    assert not any(
        "Würde des Menschen" in chunk.text and "freie Entfaltung" in chunk.text for chunk in chunks
    )
