# SPDX-FileCopyrightText: 2026 GovDesk-Mitwirkende
#
# SPDX-License-Identifier: EUPL-1.2

from typing import Annotated

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, select

from govdesk.agents.crawler.service import list_sources_with_jobs
from govdesk.auth.deps import CurrentUser, Db, ProjectViewer
from govdesk.chat.service import chat_sessions_for_project
from govdesk.core.app_settings import get_runtime_config
from govdesk.core.audit import audit
from govdesk.core.config import get_settings
from govdesk.db.models import (
    ROLE_ORDER,
    ChatConfig,
    Collection,
    Document,
    ProjectMember,
    ProjectRole,
    User,
)
from govdesk.projects.service import create_project, projects_for_user
from govdesk.web.deps import render

router = APIRouter()


@router.get("/projects", response_class=HTMLResponse)
async def project_list(request: Request, user: CurrentUser, db: Db) -> HTMLResponse:
    projects = await projects_for_user(db, user)
    ids = [p.id for p in projects]
    doc_counts: dict = {}
    member_counts: dict = {}
    if ids:
        for pid, n in (
            await db.execute(
                select(Document.project_id, func.count())
                .where(Document.project_id.in_(ids))
                .group_by(Document.project_id)
            )
        ).all():
            doc_counts[pid] = n
        for pid, n in (
            await db.execute(
                select(ProjectMember.project_id, func.count())
                .where(ProjectMember.project_id.in_(ids))
                .group_by(ProjectMember.project_id)
            )
        ).all():
            member_counts[pid] = n
    items = [
        {
            "project": p,
            "documents": doc_counts.get(p.id, 0),
            "members": member_counts.get(p.id, 0),
        }
        for p in projects
    ]
    return render(request, "projects/liste.html", {"projects": items})


@router.get("/projects/neu", response_class=HTMLResponse)
async def project_new(request: Request, user: CurrentUser) -> HTMLResponse:
    return render(request, "projects/neu.html")


@router.post("/projects")
async def project_create(
    request: Request,
    user: CurrentUser,
    db: Db,
    name: Annotated[str, Form()],
    description: Annotated[str, Form()] = "",
) -> RedirectResponse:
    cfg = await get_runtime_config(db)
    project = await create_project(
        db,
        owner=user,
        name=name,
        description=description.strip() or None,
        embedding_model=cfg.embedding_model,
        embedding_dimensions=get_settings().embedding_dimensions,
    )
    await audit(
        db,
        "project.create",
        actor_user_id=user.id,
        project_id=project.id,
        target_type="project",
        target_id=str(project.id),
        meta={"name": project.name},
    )
    await db.commit()
    return RedirectResponse(f"/projects/{project.id}", status_code=303)


@router.get("/projects/{project_id}", response_class=HTMLResponse)
async def project_detail(
    request: Request, project: ProjectViewer, user: CurrentUser, db: Db
) -> HTMLResponse:
    documents_result = await db.execute(
        select(Document)
        .where(Document.project_id == project.id)
        .order_by(Document.created_at.desc())
    )
    documents = list(documents_result.scalars())
    crawl_rows = await list_sources_with_jobs(db, project.id)
    chats = await chat_sessions_for_project(db, project, user)
    collections_result = await db.execute(
        select(Collection).where(Collection.project_id == project.id).order_by(Collection.name)
    )
    collections = list(collections_result.scalars())
    chat_configs = list(
        (
            await db.execute(
                select(ChatConfig)
                .where(ChatConfig.project_id == project.id)
                .order_by(ChatConfig.name)
            )
        ).scalars()
    )

    members_result = await db.execute(
        select(ProjectMember, User)
        .join(User, ProjectMember.user_id == User.id)
        .where(ProjectMember.project_id == project.id)
        .order_by(User.username)
    )
    members = [{"member": m, "user": u} for m, u in members_result.all()]
    member_user_ids = [m["user"].id for m in members]
    available_users = list(
        (
            await db.execute(
                select(User)
                .where(User.is_active, User.id.notin_(member_user_ids))
                .order_by(User.username.asc())
            )
        ).scalars()
    )
    my_role = next(
        (m["member"].role for m in members if m["user"].id == user.id),
        ProjectRole.OWNER if user.is_platform_admin else None,
    )
    can_manage = user.is_platform_admin or (
        my_role is not None and ROLE_ORDER[my_role] >= ROLE_ORDER[ProjectRole.ADMIN]
    )
    can_edit = user.is_platform_admin or (
        my_role is not None and ROLE_ORDER[my_role] >= ROLE_ORDER[ProjectRole.EDITOR]
    )
    return render(
        request,
        "projects/detail.html",
        {
            "project": project,
            "documents": documents,
            "crawl_rows": crawl_rows,
            "chats": chats,
            "collections": collections,
            "chat_configs": chat_configs,
            "members": members,
            "available_users": available_users,
            "can_manage": can_manage,
            "can_edit": can_edit,
        },
    )
