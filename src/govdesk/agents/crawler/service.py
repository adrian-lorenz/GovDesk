# SPDX-FileCopyrightText: 2026 GovDesk-Mitwirkende
#
# SPDX-License-Identifier: EUPL-1.2

"""Crawler-Abfragen und -Verwaltung, geteilt von Dashboard und Crawler-Seite."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from govdesk.db.models import CrawlJob, CrawlPage, CrawlSource, Document, Project
from govdesk.documents.service import delete_document_full


async def list_sources_with_jobs(db: AsyncSession, project_id: uuid.UUID) -> list[dict]:
    """Web-Quellen eines Projekts mit ihrem jeweils jüngsten Job."""
    sources = (
        (
            await db.execute(
                select(CrawlSource)
                .where(CrawlSource.project_id == project_id)
                .order_by(CrawlSource.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    rows = []
    for source in sources:
        last_job = (
            await db.execute(
                select(CrawlJob)
                .where(CrawlJob.crawl_source_id == source.id)
                .order_by(CrawlJob.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        rows.append({"source": source, "job": last_job})
    return rows


async def delete_source_full(db: AsyncSession, project: Project, source: CrawlSource) -> None:
    """Löscht eine Quelle samt aller daraus erzeugten Dokumente (Qdrant + Datei
    + DB-Zeile). Dokumente zuerst — danach kaskadieren Jobs und Pages."""
    document_ids = (
        (
            await db.execute(
                select(CrawlPage.document_id).where(
                    CrawlPage.crawl_source_id == source.id,
                    CrawlPage.document_id.is_not(None),
                )
            )
        )
        .scalars()
        .all()
    )
    for document_id in set(document_ids):
        document = await db.get(Document, document_id)
        if document is not None:
            await delete_document_full(db, project, document)
    await db.delete(source)
