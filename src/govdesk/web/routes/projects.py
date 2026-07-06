# SPDX-FileCopyrightText: 2026 GovDesk-Mitwirkende
#
# SPDX-License-Identifier: EUPL-1.2

from typing import Annotated

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, select

from govdesk.auth.deps import CurrentUser, Db, ProjectAdmin, ProjectEditor, ProjectViewer
from govdesk.chat.service import chat_sessions_for_project, create_chat_session
from govdesk.core.app_settings import get_runtime_config
from govdesk.core.audit import audit
from govdesk.core.config import get_settings
from govdesk.db.models import (
    ChatConfig,
    Collection,
    Document,
    ProjectMember,
    User,
)
from govdesk.projects.service import create_project, projects_for_user
from govdesk.web.deps import render
from govdesk.web.project_layout import ensure_section_visible, project_menu_context

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


@router.get("/projects/{project_id}")
async def project_home(project: ProjectViewer, user: CurrentUser, db: Db) -> RedirectResponse:
    """Einstieg ins Projekt ist immer der Chat: zum jüngsten Chat springen bzw. neu anlegen."""
    sessions = await chat_sessions_for_project(db, project, user)
    if sessions:
        target = sessions[0].id
    else:
        default = (
            await db.execute(
                select(ChatConfig).where(ChatConfig.project_id == project.id, ChatConfig.is_default)
            )
        ).scalar_one_or_none()
        session = await create_chat_session(
            db, project, user, chat_config_id=default.id if default else None
        )
        await db.commit()
        target = session.id
    return RedirectResponse(f"/projects/{project.id}/chats/{target}", status_code=303)


@router.get("/projects/{project_id}/dokumente", response_class=HTMLResponse)
async def project_dokumente(
    request: Request, project: ProjectEditor, user: CurrentUser, db: Db
) -> HTMLResponse:
    documents = list(
        (
            await db.execute(
                select(Document)
                .where(Document.project_id == project.id)
                .order_by(Document.created_at.desc())
            )
        ).scalars()
    )
    collections = list(
        (
            await db.execute(
                select(Collection)
                .where(Collection.project_id == project.id)
                .order_by(Collection.name)
            )
        ).scalars()
    )
    ctx = await project_menu_context(db, project, user, "dokumente")
    return render(
        request,
        "projects/dokumente.html",
        {**ctx, "documents": documents, "collections": collections},
    )


@router.get("/projects/{project_id}/mitglieder", response_class=HTMLResponse)
async def project_mitglieder(
    request: Request, project: ProjectAdmin, user: CurrentUser, db: Db
) -> HTMLResponse:
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
    ctx = await project_menu_context(db, project, user, "mitglieder")
    return render(
        request,
        "projects/mitglieder.html",
        {**ctx, "members": members, "available_users": available_users},
    )
