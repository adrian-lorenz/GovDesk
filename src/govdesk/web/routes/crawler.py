# SPDX-FileCopyrightText: 2026 GovDesk-Mitwirkende
#
# SPDX-License-Identifier: EUPL-1.2

"""Crawler-UI: Web-Quellen verwalten, Crawls starten/stoppen, Status verfolgen."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select

from govdesk.agents.crawler.service import delete_source_full, list_sources_with_jobs
from govdesk.auth.deps import CurrentUser, Db, ProjectEditor
from govdesk.core.audit import audit
from govdesk.db.models import (
    Collection,
    CrawlJob,
    CrawlJobStatus,
    CrawlMode,
    CrawlSource,
)
from govdesk.web.deps import render
from govdesk.web.project_layout import project_menu_context

router = APIRouter()


@router.get("/projects/{project_id}/crawler", response_class=HTMLResponse)
async def crawler_page(
    request: Request, project: ProjectEditor, user: CurrentUser, db: Db
) -> HTMLResponse:
    collections = (
        (
            await db.execute(
                select(Collection)
                .where(Collection.project_id == project.id)
                .order_by(Collection.name)
            )
        )
        .scalars()
        .all()
    )
    ctx = await project_menu_context(db, project, user, "crawler")
    return render(
        request,
        "projects/crawler.html",
        {**ctx, "rows": await list_sources_with_jobs(db, project.id), "collections": collections},
    )


@router.post("/projects/{project_id}/crawler")
async def source_create(
    project: ProjectEditor,
    user: CurrentUser,
    db: Db,
    name: Annotated[str, Form()],
    start_url: Annotated[str, Form()],
    topic: Annotated[str, Form()] = "",
    follow_subpages: Annotated[bool, Form()] = False,
    max_depth: Annotated[int, Form()] = 2,
    max_pages: Annotated[int, Form()] = 50,
    url_include_pattern: Annotated[str, Form()] = "",
    url_exclude_pattern: Annotated[str, Form()] = "",
    recrawl_interval_hours: Annotated[int, Form()] = 0,
    collection_id: Annotated[str, Form()] = "",
) -> RedirectResponse:
    if not start_url.startswith(("http://", "https://")):
        raise HTTPException(status_code=422, detail="Start-URL muss mit http(s):// beginnen")
    topic = topic.strip()
    # Modus aus Häkchen + Thema ableiten: ohne Unterseiten → nur diese Seite;
    # mit Thema → LLM-geführter Agent; ohne Thema → klassisch rekursiv.
    if not follow_subpages:
        mode = CrawlMode.SINGLE
    elif topic:
        mode = CrawlMode.AGENT
    else:
        mode = CrawlMode.RECURSIVE
    source = CrawlSource(
        project_id=project.id,
        collection_id=uuid.UUID(collection_id) if collection_id else None,
        name=name.strip(),
        start_url=start_url.strip(),
        topic=topic or None,
        mode=mode,
        max_depth=max(0, min(max_depth, 5)),
        max_pages=max(1, min(max_pages, 500)),
        url_include_pattern=url_include_pattern.strip() or None,
        url_exclude_pattern=url_exclude_pattern.strip() or None,
        recrawl_interval_hours=recrawl_interval_hours or None,
    )
    db.add(source)
    await db.flush()
    await audit(
        db,
        "crawl_source.create",
        actor_user_id=user.id,
        project_id=project.id,
        target_type="crawl_source",
        target_id=str(source.id),
        meta={"start_url": source.start_url, "mode": source.mode.value},
    )
    await db.commit()
    return await source_start(project, user, db, source.id)


async def _load_source(db: Db, project, source_id: uuid.UUID) -> CrawlSource:
    source = await db.get(CrawlSource, source_id)
    if source is None or source.project_id != project.id:
        raise HTTPException(status_code=404, detail="Quelle nicht gefunden")
    return source


@router.post("/projects/{project_id}/crawler/{source_id}/start")
async def source_start(
    project: ProjectEditor, user: CurrentUser, db: Db, source_id: uuid.UUID
) -> RedirectResponse:
    from govdesk.workers.tasks import crawl_source as crawl_task

    source = await _load_source(db, project, source_id)
    running = (
        await db.execute(
            select(CrawlJob).where(
                CrawlJob.crawl_source_id == source.id,
                CrawlJob.status.in_([CrawlJobStatus.QUEUED, CrawlJobStatus.RUNNING]),
            )
        )
    ).scalar_one_or_none()
    if running is None:
        job = CrawlJob(crawl_source_id=source.id)
        db.add(job)
        await db.flush()
        await audit(
            db,
            "crawl.start",
            actor_user_id=user.id,
            project_id=project.id,
            target_type="crawl_source",
            target_id=str(source.id),
        )
        await db.commit()
        await crawl_task.defer_async(job_id=str(job.id))
    return RedirectResponse(f"/projects/{project.id}/crawler", status_code=303)


@router.post("/projects/{project_id}/crawler/{source_id}/stop")
async def source_stop(
    project: ProjectEditor, user: CurrentUser, db: Db, source_id: uuid.UUID
) -> RedirectResponse:
    source = await _load_source(db, project, source_id)
    jobs = (
        (
            await db.execute(
                select(CrawlJob).where(
                    CrawlJob.crawl_source_id == source.id,
                    CrawlJob.status.in_([CrawlJobStatus.QUEUED, CrawlJobStatus.RUNNING]),
                )
            )
        )
        .scalars()
        .all()
    )
    for job in jobs:
        job.status = CrawlJobStatus.CANCELLED
    await db.commit()
    return RedirectResponse(f"/projects/{project.id}/crawler", status_code=303)


@router.post("/projects/{project_id}/crawler/{source_id}/loeschen")
async def source_delete(
    project: ProjectEditor, user: CurrentUser, db: Db, source_id: uuid.UUID
) -> RedirectResponse:
    source = await _load_source(db, project, source_id)
    await audit(
        db,
        "crawl_source.delete",
        actor_user_id=user.id,
        project_id=project.id,
        target_type="crawl_source",
        target_id=str(source.id),
        meta={"name": source.name},
    )
    await delete_source_full(db, project, source)  # inkl. erzeugter Dokumente + Vektoren
    await db.commit()
    return RedirectResponse(f"/projects/{project.id}/crawler", status_code=303)


@router.get("/projects/{project_id}/crawler/{source_id}/status", response_class=HTMLResponse)
async def source_status(
    request: Request, project: ProjectEditor, db: Db, source_id: uuid.UUID
) -> HTMLResponse:
    source = await _load_source(db, project, source_id)
    last_job = (
        await db.execute(
            select(CrawlJob)
            .where(CrawlJob.crawl_source_id == source.id)
            .order_by(CrawlJob.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    return render(
        request,
        "partials/_crawl_quelle.html",
        {"project": project, "row": {"source": source, "job": last_job}},
    )
