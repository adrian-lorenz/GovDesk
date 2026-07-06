# SPDX-FileCopyrightText: 2026 GovDesk-Mitwirkende
#
# SPDX-License-Identifier: EUPL-1.2

import asyncio
import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from govdesk.auth.deps import CurrentUser, Db, ProjectEditor, ProjectViewer, has_min_role
from govdesk.core.app_settings import get_runtime_config
from govdesk.core.audit import audit
from govdesk.db.models import Collection, Document, DocumentStatus, ProjectRole
from govdesk.documents import storage
from govdesk.documents.highlight import render_page_with_highlights
from govdesk.documents.parsers.base import UnsupportedFormatError
from govdesk.documents.service import (
    DuplicateDocumentError,
    create_document,
    delete_document_full,
    enqueue_ingest,
    load_chunk_context,
)
from govdesk.rag.retrieval import retrieve
from govdesk.web.deps import render
from govdesk.web.project_layout import ensure_section_visible, project_menu_context

logger = logging.getLogger(__name__)

router = APIRouter()

MAX_UPLOAD_BYTES = 100 * 1024 * 1024


def _is_pdf(document: Document) -> bool:
    return (document.content_type or "").startswith("application/pdf") or (
        document.filename or ""
    ).lower().endswith(".pdf")


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


@router.get(
    "/projects/{project_id}/documents/{document_id}/passage", response_class=HTMLResponse
)
async def document_passage(
    request: Request,
    project: ProjectViewer,
    user: CurrentUser,
    db: Db,
    document_id: uuid.UUID,
    chunk: int,
) -> HTMLResponse:
    """Modal-Inhalt zu einer Quelle: PDF-Seite mit markierter Fundstelle bzw.
    Text-Ausschnitt mit hervorgehobenem Chunk."""
    document = await _load_document(db, project, document_id)
    target, before, after = await load_chunk_context(db, document_id, chunk)
    if target is None:
        raise HTTPException(status_code=404, detail="Textstelle nicht gefunden")

    page_highlight = None
    if _is_pdf(document) and document.file_path and target.page_no:
        # Absätze des Chunks einzeln suchen — robuster als der ganze Chunk am Stück,
        # und ein Chunk kann Absätze mehrerer Seiten umfassen.
        needles = [p for p in target.text.split("\n\n") if p.strip()]
        try:
            pdf_bytes = await asyncio.to_thread(storage.read_file, document.file_path)
            page_highlight = await asyncio.to_thread(
                render_page_with_highlights, pdf_bytes, target.page_no, needles
            )
        except FileNotFoundError:
            logger.warning("PDF-Datei fehlt für Dokument %s", document_id)
        except Exception:
            logger.exception("PDF-Vorschau fehlgeschlagen für Dokument %s", document_id)

    return render(
        request,
        "partials/_quelle_modal.html",
        {
            "project": project,
            "document": document,
            "target": target,
            "before": before,
            "after": after,
            "page_highlight": page_highlight,
        },
    )


@router.get("/projects/{project_id}/documents/{document_id}/download")
async def document_download(
    project: ProjectViewer, db: Db, document_id: uuid.UUID
) -> Response:
    """Lädt das Originaldokument als Datei herunter."""
    document = await _load_document(db, project, document_id)
    if not document.file_path:
        raise HTTPException(status_code=404, detail="Keine Datei hinterlegt")
    try:
        data = await asyncio.to_thread(storage.read_file, document.file_path)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Datei nicht gefunden") from exc
    return Response(
        content=data,
        media_type=document.content_type or "application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{document.filename}"'},
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
    request: Request, project: ProjectEditor, user: CurrentUser, db: Db, q: str = ""
) -> HTMLResponse:
    """Debug-Seite: Retrieval ohne LLM — zeigt gerankte Chunks mit Scores."""
    await ensure_section_visible(db, project, user, "retrieval")
    citations = []
    if q.strip():
        cfg = await get_runtime_config(db)
        result = await retrieve(project, q.strip(), cfg, top_n=10)
        citations = result.citations
    ctx = await project_menu_context(db, project, user, "retrieval")
    return render(request, "projects/retrieval.html", {**ctx, "q": q, "citations": citations})
