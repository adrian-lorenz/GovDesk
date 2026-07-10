# SPDX-FileCopyrightText: 2026 GovDesk-Mitwirkende
#
# SPDX-License-Identifier: EUPL-1.2

"""Kollaborativer Editor: Dokumentliste, Bearbeiten, Long-Poll-Sync, Historie."""

import asyncio
import re
import uuid
from typing import Annotated

import nh3
from fastapi import APIRouter, Form, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse

from govdesk.auth.deps import CurrentUser, Db, ProjectEditor, ProjectViewer
from govdesk.core.audit import audit
from govdesk.db.models import EditorDocument
from govdesk.editor.service import (
    VersionConflictError,
    create_document,
    create_folder,
    delete_folder,
    folder_breadcrumbs,
    get_document,
    get_folder,
    is_descendant_folder,
    list_documents,
    list_folders,
    list_revisions,
    save_document,
    usernames_for,
)
from govdesk.web.deps import render
from govdesk.web.project_layout import ensure_section_visible, project_menu_context

router = APIRouter()

# Long-Poll: bis zu ~20 s auf eine neue Version warten, dann „kein Update".
_POLL_SECONDS = 20

# Erlaubte Formatierungs-Tags im WYSIWYG-Editor (alles andere entfernt nh3).
_ALLOWED_TAGS = {
    "p", "br", "b", "strong", "i", "em", "u", "s", "h1", "h2", "h3", "h4",
    "ul", "ol", "li", "blockquote", "a", "code", "pre", "span", "div",
}
# nh3 verwaltet rel (noopener) bei Links selbst — daher hier NICHT „rel" listen.
_ALLOWED_ATTR = {"a": {"href", "title", "target"}}


def _sanitize(html: str) -> str:
    return nh3.clean(html, tags=_ALLOWED_TAGS, attributes=_ALLOWED_ATTR)


@router.get("/projects/{project_id}/editor", response_class=HTMLResponse)
async def editor_list(
    request: Request,
    project: ProjectViewer,
    user: CurrentUser,
    db: Db,
    ordner: uuid.UUID | None = None,
) -> HTMLResponse:
    await ensure_section_visible(db, project, user, "editor")
    folder = await get_folder(db, ordner, project.id) if ordner else None
    if ordner and folder is None:
        raise HTTPException(status_code=404, detail="Ordner nicht gefunden")
    docs = await list_documents(db, project.id, user, folder_id=folder.id if folder else None)
    folders = await list_folders(db, project.id, folder.id if folder else None)
    crumbs = await folder_breadcrumbs(db, folder)
    names = await usernames_for(db, {d.updated_by for d in docs})
    ctx = await project_menu_context(db, project, user, "editor")
    return render(
        request,
        "projects/editor_liste.html",
        {
            **ctx,
            "docs": docs,
            "names": names,
            "folders": folders,
            "folder": folder,
            "crumbs": crumbs,
        },
    )


@router.post("/projects/{project_id}/editor")
async def editor_create(
    project: ProjectEditor,
    user: CurrentUser,
    db: Db,
    title: Annotated[str, Form()],
    is_private: Annotated[bool, Form()] = False,
    folder_id: Annotated[uuid.UUID | None, Form()] = None,
) -> RedirectResponse:
    doc = await create_document(db, project.id, user, title, is_private)
    if folder_id is not None and await get_folder(db, folder_id, project.id) is not None:
        doc.folder_id = folder_id
    await audit(
        db,
        "editor_document.create",
        actor_user_id=user.id,
        project_id=project.id,
        target_type="editor_document",
        target_id=str(doc.id),
        meta={"title": doc.title, "private": is_private},
    )
    await db.commit()
    return RedirectResponse(f"/projects/{project.id}/editor/{doc.id}", status_code=303)


@router.get("/projects/{project_id}/editor/{document_id}", response_class=HTMLResponse)
async def editor_page(
    request: Request, project: ProjectViewer, user: CurrentUser, db: Db, document_id: uuid.UUID
) -> HTMLResponse:
    await ensure_section_visible(db, project, user, "editor")
    doc = await get_document(db, document_id, project.id, user)
    if doc is None:
        raise HTTPException(status_code=404, detail="Dokument nicht gefunden")
    ctx = await project_menu_context(db, project, user, "editor")
    return render(request, "projects/editor.html", {**ctx, "doc": doc})


@router.post("/projects/{project_id}/editor/{document_id}/save")
async def editor_save(
    project: ProjectEditor,
    user: CurrentUser,
    db: Db,
    document_id: uuid.UUID,
    content: Annotated[str, Form()],
    base_version: Annotated[int, Form()],
) -> JSONResponse:
    doc = await get_document(db, document_id, project.id, user)
    if doc is None:
        raise HTTPException(status_code=404, detail="Dokument nicht gefunden")
    try:
        doc = await save_document(db, doc, user, _sanitize(content), base_version)
    except VersionConflictError as exc:
        await db.rollback()
        # 409: der Client soll die aktuelle Fassung übernehmen.
        return JSONResponse(
            status_code=409,
            content={"version": exc.current.version, "content": exc.current.content},
        )
    await db.commit()
    return JSONResponse({"version": doc.version})


