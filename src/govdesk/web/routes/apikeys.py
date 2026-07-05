# SPDX-FileCopyrightText: 2026 GovDesk-Mitwirkende
#
# SPDX-License-Identifier: EUPL-1.2

"""API-Key-Verwaltung pro Projekt (nur Projekt-Admins)."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select

from govdesk.auth.deps import CurrentUser, Db, ProjectAdmin
from govdesk.core.audit import audit
from govdesk.core.security import new_api_key
from govdesk.db.models import API_SCOPES, ApiKey
from govdesk.web.deps import render

router = APIRouter()


async def _keys(db: Db, project) -> list[ApiKey]:
    result = await db.execute(
        select(ApiKey).where(ApiKey.project_id == project.id).order_by(ApiKey.created_at.desc())
    )
    return list(result.scalars())


@router.get("/projects/{project_id}/api-keys", response_class=HTMLResponse)
async def key_list(request: Request, project: ProjectAdmin, db: Db) -> HTMLResponse:
    return render(
        request,
        "projects/api_keys.html",
        {"project": project, "keys": await _keys(db, project), "scopes": API_SCOPES},
    )


@router.post("/projects/{project_id}/api-keys", response_class=HTMLResponse)
async def key_create(
    request: Request,
    project: ProjectAdmin,
    user: CurrentUser,
    db: Db,
    name: Annotated[str, Form()],
    gueltig_tage: Annotated[int, Form()] = 0,
) -> HTMLResponse:
    form = await request.form()
    scopes = [s for s in form.getlist("scopes") if isinstance(s, str) and s in API_SCOPES]
    if not scopes:
        raise HTTPException(status_code=422, detail="Mindestens ein Scope erforderlich")

    full_key, prefix, key_hash = new_api_key()
    api_key = ApiKey(
        project_id=project.id,
        name=name.strip(),
        key_prefix=prefix,
        key_hash=key_hash,
        scopes=scopes,
        created_by=user.id,
        expires_at=(datetime.now(UTC) + timedelta(days=gueltig_tage) if gueltig_tage > 0 else None),
    )
    db.add(api_key)
    await audit(
        db,
        "apikey.create",
        actor_user_id=user.id,
        project_id=project.id,
        target_type="api_key",
        meta={"name": name.strip(), "scopes": scopes},
    )
    await db.commit()
    # Klartext-Key genau einmal anzeigen
    return render(
        request,
        "projects/api_keys.html",
        {
            "project": project,
            "keys": await _keys(db, project),
            "scopes": API_SCOPES,
            "neuer_key": full_key,
            "neuer_key_name": name.strip(),
        },
    )


@router.post("/projects/{project_id}/api-keys/{key_id}/widerrufen")
async def key_revoke(
    project: ProjectAdmin, user: CurrentUser, db: Db, key_id: uuid.UUID
) -> RedirectResponse:
    api_key = await db.get(ApiKey, key_id)
    if api_key is None or api_key.project_id != project.id:
        raise HTTPException(status_code=404, detail="API-Key nicht gefunden")
    api_key.revoked_at = datetime.now(UTC)
    await audit(
        db,
        "apikey.revoke",
        actor_user_id=user.id,
        project_id=project.id,
        target_type="api_key",
        target_id=str(api_key.id),
        meta={"name": api_key.name},
    )
    await db.commit()
    return RedirectResponse(f"/projects/{project.id}/api-keys", status_code=303)
