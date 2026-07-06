# SPDX-FileCopyrightText: 2026 GovDesk-Mitwirkende
#
# SPDX-License-Identifier: EUPL-1.2

"""REST-API: Dokumente hochladen, Status abfragen, löschen."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from govdesk.api.schemas import DocumentListOut, DocumentOut
from govdesk.auth.apikey import ApiProject, require_api_key
from govdesk.core.audit import audit
from govdesk.db.models import ApiKey, Document, DocumentSource
from govdesk.db.session import get_db
from govdesk.documents.parsers.base import UnsupportedFormatError
from govdesk.documents.service import (
    DuplicateDocumentError,
    create_document,
    delete_document_full,
    enqueue_ingest,
)

router = APIRouter(prefix="/documents", tags=["Dokumente"])

Db = Annotated[AsyncSession, Depends(get_db)]
WriteKey = Annotated[ApiKey, Depends(require_api_key("documents:write"))]
ReadKey = Annotated[ApiKey, Depends(require_api_key("documents:read"))]

MAX_UPLOAD_BYTES = 100 * 1024 * 1024


@router.post("", response_model=DocumentOut, status_code=201, summary="Dokument hochladen")
async def api_upload(project: ApiProject, key: WriteKey, db: Db, datei: UploadFile) -> Document:
    data = await datei.read()
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Datei größer als 100 MB")
    try:
        document = await create_document(
            db,
            project,
            filename=datei.filename or "unbenannt",
            data=data,
            content_type=datei.content_type,
            source_type=DocumentSource.API,
        )
    except (UnsupportedFormatError, DuplicateDocumentError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    await audit(
        db,
        "document.upload",
        actor_api_key_id=key.id,
        project_id=project.id,
        target_type="document",
        target_id=str(document.id),
        meta={"filename": document.filename, "via": "api"},
    )
    await db.commit()
    await enqueue_ingest(document)
    return document


@router.get("", response_model=DocumentListOut, summary="Dokumente auflisten")
async def api_list(project: ApiProject, key: ReadKey, db: Db) -> dict:
    result = await db.execute(
        select(Document)
        .where(Document.project_id == project.id)
        .order_by(Document.created_at.desc())
    )
    return {"documents": list(result.scalars())}


@router.get("/{document_id}", response_model=DocumentOut, summary="Dokument-Status abfragen")
async def api_get(project: ApiProject, key: ReadKey, db: Db, document_id: uuid.UUID) -> Document:
    document = await db.get(Document, document_id)
    if document is None or document.project_id != project.id:
        raise HTTPException(status_code=404, detail="Dokument nicht gefunden")
    return document


@router.delete("/{document_id}", status_code=204, summary="Dokument löschen")
async def api_delete(project: ApiProject, key: WriteKey, db: Db, document_id: uuid.UUID) -> None:
    document = await db.get(Document, document_id)
    if document is None or document.project_id != project.id:
        raise HTTPException(status_code=404, detail="Dokument nicht gefunden")
    await delete_document_full(db, project, document)
    await audit(
        db,
        "document.delete",
        actor_api_key_id=key.id,
        project_id=project.id,
        target_type="document",
        target_id=str(document_id),
        meta={"via": "api"},
    )
    await db.commit()
