# SPDX-FileCopyrightText: 2026 GovDesk-Mitwirkende
#
# SPDX-License-Identifier: EUPL-1.2

"""Connector-Verwaltung: DB-Abfragen, Item→Dokument-Upsert, verfügbare Plugins."""

import hashlib
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from govdesk.connectors.base import ConnectorPlugin, FetchedItem
from govdesk.connectors.registry import all_connectors
from govdesk.core.app_settings import get_setting
from govdesk.db.models import (
    ConnectorItem,
    ConnectorJob,
    ConnectorSource,
    Document,
    DocumentSource,
    DocumentStatus,
    Project,
)
from govdesk.documents import storage
from govdesk.documents.service import DuplicateDocumentError, create_document, delete_document_full

ENABLED_SETTING_KEY = "connectors_enabled"


async def enabled_type_ids(db: AsyncSession) -> list[str]:
    """Plattformweit freigeschaltete Connector-Typen (Admin-Einstellung)."""
    value = await get_setting(db, ENABLED_SETTING_KEY, [])
    return list(value) if isinstance(value, list) else []


async def available_connectors(db: AsyncSession) -> list[ConnectorPlugin]:
    """Registrierte UND plattformweit freigeschaltete Connectoren."""
    enabled = set(await enabled_type_ids(db))
    return [c for c in all_connectors() if c.type_id in enabled]


async def list_sources_with_jobs(db: AsyncSession, project_id: uuid.UUID) -> list[dict]:
    """Connector-Quellen eines Projekts mit ihrem jeweils jüngsten Job."""
    sources = (
        (
            await db.execute(
                select(ConnectorSource)
                .where(ConnectorSource.project_id == project_id)
                .order_by(ConnectorSource.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    rows = []
    for source in sources:
        last_job = (
            await db.execute(
                select(ConnectorJob)
                .where(ConnectorJob.connector_source_id == source.id)
                .order_by(ConnectorJob.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        rows.append({"source": source, "job": last_job})
    return rows


async def delete_source_full(db: AsyncSession, project: Project, source: ConnectorSource) -> None:
    """Löscht eine Quelle samt aller daraus erzeugten Dokumente (Qdrant + Datei
    + DB-Zeile). Dokumente zuerst — danach kaskadieren Jobs und Items."""
    document_ids = (
        (
            await db.execute(
                select(ConnectorItem.document_id).where(
                    ConnectorItem.connector_source_id == source.id,
                    ConnectorItem.document_id.is_not(None),
                )
            )
        )
        .scalars()
        .all()
    )
    for document_id in set(document_ids):
        document = await db.get(Document, document_id)
        if document is not None:
            await delete_document_full(db, project, document)
    await db.delete(source)


async def upsert_item_document(
    db: AsyncSession,
    project: Project,
    item: FetchedItem,
    existing_document_id: uuid.UUID | None,
    collection_id: uuid.UUID | None,
) -> Document | None:
    """Legt für ein FetchedItem ein Dokument an bzw. aktualisiert das bestehende.

    Gibt das zu ingestende Dokument zurück; None wenn Duplikat ohne Änderung.
    """
    if existing_document_id is not None:
        document = await db.get(Document, existing_document_id)
        if document is not None:
            document.sha256 = hashlib.sha256(item.data).hexdigest()
            document.filename = item.filename
            document.content_type = item.content_type
            document.source_url = item.source_url
            document.status = DocumentStatus.PENDING
            document.error = None
            if document.file_path:
                storage.delete_file(document.file_path)
            document.file_path = storage.store_file(
                project.id, document.id, item.filename, item.data
            )
            await db.flush()
            return document

    try:
        return await create_document(
            db,
            project,
            filename=item.filename,
            data=item.data,
            content_type=item.content_type,
            source_type=DocumentSource.CONNECTOR,
            source_url=item.source_url,
            collection_id=collection_id,
        )
    except DuplicateDocumentError:
        return None
