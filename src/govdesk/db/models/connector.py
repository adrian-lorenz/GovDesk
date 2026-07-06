# SPDX-FileCopyrightText: 2026 GovDesk-Mitwirkende
#
# SPDX-License-Identifier: EUPL-1.2

"""Generisches Connector-Datenmodell.

Ein Connector ist eine abschaltbare Quellen-Erweiterung (Plugin), die Dokumente
aus einer externen Quelle (z. B. der EU-Ausschreibungsdatenbank TED) in ein
Projekt einspeist. Anders als der Crawler mit eigenen Tabellen teilen sich alle
Connector-Typen dieses Modell; `connector_type` ist der Diskriminator und `config`
hält die typ-spezifischen Optionen als JSON. Die eigentliche Abruf-Logik lebt im
jeweiligen Plugin (siehe govdesk.connectors).
"""

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Enum, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from govdesk.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class ConnectorJobStatus(enum.StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ConnectorSource(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Eine konfigurierte Connector-Quelle eines Projekts."""

    __tablename__ = "connector_sources"

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    collection_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("collections.id", ondelete="SET NULL")
    )
    # Diskriminator — entspricht ConnectorPlugin.type_id in der Registry.
    connector_type: Mapped[str] = mapped_column(String(50), index=True)
    name: Mapped[str] = mapped_column(String(200))
    # Typ-spezifische Optionen (bei TED z. B. CPV-Codes, Zeitraum, Land).
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    # Wiederkehrende Synchronisation (NULL = nur manuell auslösen).
    sync_interval_hours: Mapped[int | None]
    enabled: Mapped[bool] = mapped_column(default=True)


class ConnectorJob(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "connector_jobs"

    connector_source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("connector_sources.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[ConnectorJobStatus] = mapped_column(
        Enum(
            ConnectorJobStatus,
            name="connector_job_status",
            values_callable=lambda e: [m.value for m in e],
        ),
        default=ConnectorJobStatus.QUEUED,
    )
    started_at: Mapped[datetime | None]
    finished_at: Mapped[datetime | None]
    items_found: Mapped[int] = mapped_column(default=0)
    items_ingested: Mapped[int] = mapped_column(default=0)
    items_skipped: Mapped[int] = mapped_column(default=0)
    error: Mapped[str | None] = mapped_column(Text)


class ConnectorItem(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Bekanntes Quell-Item — mit Content-Hash für Delta-Erkennung (Skip-if-unchanged)."""

    __tablename__ = "connector_items"
    __table_args__ = (UniqueConstraint("connector_source_id", "external_id"),)

    connector_source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("connector_sources.id", ondelete="CASCADE"), index=True
    )
    # Stabile ID beim Anbieter (bei TED z. B. die publication-number).
    external_id: Mapped[str] = mapped_column(String(200))
    content_hash: Mapped[str | None] = mapped_column(String(64))
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL")
    )
    last_seen_at: Mapped[datetime | None]
