# SPDX-FileCopyrightText: 2026 GovDesk-Mitwirkende
#
# SPDX-License-Identifier: EUPL-1.2

"""TED-Connector: ruft deutsche EU-Ausschreibungen (CPV-gefiltert) aus der
offiziellen TED-API ab und liefert die deutschen PDF-Bekanntmachungen als Items.

TED (Tenders Electronic Daily): https://api.ted.europa.eu — kein API-Key nötig.
Fachlich abgeleitet aus dem bewährten Stand-alone-Skript; hier async (httpx) und
in den generischen Connector-Vertrag (govdesk.connectors.base) integriert.
"""

import asyncio
import logging
import re
from collections.abc import AsyncIterator
from typing import Any

import httpx

from govdesk.connectors.base import ConfigField, FetchedItem
from govdesk.connectors.registry import register

logger = logging.getLogger(__name__)

API_URL = "https://api.ted.europa.eu/v3/notices/search"
DETAIL_URL = "https://ted.europa.eu/de/notice/-/detail/{nr}"
PAGE_LIMIT = 250  # Maximum pro Seite laut TED-API
# Auswählbare CPV-Hauptkategorien (Code → Klartext) für die Connector-Konfiguration.
CPV_CHOICES = [
    ("48000000", "Software & Informationssysteme"),
    ("72000000", "IT-Dienstleistungen (Beratung, Entwicklung)"),
    ("30200000", "Computeranlagen & Zubehör"),
    ("79000000", "Unternehmens- & Verwaltungsdienste"),
    ("71000000", "Architektur- & Ingenieurleistungen"),
    ("90900000", "Reinigungsdienste"),
    ("80000000", "Aus- & Weiterbildung"),
    ("85000000", "Gesundheits- & Sozialwesen"),
]
# Vorausgewählt: Software, IT-Dienste, Reinigung
DEFAULT_CPV = ["48000000", "72000000", "90900000"]
_FIELDS = [
    "publication-number",
    "notice-title",
    "publication-date",
    "classification-cpv",
    "buyer-name",
    "links",
    # BT-15: „Elektronischer Zugang zu den Auftragsunterlagen" — Link auf die
    # vollständige Leistungsbeschreibung/Vergabeunterlagen auf der Vergabeplattform.
    "BT-15-Lot",
    "BT-15-Part",
]


def _text(value: Any) -> str:
    """TED liefert manche Felder mehrsprachig (dict/list) — Deutsch bevorzugen."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return _text(value[0]) if value else ""
    if isinstance(value, dict):
        for key in ("deu", "DEU", "de", "eng", "ENG"):
            if key in value:
                return _text(value[key])
        for v in value.values():
            return _text(v)
    return str(value)


def _pdf_url(notice: dict) -> str | None:
    links = notice.get("links") or {}
    pdf = links.get("pdf") or {}
    return pdf.get("DEU") or pdf.get("ENG") or next(iter(pdf.values()), None)


def _documents_url(notice: dict) -> str | None:
    """Erste „Documents URL" (BT-15) — Zugang zu den vollständigen Vergabeunterlagen."""
    for feld in ("BT-15-Lot", "BT-15-Part"):
        werte = notice.get(feld)
        if isinstance(werte, str) and werte.strip():
            return werte.strip()
        if isinstance(werte, list):
            for url in werte:
                if isinstance(url, str) and url.strip():
                    return url.strip()
    return None


def _safe_name(nr: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", nr).strip("-") or "ausschreibung"


class TedConnector:
    type_id = "ted"
    label = "TED-Ausschreibungen (EU)"
    description = "Deutsche EU-Ausschreibungen aus der TED-Datenbank, nach CPV gefiltert."

    def config_fields(self) -> list[ConfigField]:
        return [
            ConfigField(
                "cpv",
                "CPV-Kategorien",
                kind="checkboxes",
                choices=CPV_CHOICES,
                default=DEFAULT_CPV,
                help="EU-Beschaffungskategorien, nach denen gefiltert wird.",
            ),
            ConfigField(
                "land",
                "Erfüllungsort (ISO-Ländercode)",
                kind="text",
                default="DEU",
                help="Dreistelliger Ländercode, z. B. DEU, AUT.",
            ),
            ConfigField("tage", "Zeitraum (Tage)", kind="number", default=30),
            ConfigField("anzahl", "Maximale Anzahl", kind="number", default=100),
        ]

    async def fetch_items(self, config: dict[str, Any]) -> AsyncIterator[FetchedItem]:
        cpv = config.get("cpv") or DEFAULT_CPV
        land = (config.get("land") or "DEU").strip() or "DEU"
        tage = int(config.get("tage") or 30)
        anzahl = int(config.get("anzahl") or 100)
        query = (
            f"(place-of-performance IN ({land})) "
            f"AND (publication-date >= today(-{tage})) "
            f"AND (classification-cpv IN ({' '.join(cpv)}))"
        )
        headers = {"Content-Type": "application/json", "Accept": "application/json"}

        async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
            collected = 0
            page = 1
            while collected < anzahl:
                limit = min(PAGE_LIMIT, anzahl - collected)
                body = {
                    "query": query,
                    "fields": _FIELDS,
                    "limit": limit,
                    "page": page,
                    "scope": "ALL",
                }
                response = await client.post(API_URL, json=body, headers=headers)
                response.raise_for_status()
                notices = response.json().get("notices", [])
                if not notices:
                    break

                for notice in notices:
                    collected += 1
                    nr = _text(notice.get("publication-number")) or f"seite-{collected}"
                    pdf_url = _pdf_url(notice)
                    if not pdf_url:
                        continue
                    try:
                        pdf = await client.get(pdf_url, headers={"User-Agent": "Mozilla/5.0"})
                        pdf.raise_for_status()
                    except httpx.HTTPError as exc:
                        logger.warning("TED-PDF-Download fehlgeschlagen (%s): %s", nr, exc)
                        continue
                    # Bevorzugt auf die vollständigen Vergabeunterlagen verlinken,
                    # sonst auf die TED-Bekanntmachung.
                    source_url = _documents_url(notice) or DETAIL_URL.format(nr=nr)
                    yield FetchedItem(
                        external_id=nr,
                        filename=f"{_safe_name(nr)}.pdf",
                        data=pdf.content,
                        content_type="application/pdf",
                        source_url=source_url,
                    )
                    await asyncio.sleep(0.2)  # höflich zur API
                page += 1


register(TedConnector())
