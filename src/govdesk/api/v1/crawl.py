# SPDX-FileCopyrightText: 2026 GovDesk-Mitwirkende
#
# SPDX-License-Identifier: EUPL-1.2

"""REST-API: einzelne URL crawlen und einbetten."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, HttpUrl
from sqlalchemy.ext.asyncio import AsyncSession

from govdesk.auth.apikey import ApiProject, require_api_key
from govdesk.core.audit import audit
from govdesk.db.models import ApiKey, CrawlJob, CrawlMode, CrawlSource
from govdesk.db.session import get_db

router = APIRouter(prefix="/crawl", tags=["Crawler"])

Db = Annotated[AsyncSession, Depends(get_db)]
CrawlKey = Annotated[ApiKey, Depends(require_api_key("crawl:write"))]


class CrawlRequest(BaseModel):
    url: HttpUrl = Field(description="URL der einzubettenden Seite")
    name: str | None = Field(default=None, max_length=200)


class CrawlJobOut(BaseModel):
    job_id: uuid.UUID
    source_id: uuid.UUID
    status: str


@router.post("", response_model=CrawlJobOut, status_code=202, summary="Einzelne URL einbetten")
async def api_crawl_url(
    project: ApiProject, key: CrawlKey, db: Db, body: CrawlRequest
) -> CrawlJobOut:
    from govdesk.workers.tasks import crawl_source as crawl_task

    source = CrawlSource(
        project_id=project.id,
        name=body.name or str(body.url)[:200],
        start_url=str(body.url),
        mode=CrawlMode.SINGLE,
    )
    db.add(source)
    await db.flush()
    job = CrawlJob(crawl_source_id=source.id)
    db.add(job)
    await db.flush()
    await audit(
        db,
        "crawl.start",
        actor_api_key_id=key.id,
        project_id=project.id,
        target_type="crawl_source",
        target_id=str(source.id),
        meta={"url": str(body.url), "via": "api"},
    )
    await db.commit()
    await crawl_task.defer_async(job_id=str(job.id))
    return CrawlJobOut(job_id=job.id, source_id=source.id, status="queued")


@router.get("/{job_id}", response_model=CrawlJobOut, summary="Crawl-Status abfragen")
async def api_crawl_status(
    project: ApiProject, key: CrawlKey, db: Db, job_id: uuid.UUID
) -> CrawlJobOut:
    job = await db.get(CrawlJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job nicht gefunden")
    source = await db.get(CrawlSource, job.crawl_source_id)
    if source is None or source.project_id != project.id:
        raise HTTPException(status_code=404, detail="Job nicht gefunden")
    return CrawlJobOut(job_id=job.id, source_id=source.id, status=job.status.value)
