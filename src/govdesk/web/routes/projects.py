# SPDX-FileCopyrightText: 2026 GovDesk-Mitwirkende
#
# SPDX-License-Identifier: EUPL-1.2

import uuid
from typing import Annotated

from fastapi import APIRouter, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy import func, select

from govdesk.auth.deps import (
    CurrentUser,
    Db,
    PlatformAdmin,
    ProjectAdmin,
    ProjectEditor,
    ProjectViewer,
)
from govdesk.chat.service import chat_sessions_for_project, create_chat_session
from govdesk.core.app_settings import get_runtime_config
from govdesk.core.audit import audit
from govdesk.core.config import get_settings
from govdesk.db.models import (
    ChatConfig,
    ChatMessage,
    ChatSession,
    Collection,
    Document,
    ProjectMember,
    User,
)
from govdesk.documents.service import enqueue_ingest
from govdesk.porting import export_project_archive, import_project_archive
from govdesk.projects.service import (
    archive_project,
    archived_projects,
    create_project,
    delete_project_permanently,
    projects_for_user,
    restore_project,
)
from govdesk.web.deps import render
from govdesk.web.project_layout import ensure_section_visible, project_menu_context

router = APIRouter()


@router.get("/projects", response_class=HTMLResponse)
async def project_list(request: Request, user: CurrentUser, db: Db) -> HTMLResponse:
    projects = await projects_for_user(db, user)
    ids = [p.id for p in projects]
    doc_counts: dict = {}
    member_counts: dict = {}
    last_activity: dict = {}
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
        # „Zuletzt verwendet" = jüngste Chat-Nachricht im Projekt.
        for pid, ts in (
            await db.execute(
                select(ChatSession.project_id, func.max(ChatMessage.created_at))
                .join(ChatMessage, ChatMessage.session_id == ChatSession.id)
                .where(ChatSession.project_id.in_(ids))
                .group_by(ChatSession.project_id)
            )
        ).all():
            last_activity[pid] = ts
    items = [
        {
            "project": p,
            "documents": doc_counts.get(p.id, 0),
            "members": member_counts.get(p.id, 0),
            "last_used": last_activity.get(p.id) or p.created_at,
        }
        for p in projects
    ]
    # Nach letzter Nutzung absteigend sortieren (jüngste zuerst).
    items.sort(key=lambda item: item["last_used"], reverse=True)
    # Plattform-Admins sehen zusätzlich das Archiv (behaltene Wissensbasen).
    archiv = await archived_projects(db) if user.is_platform_admin else []
    return render(request, "projects/liste.html", {"projects": items, "archiv": archiv})


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


@router.post("/projects/import")
async def project_import(user: CurrentUser, db: Db, datei: UploadFile) -> RedirectResponse:
    """Projekt-Archiv importieren (neu-eingebettet mit dem Modell dieser Instanz)."""
    data = await datei.read()
    cfg = await get_runtime_config(db)
    try:
        project, doc_ids = await import_project_archive(
            db, user, data, cfg.embedding_model, get_settings().embedding_dimensions
        )
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Archiv nicht lesbar: {exc}") from exc
    await audit(
        db,
        "project.import",
        actor_user_id=user.id,
        project_id=project.id,
        target_type="project",
        target_id=str(project.id),
        meta={"name": project.name, "documents": len(doc_ids)},
    )
    await db.commit()
    # Re-Ingest erst nach dem Commit einreihen (Worker muss die Zeilen sehen).
    for did in doc_ids:
        document = await db.get(Document, did)
        if document is not None:
            await enqueue_ingest(document)
    return RedirectResponse(f"/projects/{project.id}", status_code=303)


@router.post("/projects/{project_id}/loeschen")
async def project_delete(
    project: ProjectAdmin,
    user: CurrentUser,
    db: Db,
    modus: Annotated[str, Form()] = "archiv",
) -> RedirectResponse:
    """Projekt löschen — „archiv" behält die Wissensbasis (Collection) und
    parkt das Projekt im Archiv; „endgueltig" entfernt alles inkl. Qdrant."""
    if modus == "endgueltig":
        await audit(
            db,
            "project.delete",
            actor_user_id=user.id,
            project_id=project.id,
            target_type="project",
            target_id=str(project.id),
            meta={"name": project.name, "collection": project.qdrant_collection},
        )
        await delete_project_permanently(db, project)
    else:
        await audit(
            db,
            "project.archive",
            actor_user_id=user.id,
            project_id=project.id,
            target_type="project",
            target_id=str(project.id),
            meta={"name": project.name, "collection": project.qdrant_collection},
        )
        await archive_project(db, project)
    await db.commit()
    return RedirectResponse("/projects", status_code=303)


