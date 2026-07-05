# SPDX-FileCopyrightText: 2026 GovDesk-Mitwirkende
#
# SPDX-License-Identifier: EUPL-1.2

import enum
import uuid

from sqlalchemy import BigInteger, Enum, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from govdesk.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class DocumentSource(enum.StrEnum):
    UPLOAD = "upload"
    API = "api"
    CRAWLER = "crawler"


class DocumentStatus(enum.StrEnum):
    PENDING = "pending"
    PARSING = "parsing"
    CHUNKING = "chunking"
    EMBEDDING = "embedding"
    READY = "ready"
    FAILED = "failed"


class Collection(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Logische Gruppierung von Dokumenten innerhalb eines Projekts
    (z. B. „Gesetze", „interne Richtlinien") — filterbar pro Chat."""

    __tablename__ = "collections"
    __table_args__ = (UniqueConstraint("project_id", "name"),)

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(150))
    description: Mapped[str | None] = mapped_column(Text)


class Document(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "documents"
    __table_args__ = (UniqueConstraint("project_id", "sha256"),)

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    collection_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("collections.id", ondelete="SET NULL")
    )
    filename: Mapped[str] = mapped_column(String(400))
    content_type: Mapped[str | None] = mapped_column(String(150))
    source_type: Mapped[DocumentSource] = mapped_column(
        Enum(
            DocumentSource,
            name="document_source",
            values_callable=lambda e: [m.value for m in e],
        ),
        default=DocumentSource.UPLOAD,
    )
    source_url: Mapped[str | None] = mapped_column(Text)
    file_path: Mapped[str | None] = mapped_column(Text)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    sha256: Mapped[str] = mapped_column(String(64))
    status: Mapped[DocumentStatus] = mapped_column(
        Enum(
            DocumentStatus,
            name="document_status",
            values_callable=lambda e: [m.value for m in e],
        ),
        default=DocumentStatus.PENDING,
    )
    error: Mapped[str | None] = mapped_column(Text)
    chunk_count: Mapped[int] = mapped_column(default=0)

    chunks: Mapped[list[DocumentChunk]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )


class DocumentChunk(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Chunk-Text in Postgres = Source of Truth; Qdrant ist jederzeit rebuildbar."""

    __tablename__ = "document_chunks"
    __table_args__ = (UniqueConstraint("document_id", "chunk_index"),)

    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    chunk_index: Mapped[int]
    text: Mapped[str] = mapped_column(Text)
    token_count: Mapped[int | None]
    heading_path: Mapped[str | None] = mapped_column(Text)
    page_no: Mapped[int | None]
    qdrant_point_id: Mapped[uuid.UUID]

    document: Mapped[Document] = relationship(back_populates="chunks")
