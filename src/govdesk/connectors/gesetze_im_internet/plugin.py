# SPDX-FileCopyrightText: 2026 GovDesk-Mitwirkende
#
# SPDX-License-Identifier: EUPL-1.2

"""Importiert ausgewählte Bundesgesetze aus dem QuantLaw-Tagesarchiv.

Der ``data``-Branch von QuantLaw/gesetze-im-internet enthält das täglich
aktualisierte Inhaltsverzeichnis sowie die amtlichen XML-Dateien. Pro Gesetz
entsteht ein strukturiertes Markdown-Dokument. Die Überschriften bilden die
Gliederung und Paragraphen ab, sodass der generische GovDesk-Chunker harte
Grenzen zwischen Normen zieht.
"""

import hashlib
import re
import xml.etree.ElementTree as ET
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote, urlsplit

import httpx

from govdesk.connectors.base import ConfigField, FetchedItem
from govdesk.connectors.registry import register

TOC_URL = "https://raw.githubusercontent.com/QuantLaw/gesetze-im-internet/data/data/toc.xml"
CONTENTS_API = (
    "https://api.github.com/repos/QuantLaw/gesetze-im-internet/contents/data/items/{slug}?ref=data"
)
OFFICIAL_BASE_URL = "https://www.gesetze-im-internet.de"
MAX_LAWS = 25
MAX_XML_BYTES = 20 * 1024 * 1024
LAW_CHOICES = [
    ("gg", "GG — Grundgesetz"),
    ("gwb", "GWB — Gesetz gegen Wettbewerbsbeschränkungen"),
    ("bgb", "BGB — Bürgerliches Gesetzbuch"),
    ("hgb", "HGB — Handelsgesetzbuch"),
    ("stgb", "StGB — Strafgesetzbuch"),
    ("stpo", "StPO — Strafprozessordnung"),
    ("zpo", "ZPO — Zivilprozessordnung"),
    ("vwvfg", "VwVfG — Verwaltungsverfahrensgesetz"),
    ("vwgo", "VwGO — Verwaltungsgerichtsordnung"),
    ("ao_1977", "AO — Abgabenordnung"),
    ("sgb_1", "SGB I — Allgemeiner Teil"),
    ("sgb_10", "SGB X — Sozialverwaltungsverfahren und Sozialdatenschutz"),
    ("bdsg_2018", "BDSG — Bundesdatenschutzgesetz"),
    ("ifsg", "IfSG — Infektionsschutzgesetz"),
    ("aufenthg_2004", "AufenthG — Aufenthaltsgesetz"),
    ("bbaug", "BauGB — Baugesetzbuch"),
    ("gewo", "GewO — Gewerbeordnung"),
]

_SPACE = re.compile(r"[^\S\n]+")
_NEWLINES = re.compile(r"\n{3,}")
_SAFE_NAME = re.compile(r"[^A-Za-z0-9äöüÄÖÜß._-]+")
_BREAK_TAGS = {
    "BR",
    "P",
    "DD",
    "DT",
    "LI",
    "LA",
    "TR",
    "ROW",
}


@dataclass(frozen=True)
class LawEntry:
    slug: str
    title: str


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _node_text(node: ET.Element | None) -> str:
    """XML-Text mit lesbaren Absatz-/Zeilenumbrüchen extrahieren."""
    if node is None:
        return ""
    parts: list[str] = []

    def visit(current: ET.Element) -> None:
        if current.text:
            parts.append(current.text)
        for child in current:
            if _local_name(child.tag).upper() == "BR":
                parts.append("\n")
            visit(child)
            if _local_name(child.tag).upper() in _BREAK_TAGS:
                parts.append("\n")
            if child.tail:
                parts.append(child.tail)

    visit(node)
    text = _SPACE.sub(" ", "".join(parts))
    text = "\n".join(line.strip() for line in text.splitlines())
    return _NEWLINES.sub("\n\n", text).strip()


def _first_text(node: ET.Element, path: str) -> str:
    found = node.find(path)
    return _node_text(found)


