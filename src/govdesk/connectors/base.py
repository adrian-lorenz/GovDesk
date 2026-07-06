# SPDX-FileCopyrightText: 2026 GovDesk-Mitwirkende
#
# SPDX-License-Identifier: EUPL-1.2

"""Vertrag für Quellen-Connectoren.

Ein Connector kapselt „woher kommen die Rohdokumente". Alles danach — Delta-
Erkennung, `create_document`, Einreihen in die Ingestion-Pipeline, Job-Status —
erledigt der generische Worker (Phase 2). Ein Connector muss also nur:

  1. sich beschreiben (`type_id`, `label`, `description`),
  2. sein Konfigurationsformular deklarieren (`config_fields`) und
  3. für eine gegebene Konfiguration die zu importierenden Items liefern
     (`fetch_items`) — als async-Generator, damit große Bestände streamend
     verarbeitet werden.
"""

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class ConfigField:
    """Deklaratives Formularfeld für die Connector-Konfiguration (UI + Validierung)."""

    key: str
    label: str
    kind: str = "text"  # "text" | "number" | "list" | "select" | "bool"
    default: Any = None
    required: bool = False
    help: str | None = None
    # Nur bei kind == "select": erlaubte (Wert, Anzeigetext)-Paare.
    choices: list[tuple[str, str]] = field(default_factory=list)


@dataclass(frozen=True)
class FetchedItem:
    """Ein abrufbereites Rohdokument, das der Worker in die Pipeline gibt."""

    external_id: str  # stabile Anbieter-ID (Delta-Erkennung)
    filename: str
    data: bytes
    content_type: str
    source_url: str | None = None
    # Optionaler Hash zur Delta-Erkennung; None → Worker hasht `data` selbst.
    content_hash: str | None = None


@runtime_checkable
class ConnectorPlugin(Protocol):
    """Protokoll, das jeder Connector erfüllt. Instanzen werden in der Registry gehalten."""

    #: Eindeutiger, stabiler Typ-Schlüssel (== ConnectorSource.connector_type).
    type_id: str
    #: Menschlicher Name für die UI.
    label: str
    #: Kurzbeschreibung für die UI.
    description: str

    def config_fields(self) -> list[ConfigField]:
        """Deklariert die Konfigurationsfelder dieses Connectors."""
        ...

    def fetch_items(self, config: dict[str, Any]) -> AsyncIterator[FetchedItem]:
        """Liefert die zu importierenden Items für die gegebene Konfiguration.

        Implementierungen sind `async def` mit `yield` (async-Generator).
        """
        ...
