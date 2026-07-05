# SPDX-FileCopyrightText: 2026 GovDesk-Mitwirkende
#
# SPDX-License-Identifier: EUPL-1.2

import uuid
from typing import Annotated

from fastapi import APIRouter, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse

from govdesk.auth.deps import CurrentUser, Db, ProjectEditor, ProjectViewer, has_min_role
from govdesk.core.app_settings import get_runtime_config
from govdesk.core.audit import audit
from govdesk.db.models import Collection, Document, DocumentStatus, ProjectRole
from govdesk.documents.parsers.base import UnsupportedFormatError
from govdesk.documents.service import (
    DuplicateDocumentError,
    create_document,
    delete_document_full,
    enqueue_ingest,
)
from govdesk.rag.retrieval import retrieve
from govdesk.web.deps import render

router = APIRouter()

MAX_UPLOAD_BYTES = 100 * 1024 * 1024


@router.post("/projects/{project_id}/documents")
async def upload_document(
    request: Request,
    project: ProjectEditor,
    user: CurrentUser,
    db: Db,
    datei: UploadFile,
    collection_id: Annotated[str, Form()] = "",
) -> RedirectResponse:
    data = await datei.read()
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Datei größer als 100 MB")
    parsed_collection_id = None
    if collection_id:
        collection = await db.get(Collection, uuid.UUID(collection_id))
        if collection is None or collection.project_id != project.id:
            raise HTTPException(status_code=404, detail="Sammlung nicht gefunden")
        parsed_collection_id = collection.id
    try:
        document = await create_document(
            db,
            project,
            filename=datei.filename or "unbenannt",
            data=data,
            content_type=datei.content_type,
            collection_id=parsed_collection_id,
        )
    except (UnsupportedFormatError, DuplicateDocumentError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    await audit(
        db,
        "document.upload",
        actor_user_id=user.id,
        project_id=project.id,
        target_type="document",
        target_id=str(document.id),
        meta={"filename": document.filename, "size_bytes": document.size_bytes},
    )
    await db.commit()
    await enqueue_ingest(document)
    return RedirectResponse(f"/projects/{project.id}", status_code=303)


@router.get("/projects/{project_id}/documents/{document_id}/zeile", response_class=HTMLResponse)
async def document_row(
    request: Request, project: ProjectViewer, user: CurrentUser, db: Db, document_id: uuid.UUID
) -> HTMLResponse:
    """HTMX-Polling-Partial für die Statusanzeige."""
    document = await _load_document(db, project, document_id)
    can_edit = await has_min_role(db, project, user, ProjectRole.EDITOR)
    return render(
        request,
        "partials/_dokument_zeile.html",
        {"document": document, "project": project, "can_edit": can_edit},
    )


async def _load_document(db: Db, project, document_id: uuid.UUID) -> Document:
    document = await db.get(Document, document_id)
    if document is None or document.project_id != project.id:
        raise HTTPException(status_code=404, detail="Dokument nicht gefunden")
    return document


@router.post("/projects/{project_id}/documents/{document_id}/reindex")
async def document_reindex(
    project: ProjectEditor, user: CurrentUser, db: Db, document_id: uuid.UUID
) -> RedirectResponse:
    document = await _load_document(db, project, document_id)
    document.status = DocumentStatus.PENDING
    document.error = None
    await audit(
        db,
        "document.reindex",
        actor_user_id=user.id,
        project_id=project.id,
        target_type="document",
        target_id=str(document.id),
    )
    await db.commit()
    await enqueue_ingest(document)
    return RedirectResponse(f"/projects/{project.id}", status_code=303)


@router.post("/projects/{project_id}/documents/{document_id}/loeschen")
async def document_delete(
    project: ProjectEditor, user: CurrentUser, db: Db, document_id: uuid.UUID
) -> RedirectResponse:
    document = await _load_document(db, project, document_id)
    await delete_document_full(db, project, document)
    await audit(
        db,
        "document.delete",
        actor_user_id=user.id,
        project_id=project.id,
        target_type="document",
        target_id=str(document_id),
        meta={"filename": document.filename},
    )
    await db.commit()
    return RedirectResponse(f"/projects/{project.id}", status_code=303)


@router.post("/projects/{project_id}/collections")
async def collection_create(
    project: ProjectEditor,
    user: CurrentUser,
    db: Db,
    name: Annotated[str, Form()],
) -> RedirectResponse:
    db.add(Collection(project_id=project.id, name=name.strip()))
    await audit(
        db,
        "collection.create",
        actor_user_id=user.id,
        project_id=project.id,
        meta={"name": name.strip()},
    )
    await db.commit()
    return RedirectResponse(f"/projects/{project.id}", status_code=303)


@router.get("/projects/{project_id}/retrieval", response_class=HTMLResponse)
async def retrieval_debug(
    request: Request, project: ProjectEditor, db: Db, q: str = ""
) -> HTMLResponse:
    """Debug-Seite: Retrieval ohne LLM — zeigt gerankte Chunks mit Scores."""
    citations = []
    if q.strip():
        cfg = await get_runtime_config(db)
        result = await retrieve(project, q.strip(), cfg, top_n=10)
        citations = result.citations
    return render(
        request,
        "projects/retrieval.html",
        {"project": project, "q": q, "citations": citations},
    )