def _heading_level(label: str) -> int:
    lowered = label.casefold()
    if lowered.startswith(("teil", "buch")):
        return 2
    if lowered.startswith("abschnitt"):
        return 3
    if lowered.startswith("titel"):
        return 4
    if lowered.startswith(("untertitel", "kapitel")):
        return 5
    return 2


def _xml_to_markdown(data: bytes, fallback_title: str, slug: str) -> tuple[str, str]:
    """Amtliches GII-XML in ein chunkfreundliches Markdown-Dokument wandeln."""
    if len(data) > MAX_XML_BYTES:
        raise ValueError(f"{slug}: XML ist größer als {MAX_XML_BYTES // 1024 // 1024} MB.")
    root = ET.fromstring(data)  # noqa: S314 - feste, öffentliche QuantLaw-Quelle
    norms = root.findall("./norm")
    if not norms:
        raise ValueError(f"{slug}: XML enthält keine Normen.")

    first_meta = norms[0].find("./metadaten")
    title = _first_text(first_meta, "./langue") if first_meta is not None else ""
    abbreviation = _first_text(first_meta, "./jurabk") if first_meta is not None else ""
    title = title or fallback_title
    display_title = f"{title} ({abbreviation})" if abbreviation else title
    lines = [f"# {display_title}", "", f"Quelle: {OFFICIAL_BASE_URL}/{slug}/"]

    builddate = root.attrib.get("builddate", "")
    if builddate:
        lines.append(f"Datenstand (Build): {builddate}")
    if first_meta is not None:
        for status in first_meta.findall("./standangabe/standkommentar"):
            value = _node_text(status)
            if value:
                lines.append(f"Stand: {value}")

    for index, norm in enumerate(norms):
        metadata = norm.find("./metadaten")
        if metadata is None:
            continue

        structure = metadata.find("./gliederungseinheit")
        if structure is not None:
            label = _first_text(structure, "./gliederungsbez")
            structure_title = _first_text(structure, "./gliederungstitel")
            heading = " – ".join(part for part in (label, structure_title) if part)
            if heading:
                lines.extend(("", f"{'#' * _heading_level(label)} {heading}"))
            continue

        designation = _first_text(metadata, "./enbez")
        if designation.casefold() == "inhaltsübersicht":
            continue
        norm_title = _first_text(metadata, "./titel")
        content = _node_text(norm.find("./textdaten/text"))

        if designation:
            heading = " – ".join(part for part in (designation, norm_title) if part)
            lines.extend(("", f"###### {heading}"))
        elif index == 0 and content:
            lines.extend(("", "## Vorbemerkungen"))

        if content:
            lines.extend(("", content))

    markdown = "\n".join(lines).strip() + "\n"
    safe_base = _SAFE_NAME.sub("-", abbreviation or slug).strip("-_.").lower() or slug
    return markdown, f"{safe_base}.md"


def _parse_catalog(data: bytes) -> list[LawEntry]:
    root = ET.fromstring(data)  # noqa: S314 - feste, öffentliche QuantLaw-Quelle
    entries: list[LawEntry] = []
    for item in root.findall("./item"):
        title = _first_text(item, "./title")
        link = _first_text(item, "./link")
        parts = [part for part in urlsplit(link).path.split("/") if part]
        if title and len(parts) >= 2 and parts[-1] == "xml.zip":
            entries.append(LawEntry(slug=parts[-2], title=title))
    return entries