@router.get("/projects/{project_id}/editor/{document_id}/poll")
async def editor_poll(
    project: ProjectViewer, user: CurrentUser, db: Db, document_id: uuid.UUID, since: int = 0
) -> Response:
    """Long-Poll: gibt neue Version + Inhalt zurück, sobald version > since; sonst 204.

    Jeder Durchlauf nutzt eine eigene kurzlebige Session — so sehen wir Commits
    anderer Nutzer, ohne die per Dependency geladenen Request-Objekte zu expiren
    (das löste sonst Lazy-Loads außerhalb des Async-Greenlets aus).
    """
    from govdesk.db.session import get_session_factory

    # Sichtbarkeits-relevante Werte einmalig als plain Werte festhalten.
    project_id = project.id
    user_id = user.id
    is_admin = user.is_platform_admin
    session_factory = get_session_factory()

    for _ in range(_POLL_SECONDS):
        async with session_factory() as poll_db:
            doc = await poll_db.get(EditorDocument, document_id)
            if doc is None or doc.project_id != project_id:
                raise HTTPException(status_code=404, detail="Dokument nicht gefunden")
            if doc.is_private and doc.created_by != user_id and not is_admin:
                raise HTTPException(status_code=404, detail="Dokument nicht gefunden")
            if doc.version > since:
                names = await usernames_for(poll_db, {doc.updated_by})
                return JSONResponse(
                    {
                        "version": doc.version,
                        "content": doc.content,
                        "updated_by": names.get(doc.updated_by, ""),
                    }
                )
        await asyncio.sleep(1)
    return Response(status_code=204)


@router.get("/projects/{project_id}/editor/{document_id}/export")
async def editor_export(
    project: ProjectViewer, user: CurrentUser, db: Db, document_id: uuid.UUID, format: str = "docx"
) -> Response:
    await ensure_section_visible(db, project, user, "editor")
    doc = await get_document(db, document_id, project.id, user)
    if doc is None:
        raise HTTPException(status_code=404, detail="Dokument nicht gefunden")
    from govdesk.editor.export import to_docx, to_odf, to_pdf

    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", doc.title).strip("-") or "dokument"
    if format == "pdf":
        data = await asyncio.to_thread(to_pdf, doc.title, doc.content)
        media = "application/pdf"
        ext = "pdf"
    elif format == "odf":
        data = await asyncio.to_thread(to_odf, doc.title, doc.content)
        media = "application/vnd.oasis.opendocument.text"
        ext = "odt"
    else:
        data = await asyncio.to_thread(to_docx, doc.title, doc.content)
        media = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        ext = "docx"
    return Response(
        content=data,
        media_type=media,
        headers={"Content-Disposition": f'attachment; filename="{slug}.{ext}"'},
    )


@router.post("/projects/{project_id}/editor/{document_id}/umbenennen")
async def editor_rename(
    project: ProjectEditor,
    user: CurrentUser,
    db: Db,
    document_id: uuid.UUID,
    title: Annotated[str, Form()],
) -> Response:
    doc = await get_document(db, document_id, project.id, user)
    if doc is None:
        raise HTTPException(status_code=404, detail="Dokument nicht gefunden")
    neu = title.strip()[:300]
    if neu:
        doc.title = neu
        await db.commit()
    return Response(status_code=204)


# ---------------------------------------------------------------------------
# Ordner der Dokumentenbibliothek (Explorer)
# ---------------------------------------------------------------------------


def _liste_url(project_id: uuid.UUID, folder_id: uuid.UUID | None) -> str:
    return f"/projects/{project_id}/editor" + (f"?ordner={folder_id}" if folder_id else "")


@router.post("/projects/{project_id}/editor/ordner")
async def folder_create(
    project: ProjectEditor,
    user: CurrentUser,
    db: Db,
    name: Annotated[str, Form()],
    parent_id: Annotated[uuid.UUID | None, Form()] = None,
) -> RedirectResponse:
    if parent_id is not None and await get_folder(db, parent_id, project.id) is None:
        raise HTTPException(status_code=404, detail="Ordner nicht gefunden")
    folder = await create_folder(db, project.id, user, name, parent_id)
    await audit(
        db,
        "editor_folder.create",
        actor_user_id=user.id,
        project_id=project.id,
        target_type="editor_folder",
        target_id=str(folder.id),
        meta={"name": folder.name},
    )
    await db.commit()
    return RedirectResponse(_liste_url(project.id, parent_id), status_code=303)


@router.post("/projects/{project_id}/editor/ordner/{folder_id}/umbenennen")
async def folder_rename(
    project: ProjectEditor,
    user: CurrentUser,
    db: Db,
    folder_id: uuid.UUID,
    name: Annotated[str, Form()],
) -> Response:
    folder = await get_folder(db, folder_id, project.id)
    if folder is None:
        raise HTTPException(status_code=404, detail="Ordner nicht gefunden")
    neu = name.strip()[:200]
    if neu:
        folder.name = neu
        await db.commit()
    return Response(status_code=204)


