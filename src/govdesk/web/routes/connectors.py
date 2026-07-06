# SPDX-FileCopyrightText: 2026 GovDesk-Mitwirkende
#
# SPDX-License-Identifier: EUPL-1.2

"""Connector-UI: Quellen verwalten, Läufe starten/stoppen, Status verfolgen."""

import re
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select

from govdesk.auth.deps import CurrentUser, Db, ProjectEditor
from govdesk.connectors.base import ConfigField, ConnectorPlugin
from govdesk.connectors.service import (
    available_connectors,
    delete_source_full,
    list_sources_with_jobs,
)
from govdesk.core.audit import audit
from govdesk.db.models import Collection, ConnectorJob, ConnectorJobStatus, ConnectorSource
from govdesk.web.deps import render
from govdesk.web.project_layout import ensure_section_visible, project_menu_context

router = APIRouter()


def _coerce(field: ConfigField, raw: Any) -> Any:
    """Formularwert gemäß Felddeklaration in den Zieltyp überführen."""
    if field.kind == "bool":
        return raw is not None
    if not isinstance(raw, str) or not raw.strip():
        return field.default
    value = raw.strip()
    if field.kind == "number":
        try:
            return int(value)
        except ValueError:
            return field.default
    if field.kind == "list":
        return [x.strip() for x in re.split(r"[\n,]", value) if x.strip()]
    return value


@router.get("/projects/{project_id}/connectors", response_class=HTMLResponse)
async def connectors_page(
    request: Request, project: ProjectEditor, user: CurrentUser, db: Db
) -> HTMLResponse:
    await ensure_section_visible(db, project, user, "connectors")
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
    ctx = await project_menu_context(db, project, user, "connectors")
    return render(
        request,
        "projects/connectors.html",
        {
            **ctx,
            "rows": await list_sources_with_jobs(db, project.id),
            "collections": collections,
            "available": await available_connectors(db),
        },
    )


@router.post("/projects/{project_id}/connectors")
async def source_create(
    request: Request,
    project: ProjectEditor,
    user: CurrentUser,
    db: Db,
    connector_type: Annotated[str, Form()],
    name: Annotated[str, Form()],
    collection_id: Annotated[str, Form()] = "",
    sync_interval_hours: Annotated[int, Form()] = 0,
) -> RedirectResponse:
    plugin: ConnectorPlugin | None = next(
        (c for c in await available_connectors(db) if c.type_id == connector_type), None
    )
    if plugin is None:
        raise HTTPException(status_code=422, detail="Connector nicht verfügbar")

    form = await request.form()
    config: dict[str, Any] = {}
    for f in plugin.config_fields():
        if f.kind == "checkboxes":
            config[f.key] = form.getlist(f"config_{f.key}")
        else:
            config[f.key] = _coerce(f, form.get(f"config_{f.key}"))

    source = ConnectorSource(
        project_id=project.id,
        collection_id=uuid.UUID(collection_id) if collection_id else None,
        connector_type=connector_type,
        name=name.strip(),
        config=config,
        sync_interval_hours=sync_interval_hours or None,
    )
    db.add(source)
    await db.flush()
    await audit(
        db,
        "connector_source.create",
        actor_user_id=user.id,
        project_id=project.id,
        target_type="connector_source",
        target_id=str(source.id),
        meta={"connector_type": connector_type},
    )
    await db.commit()
    return await source_start(project, user, db, source.id)


async def _load_source(db: Db, project, source_id: uuid.UUID) -> ConnectorSource:
    source = await db.get(ConnectorSource, source_id)
    if source is None or source.project_id != project.id:
        raise HTTPException(status_code=404, detail="Quelle nicht gefunden")
    return source


@router.post("/projects/{project_id}/connectors/{source_id}/start")
async def source_start(
    project: ProjectEditor, user: CurrentUser, db: Db, source_id: uuid.UUID
) -> RedirectResponse:
    from govdesk.workers.tasks import run_connector_job

    source = await _load_source(db, project, source_id)
    running = (
        await db.execute(
            select(ConnectorJob).where(
                ConnectorJob.connector_source_id == source.id,
                ConnectorJob.status.in_([ConnectorJobStatus.QUEUED, ConnectorJobStatus.RUNNING]),
            )
        )
    ).scalar_one_or_none()
    if running is None:
        job = ConnectorJob(connector_source_id=source.id)
        db.add(job)
        await db.flush()
        await audit(
            db,
            "connector.start",
            actor_user_id=user.id,
            project_id=project.id,
            target_type="connector_source",
            target_id=str(source.id),
        )
        await db.commit()
        await run_connector_job.defer_async(job_id=str(job.id))
    return RedirectResponse(f"/projects/{project.id}/connectors", status_code=303)


@router.post("/projects/{project_id}/connectors/{source_id}/stop")
async def source_stop(
    project: ProjectEditor, user: CurrentUser, db: Db, source_id: uuid.UUID
) -> RedirectResponse:
    source = await _load_source(db, project, source_id)
    jobs = (
        (
            await db.execute(
                select(ConnectorJob).where(
                    ConnectorJob.connector_source_id == source.id,
                    ConnectorJob.status.in_(
                        [ConnectorJobStatus.QUEUED, ConnectorJobStatus.RUNNING]
                    ),
                )
            )
        )
        .scalars()
        .all()
    )
    for job in jobs:
        job.status = ConnectorJobStatus.CANCELLED
    await db.commit()
    return RedirectResponse(f"/projects/{project.id}/connectors", status_code=303)


@router.post("/projects/{project_id}/connectors/{source_id}/loeschen")
async def source_delete(
    project: ProjectEditor, user: CurrentUser, db: Db, source_id: uuid.UUID
) -> RedirectResponse:
    source = await _load_source(db, project, source_id)
    await audit(
        db,
        "connector_source.delete",
        actor_user_id=user.id,
        project_id=project.id,
        target_type="connector_source",
        target_id=str(source.id),
        meta={"name": source.name},
    )
    await delete_source_full(db, project, source)  # inkl. erzeugter Dokumente + Vektoren
    await db.commit()
    return RedirectResponse(f"/projects/{project.id}/connectors", status_code=303)


@router.get("/projects/{project_id}/connectors/{source_id}/status", response_class=HTMLResponse)
async def source_status(
    request: Request, project: ProjectEditor, db: Db, source_id: uuid.UUID
) -> HTMLResponse:
    source = await _load_source(db, project, source_id)
    last_job = (
        await db.execute(
            select(ConnectorJob)
            .where(ConnectorJob.connector_source_id == source.id)
            .order_by(ConnectorJob.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    return render(
        request,
        "partials/_connector_quelle.html",
        {"project": project, "row": {"source": source, "job": last_job}},
    )
