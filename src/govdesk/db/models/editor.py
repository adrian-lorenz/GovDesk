# SPDX-FileCopyrightText: 2026 GovDesk-Mitwirkende
#
# SPDX-License-Identifier: EUPL-1.2

"""Kollaborative Editor-Dokumente (gemeinsames Schreiben mit Historie).

Bewusst schlank: der Inhalt ist Markdown/Text, jede Speicherung erzeugt eine
Revision (Volltext-Schnappschuss) für die Historie „wer hat wann was geändert".
Synchronisation läuft über Long-Polling gegen den `version`-Zähler; parallele
Speicherungen werden optimistisch über die Version abgesichert.
"""

import uuid

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from govdesk.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class EditorFolder(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Ordner der Dokumentenbibliothek — beliebig schachtelbar je Projekt."""

    __tablename__ = "editor_folders"

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    # Wurzelordner haben parent_id NULL. Löschen eines Ordners hebt die
    # Verschachtelung auf Datenbankebene nicht kaskadierend auf — der Service
    # verschiebt Inhalte vorher in den Elternordner.
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("editor_folders.id", ondelete="CASCADE"), index=True
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )


class EditorDocument(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "editor_documents"

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    # NULL = liegt auf oberster Ebene der Bibliothek.
    folder_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("editor_folders.id", ondelete="SET NULL"), index=True
    )
    title: Mapped[str] = mapped_column(String(300))
    content: Mapped[str] = mapped_column(Text, default="")
    # Privat = nur für den Ersteller sichtbar; sonst für alle Projekt-Mitglieder.
    is_private: Mapped[bool] = mapped_column(default=False)
    # Monoton steigender Änderungszähler — Basis für Long-Poll und Konfliktprüfung.
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )


class EditorRevision(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Volltext-Schnappschuss einer Speicherung — für die Änderungshistorie."""

    __tablename__ = "editor_revisions"

    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("editor_documents.id", ondelete="CASCADE"), index=True
    )
    version: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    author_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