@router.post("/projects/{project_id}/editor/ordner/{folder_id}/loeschen")
async def folder_delete(
    project: ProjectEditor, user: CurrentUser, db: Db, folder_id: uuid.UUID
) -> RedirectResponse:
    folder = await get_folder(db, folder_id, project.id)
    if folder is None:
        raise HTTPException(status_code=404, detail="Ordner nicht gefunden")
    parent_id = folder.parent_id
    await audit(
        db,
        "editor_folder.delete",
        actor_user_id=user.id,
        project_id=project.id,
        target_type="editor_folder",
        target_id=str(folder_id),
        meta={"name": folder.name},
    )
    await delete_folder(db, folder)
    await db.commit()
    return RedirectResponse(_liste_url(project.id, parent_id), status_code=303)


@router.post("/projects/{project_id}/editor/ordner/{folder_id}/verschieben")
async def folder_move(
    project: ProjectEditor,
    user: CurrentUser,
    db: Db,
    folder_id: uuid.UUID,
    ziel: Annotated[uuid.UUID | None, Form()] = None,
) -> Response:
    folder = await get_folder(db, folder_id, project.id)
    if folder is None:
        raise HTTPException(status_code=404, detail="Ordner nicht gefunden")
    if ziel is not None:
        ziel_ordner = await get_folder(db, ziel, project.id)
        if ziel_ordner is None:
            raise HTTPException(status_code=404, detail="Zielordner nicht gefunden")
        # Ein Ordner darf nicht in sich selbst oder einen Unterordner wandern.
        if await is_descendant_folder(db, ziel_ordner, folder.id):
            raise HTTPException(
                status_code=400, detail="Ordner kann nicht in sich selbst verschoben werden"
            )
    folder.parent_id = ziel
    await db.commit()
    return Response(status_code=204)


@router.post("/projects/{project_id}/editor/{document_id}/verschieben")
async def editor_move(
    project: ProjectEditor,
    user: CurrentUser,
    db: Db,
    document_id: uuid.UUID,
    ziel: Annotated[uuid.UUID | None, Form()] = None,
) -> Response:
    doc = await get_document(db, document_id, project.id, user)
    if doc is None:
        raise HTTPException(status_code=404, detail="Dokument nicht gefunden")
    if ziel is not None and await get_folder(db, ziel, project.id) is None:
        raise HTTPException(status_code=404, detail="Zielordner nicht gefunden")
    doc.folder_id = ziel
    await db.commit()
    return Response(status_code=204)


# ---------------------------------------------------------------------------
# KI-Assistent im Editor
# ---------------------------------------------------------------------------


@router.post("/projects/{project_id}/editor/{document_id}/ki")
async def editor_assist(
    project: ProjectEditor,
    user: CurrentUser,
    db: Db,
    document_id: uuid.UUID,
    frage: Annotated[str, Form()],
    modus: Annotated[str, Form()] = "frage",
    auswahl: Annotated[str, Form()] = "",
) -> StreamingResponse:
    doc = await get_document(db, document_id, project.id, user)
    if doc is None:
        raise HTTPException(status_code=404, detail="Dokument nicht gefunden")
    from govdesk.editor.assistent import stream_assist

    return StreamingResponse(
        stream_assist(project, doc, user, frage, modus, auswahl, _sanitize),
        media_type="text/event-stream",
    )


@router.get("/projects/{project_id}/editor/{document_id}/historie", response_class=HTMLResponse)
async def editor_history(
    request: Request, project: ProjectViewer, user: CurrentUser, db: Db, document_id: uuid.UUID
) -> HTMLResponse:
    await ensure_section_visible(db, project, user, "editor")
    doc = await get_document(db, document_id, project.id, user)
    if doc is None:
        raise HTTPException(status_code=404, detail="Dokument nicht gefunden")
    revisions = await list_revisions(db, document_id)
    names = await usernames_for(db, {r.author_id for r in revisions})
    ctx = await project_menu_context(db, project, user, "editor")
    return render(
        request,
        "projects/editor_historie.html",
        {**ctx, "doc": doc, "revisions": revisions, "names": names},
    )


@router.post("/projects/{project_id}/editor/{document_id}/loeschen")
async def editor_delete(
    project: ProjectEditor, user: CurrentUser, db: Db, document_id: uuid.UUID
) -> RedirectResponse:
    doc = await get_document(db, document_id, project.id, user)
    if doc is None:
        raise HTTPException(status_code=404, detail="Dokument nicht gefunden")
    await audit(
        db,
        "editor_document.delete",
        actor_user_id=user.id,
        project_id=project.id,
        target_type="editor_document",
        target_id=str(document_id),
        meta={"title": doc.title},
    )
    await db.delete(doc)
    await db.commit()
    return RedirectResponse(f"/projects/{project.id}/editor", status_code=303)