def _resolve_entries(catalog: list[LawEntry], terms: list[str]) -> list[LawEntry]:
    """Kürzel/Slug oder eindeutige Titelsuche auf Katalogeinträge abbilden."""
    if not terms:
        raise ValueError("Mindestens ein Gesetz angeben, z. B. GG, BGB oder VwVfG.")
    if len(terms) > MAX_LAWS:
        raise ValueError(f"Pro Quelle sind höchstens {MAX_LAWS} Gesetze erlaubt.")

    resolved: list[LawEntry] = []
    seen: set[str] = set()
    for raw_term in terms:
        term = raw_term.strip().casefold()
        if not term:
            continue
        exact = [
            entry
            for entry in catalog
            if entry.slug.casefold() == term or entry.title.casefold() == term
        ]
        matches = exact or [
            entry
            for entry in catalog
            if term in entry.slug.casefold() or term in entry.title.casefold()
        ]
        if not matches:
            raise ValueError(f"Kein Gesetz für „{raw_term}“ gefunden.")
        if len(matches) > 1:
            examples = ", ".join(f"{entry.slug} ({entry.title})" for entry in matches[:4])
            raise ValueError(
                f"„{raw_term}“ ist nicht eindeutig. Bitte Slug verwenden, z. B.: {examples}"
            )
        entry = matches[0]
        if entry.slug not in seen:
            resolved.append(entry)
            seen.add(entry.slug)
    return resolved


async def _response_bytes(response: httpx.Response, label: str) -> bytes:
    response.raise_for_status()
    data = response.content
    if len(data) > MAX_XML_BYTES:
        raise ValueError(f"{label}: Download ist größer als 20 MB.")
    return data


class GesetzeImInternetConnector:
    type_id = "gesetze_im_internet"
    label = "Gesetze im Internet"
    description = "Ausgewählte Bundesgesetze aus dem täglich aktualisierten QuantLaw-XML-Archiv."
    supports_preview = True
    default_name = "Bundesgesetze"
    default_sync_interval_hours = 24

    def config_fields(self) -> list[ConfigField]:
        return [
            ConfigField(
                "laws",
                "Gesetze",
                kind="checkboxes",
                default=["gg", "bgb"],
                required=True,
                help=(
                    "GG und BGB sind vorausgewählt. Die Auswahl kann vor dem "
                    "Import über die Chunk-Vorschau geprüft werden."
                ),
                choices=LAW_CHOICES,
            ),
        ]

    async def fetch_items(self, config: dict[str, Any]) -> AsyncIterator[FetchedItem]:
        terms = [str(value).strip() for value in (config.get("laws") or []) if str(value).strip()]
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "GovDesk-Gesetze-Connector/0.1",
        }
        async with httpx.AsyncClient(
            timeout=120.0, headers=headers, follow_redirects=True
        ) as client:
            toc_response = await client.get(TOC_URL)
            catalog = _parse_catalog(await _response_bytes(toc_response, "Inhaltsverzeichnis"))
            selected = _resolve_entries(catalog, terms)

            for entry in selected:
                listing_response = await client.get(
                    CONTENTS_API.format(slug=quote(entry.slug, safe=""))
                )
                listing_response.raise_for_status()
                listing = listing_response.json()
                xml_files = [
                    row
                    for row in listing
                    if row.get("type") == "file"
                    and str(row.get("name", "")).lower().endswith(".xml")
                    and row.get("download_url")
                ]
                if not xml_files:
                    raise ValueError(f"{entry.slug}: Keine XML-Datei im QuantLaw-Archiv.")

                markdown_parts: list[str] = []
                filename = f"{entry.slug}.md"
                shas: list[str] = []
                for row in sorted(xml_files, key=lambda value: value["name"]):
                    xml_response = await client.get(row["download_url"])
                    xml_data = await _response_bytes(xml_response, entry.slug)
                    markdown, filename = _xml_to_markdown(xml_data, entry.title, entry.slug)
                    markdown_parts.append(markdown)
                    shas.append(str(row.get("sha") or hashlib.sha256(xml_data).hexdigest()))

                yield FetchedItem(
                    external_id=entry.slug,
                    filename=filename,
                    data="\n\n".join(markdown_parts).encode(),
                    content_type="text/markdown",
                    source_url=f"{OFFICIAL_BASE_URL}/{entry.slug}/",
                    content_hash=hashlib.sha256("|".join(shas).encode()).hexdigest(),
                )


register(GesetzeImInternetConnector())
