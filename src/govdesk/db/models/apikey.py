# SPDX-FileCopyrightText: 2026 GovDesk-Mitwirkende
#
# SPDX-License-Identifier: EUPL-1.2

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, String
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from govdesk.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

# Verfügbare Scopes für API-Keys
API_SCOPES = {
    "documents:read": "Dokumente und Status lesen",
    "documents:write": "Dokumente hochladen und löschen",
    "search:read": "Retrieval-Suche ausführen",
    "crawl:write": "Webseiten crawlen und einbetten",
}


class ApiKey(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Projekt-gebundener API-Key. Es wird nur der SHA-256-Hash gespeichert;
    der Klartext-Schlüssel ist ausschließlich bei der Erzeugung sichtbar."""

    __tablename__ = "api_keys"

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(150))
    key_prefix: Mapped[str] = mapped_column(String(20), index=True)
    key_hash: Mapped[str] = mapped_column(String(64), unique=True)
    scopes: Mapped[list[str]] = mapped_column(ARRAY(String(40)))
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    expires_at: Mapped[datetime | None]
    last_used_at: Mapped[datetime | None]
    revoked_at: Mapped[datetime | None]
