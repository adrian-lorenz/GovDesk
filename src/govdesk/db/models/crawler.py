# SPDX-FileCopyrightText: 2026 GovDesk-Mitwirkende
#
# SPDX-License-Identifier: EUPL-1.2

import enum
import uuid
from datetime import datetime

from sqlalchemy import Enum, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from govdesk.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class CrawlMode(enum.StrEnum):
    SINGLE = "single"
    RECURSIVE = "recursive"
    AGENT = "agent"


class CrawlJobStatus(enum.StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


class CrawlSource(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Eine Web-Quelle (einzelne Seite oder rekursiver Crawl) eines Projekts."""

    __tablename__ = "crawl_sources"

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    collection_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("collections.id", ondelete="SET NULL")
    )
    name: Mapped[str] = mapped_column(String(200))
    start_url: Mapped[str] = mapped_column(Text)
    # Suchauftrag in Worten (nur Agent-Modus): steuert LLM-Relevanz + Linkauswahl.
    topic: Mapped[str | None] = mapped_column(Text)
    mode: Mapped[CrawlMode] = mapped_column(
        Enum(CrawlMode, name="crawl_mode", values_callable=lambda e: [m.value for m in e]),
        default=CrawlMode.SINGLE,
    )
    max_depth: Mapped[int] = mapped_column(default=2)
    max_pages: Mapped[int] = mapped_column(default=50)
    # Leer = nur die Domain der Start-URL
    allowed_domains: Mapped[list[str] | None] = mapped_column(ARRAY(String(255)))
    url_include_pattern: Mapped[str | None] = mapped_column(String(500))
    url_exclude_pattern: Mapped[str | None] = mapped_column(String(500))
    recrawl_interval_hours: Mapped[int | None]
    enabled: Mapped[bool] = mapped_column(default=True)


class CrawlJob(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "crawl_jobs"

    crawl_source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("crawl_sources.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[CrawlJobStatus] = mapped_column(
        Enum(
            CrawlJobStatus,
            name="crawl_job_status",
            values_callable=lambda e: [m.value for m in e],
        ),
        default=CrawlJobStatus.QUEUED,
    )
    started_at: Mapped[datetime | None]
    finished_at: Mapped[datetime | None]
    pages_fetched: Mapped[int] = mapped_column(default=0)
    pages_ingested: Mapped[int] = mapped_column(default=0)
    pages_skipped: Mapped[int] = mapped_column(default=0)
    error: Mapped[str | None] = mapped_column(Text)


class CrawlPage(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Bekannte URL einer Quelle — mit Content-Hash für Change-Detection."""

    __tablename__ = "crawl_pages"
    __table_args__ = (UniqueConstraint("crawl_source_id", "url_hash"),)

    crawl_source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("crawl_sources.id", ondelete="CASCADE"), index=True
    )
    url: Mapped[str] = mapped_column(Text)
    url_hash: Mapped[str] = mapped_column(String(64))
    content_hash: Mapped[str | None] = mapped_column(String(64))
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL")
    )
    last_fetched_at: Mapped[datetime | None]
    http_status: Mapped[int | None]
