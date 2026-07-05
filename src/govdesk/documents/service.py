# SPDX-FileCopyrightText: 2026 GovDesk-Mitwirkende
#
# SPDX-License-Identifier: EUPL-1.2

"""Dokument-Upload und Ingestion-Orchestrierung."""

import hashlib
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from govdesk.db.models import Document, DocumentSource, DocumentStatus, Project
from govdesk.documents import storage
from govdesk.documents.parsers.registry import parser_for


class DuplicateDocumentError(Exception):
    """Identische Datei existiert bereits im Projekt."""


async def create_document(
    db: AsyncSession,
    project: Project,
    filename: str,
    data: bytes,
    content_type: str | None,
    source_type: DocumentSource = DocumentSource.UPLOAD,
    source_url: str | None = None,
    collection_id: uuid.UUID | None = None,
) -> Document:
    """Validiert, speichert und legt den Dokument-Datensatz an (Status: pending).

    Der eigentliche Ingest (Parsen → Chunken → Embedden) läuft im Worker;
    der Aufrufer muss nach dem Commit `enqueue_ingest` aufrufen.
    """
    parser_for(filename)  # wirft UnsupportedFormatError vor dem Speichern

    sha256 = hashlib.sha256(data).hexdigest()
    existing = await db.execute(
        select(Document.id).where(Document.project_id == project.id, Document.sha256 == sha256)
    )
    if existing.scalar_one_or_none() is not None:
        raise DuplicateDocumentError(f"„{filename}“ ist bereits in diesem Projekt vorhanden.")

    document = Document(
        project_id=project.id,
        collection_id=collection_id,
        filename=filename,
        content_type=content_type,
        source_type=source_type,
        source_url=source_url,
        size_bytes=len(data),
        sha256=sha256,
        status=DocumentStatus.PENDING,
    )
    db.add(document)
    await db.flush()
    document.file_path = storage.store_file(project.id, document.id, filename, data)
    return document


async def enqueue_ingest(document: Document) -> None:
    from govdesk.workers.tasks import ingest_document

    await ingest_document.defer_async(document_id=str(document.id))


async def delete_document_full(db: AsyncSession, project: Project, document: Document) -> None:
    """Entfernt Dokument vollständig: Qdrant-Punkte, Datei, DB-Zeile (Chunks kaskadieren)."""
    from govdesk.rag.vectorstore import VectorStore

    store = VectorStore()
    try:
        await store.delete_document(project.qdrant_collection, document.id)
    finally:
        await store.close()
    if document.file_path:
        storage.delete_file(document.file_path)
    await db.delete(document)
