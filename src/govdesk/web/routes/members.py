# SPDX-FileCopyrightText: 2026 GovDesk-Mitwirkende
#
# SPDX-License-Identifier: EUPL-1.2

"""Mitgliederverwaltung pro Projekt."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select

from govdesk.auth.deps import CurrentUser, Db, ProjectAdmin
from govdesk.core.audit import audit
from govdesk.db.models import ProjectMember, ProjectRole, User

router = APIRouter()

# Rollen, die per UI vergeben werden können (owner nur durch Projektanlage)
ASSIGNABLE_ROLES = (ProjectRole.ADMIN, ProjectRole.EDITOR, ProjectRole.VIEWER)


@router.post("/projects/{project_id}/members")
async def member_add(
    request: Request,
    project: ProjectAdmin,
    user: CurrentUser,
    db: Db,
    username: Annotated[str, Form()],
    role: Annotated[ProjectRole, Form()],
) -> RedirectResponse:
    if role not in ASSIGNABLE_ROLES:
        raise HTTPException(status_code=422, detail="Diese Rolle kann nicht vergeben werden")
    target = (
        await db.execute(select(User).where(User.username == username.strip()))
    ).scalar_one_or_none()
    if target is None or not target.is_active:
        raise HTTPException(status_code=404, detail=f"Nutzer „{username}“ nicht gefunden")
    existing = (
        await db.execute(
            select(ProjectMember).where(
                ProjectMember.project_id == project.id, ProjectMember.user_id == target.id
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=409, detail="Nutzer ist bereits Mitglied")
    db.add(ProjectMember(project_id=project.id, user_id=target.id, role=role))
    await audit(
        db,
        "member.add",
        actor_user_id=user.id,
        project_id=project.id,
        target_type="user",
        target_id=str(target.id),
        meta={"role": role.value},
    )
    await db.commit()
    return RedirectResponse(f"/projects/{project.id}", status_code=303)


async def _load_member(db: Db, project, member_id: uuid.UUID) -> ProjectMember:
    member = await db.get(ProjectMember, member_id)
    if member is None or member.project_id != project.id:
        raise HTTPException(status_code=404, detail="Mitglied nicht gefunden")
    if member.role == ProjectRole.OWNER:
        raise HTTPException(status_code=400, detail="Eigentümer kann nicht geändert werden")
    return member


@router.post("/projects/{project_id}/members/{member_id}/role")
async def member_change_role(
    project: ProjectAdmin,
    user: CurrentUser,
    db: Db,
    member_id: uuid.UUID,
    role: Annotated[ProjectRole, Form()],
) -> RedirectResponse:
    if role not in ASSIGNABLE_ROLES:
        raise HTTPException(status_code=422, detail="Diese Rolle kann nicht vergeben werden")
    member = await _load_member(db, project, member_id)
    member.role = role
    await audit(
        db,
        "member.change_role",
        actor_user_id=user.id,
        project_id=project.id,
        target_type="user",
        target_id=str(member.user_id),
        meta={"role": role.value},
    )
    await db.commit()
    return RedirectResponse(f"/projects/{project.id}", status_code=303)


@router.post("/projects/{project_id}/members/{member_id}/entfernen")
async def member_remove(
    project: ProjectAdmin, user: CurrentUser, db: Db, member_id: uuid.UUID
) -> RedirectResponse:
    member = await _load_member(db, project, member_id)
    await audit(
        db,
        "member.remove",
        actor_user_id=user.id,
        project_id=project.id,
        target_type="user",
        target_id=str(member.user_id),
    )
    await db.delete(member)
    await db.commit()
    return RedirectResponse(f"/projects/{project.id}", status_code=303)