async def _archiviertes_projekt(db: Db, project_id: uuid.UUID):
    from govdesk.db.models import Project

    project = await db.get(Project, project_id)
    if project is None or not project.is_archived:
        raise HTTPException(status_code=404, detail="Archiviertes Projekt nicht gefunden")
    return project


@router.post("/projects/archiv/{project_id}/wiederherstellen")
async def project_restore(
    admin: PlatformAdmin, db: Db, project_id: uuid.UUID
) -> RedirectResponse:
    """Verknüpft eine behaltene Wissensbasis wieder: das Projekt kehrt mitsamt
    seiner Collection, Dokumenten und Mitgliedern aus dem Archiv zurück."""
    project = await _archiviertes_projekt(db, project_id)
    await audit(
        db,
        "project.restore",
        actor_user_id=admin.id,
        project_id=project.id,
        target_type="project",
        target_id=str(project.id),
        meta={"name": project.name, "collection": project.qdrant_collection},
    )
    await restore_project(db, project)
    await db.commit()
    return RedirectResponse(f"/projects/{project.id}", status_code=303)


@router.post("/projects/archiv/{project_id}/loeschen")
async def project_archive_delete(
    admin: PlatformAdmin, db: Db, project_id: uuid.UUID
) -> RedirectResponse:
    project = await _archiviertes_projekt(db, project_id)
    await audit(
        db,
        "project.delete",
        actor_user_id=admin.id,
        project_id=project.id,
        target_type="project",
        target_id=str(project.id),
        meta={"name": project.name, "collection": project.qdrant_collection},
    )
    await delete_project_permanently(db, project)
    await db.commit()
    return RedirectResponse("/projects", status_code=303)


@router.get("/projects/{project_id}/export")
async def project_export(project: ProjectAdmin, db: Db) -> Response:
    data = await export_project_archive(db, project)
    return Response(
        content=data,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{project.slug}.govdesk.zip"'},
    )


@router.get("/projects/{project_id}")
async def project_home(project: ProjectViewer, user: CurrentUser, db: Db) -> RedirectResponse:
    """Einstieg ins Projekt ist immer der Chat: zum jüngsten Chat springen bzw. neu anlegen."""
    sessions = await chat_sessions_for_project(db, project, user)
    if sessions:
        target = sessions[0].id
    else:
        cfg = await get_runtime_config(db)
        default = (
            await db.execute(
                select(ChatConfig).where(ChatConfig.project_id == project.id, ChatConfig.is_default)
            )
        ).scalar_one_or_none()
        session = await create_chat_session(
            db,
            project,
            user,
            chat_config_id=(
                default.id
                if default and (default.retrieval_enabled or cfg.model_chat_enabled)
                else None
            ),
        )
        await db.commit()
        target = session.id
    return RedirectResponse(f"/projects/{project.id}/chats/{target}", status_code=303)


@router.get("/projects/{project_id}/dokumente", response_class=HTMLResponse)
async def project_dokumente(
    request: Request, project: ProjectEditor, user: CurrentUser, db: Db
) -> HTMLResponse:
    await ensure_section_visible(db, project, user, "dokumente")
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


@router.post("/projects/{project_id}/rag-fallback")
async def project_rag_fallback_update(
    project: ProjectAdmin,
    user: CurrentUser,
    db: Db,
    fallback_mode: Annotated[str, Form()],
) -> RedirectResponse:
    if fallback_mode not in {"strict", "model_knowledge"}:
        raise HTTPException(status_code=422, detail="Unbekannter Antwortmodus")
    project.rag_fallback_enabled = fallback_mode == "model_knowledge"
    await audit(
        db,
        "project.rag_fallback.update",
        actor_user_id=user.id,
        project_id=project.id,
        target_type="project",
        target_id=str(project.id),
        meta={"mode": fallback_mode},
    )
    await db.commit()
    return RedirectResponse(f"/projects/{project.id}/mitglieder#antwortmodus", status_code=303)
