# SPDX-FileCopyrightText: 2026 GovDesk-Mitwirkende
#
# SPDX-License-Identifier: EUPL-1.2

"""Auth-Dependencies für Web-Routen."""

import uuid
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from govdesk.db.models import ROLE_ORDER, Project, ProjectMember, ProjectRole, User
from govdesk.db.session import get_db


def get_current_user(request: Request) -> User:
    user = getattr(request.state, "user", None)
    if user is None:
        # 303 mit Location: Browser und HTMX landen auf der Login-Seite
        raise HTTPException(status_code=303, headers={"Location": "/login"})
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
Db = Annotated[AsyncSession, Depends(get_db)]


def require_platform_admin(user: CurrentUser) -> User:
    if not user.is_platform_admin:
        raise HTTPException(status_code=403, detail="Nur für Plattform-Administratoren")
    return user


PlatformAdmin = Annotated[User, Depends(require_platform_admin)]


class ProjectAccess:
    """Lädt das Projekt und erzwingt eine Mindestrolle des angemeldeten Nutzers."""

    def __init__(self, min_role: ProjectRole) -> None:
        self.min_role = min_role

    async def __call__(self, project_id: uuid.UUID, user: CurrentUser, db: Db) -> Project:
        project = await db.get(Project, project_id)
        # Archivierte Projekte sind für die normale Nutzung unsichtbar —
        # Verwaltung läuft über den Archiv-Bereich (Plattform-Admin).
        if project is None or project.is_archived:
            raise HTTPException(status_code=404, detail="Projekt nicht gefunden")
        if user.is_platform_admin:
            return project
        result = await db.execute(
            select(ProjectMember.role).where(
                ProjectMember.project_id == project.id,
                ProjectMember.user_id == user.id,
            )
        )
        role = result.scalar_one_or_none()
        if role is None or ROLE_ORDER[role] < ROLE_ORDER[self.min_role]:
            raise HTTPException(status_code=403, detail="Keine Berechtigung in diesem Projekt")
        return project


async def has_min_role(
    db: AsyncSession, project: Project, user: User, min_role: ProjectRole
) -> bool:
    if user.is_platform_admin:
        return True
    result = await db.execute(
        select(ProjectMember.role).where(
            ProjectMember.project_id == project.id, ProjectMember.user_id == user.id
        )
    )
    role = result.scalar_one_or_none()
    return role is not None and ROLE_ORDER[role] >= ROLE_ORDER[min_role]


ProjectViewer = Annotated[Project, Depends(ProjectAccess(ProjectRole.VIEWER))]
ProjectEditor = Annotated[Project, Depends(ProjectAccess(ProjectRole.EDITOR))]
ProjectAdmin = Annotated[Project, Depends(ProjectAccess(ProjectRole.ADMIN))]
ProjectOwner = Annotated[Project, Depends(ProjectAccess(ProjectRole.OWNER))]
