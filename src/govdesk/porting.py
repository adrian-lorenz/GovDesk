# SPDX-FileCopyrightText: 2026 GovDesk-Mitwirkende
#
# SPDX-License-Identifier: EUPL-1.2

"""Projekt-Export/-Import als in sich geschlossenes ZIP-Archiv.

Bewusst **vektorunabhängig**: das Archiv enthält Originaldateien + Metadaten,
aber keine Embeddings. Beim Import wird mit dem Embedding-Modell der Zielinstanz
neu eingebettet — so lässt sich ein Projekt zwischen Instanzen mit
unterschiedlichen Modellen übertragen.
"""

import io
import json
import logging
import uuid
import zipfile
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from govdesk.db.models import ChatConfig, Collection, Document, Project, User
from govdesk.documents import storage
from govdesk.documents.service import create_document
from govdesk.projects.service import create_project

logger = logging.getLogger(__name__)

FORMAT_VERSION = 1


async def export_project_archive(db: AsyncSession, project: Project) -> bytes:
    """Serialisiert Projekt, Sammlungen, Chat-Profile und Dokumente in ein ZIP."""
    collections = list(
        (
            await db.execute(select(Collection).where(Collection.project_id == project.id))
        ).scalars()
    )
    configs = list(
        (
            await db.execute(select(ChatConfig).where(ChatConfig.project_id == project.id))
        ).scalars()
    )
    documents = list(
        (await db.execute(select(Document).where(Document.project_id == project.id))).scalars()
    )

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "manifest.json",
            json.dumps(
                {
                    "format_version": FORMAT_VERSION,
                    "exported_at": datetime.now(UTC).isoformat(),
                    "project": {
                        "name": project.name,
                        "description": project.description,
                        "embedding_model": project.embedding_model,
                    },
                },
                ensure_ascii=False,
                indent=2,
            ),
        )
        coll_json = [
            {"id": str(c.id), "name": c.name, "description": c.description} for c in collections
        ]
        zf.writestr("collections.json", json.dumps(coll_json, ensure_ascii=False))
        zf.writestr(
            "chat_configs.json",
            json.dumps(
                [
                    {
                        "name": c.name,
                        "system_prompt": c.system_prompt,
                        "model": c.model,
                        "temperature": c.temperature,
                        "top_k": c.top_k,
                        "rerank_enabled": c.rerank_enabled,
                        "collection_ids": [str(i) for i in (c.collection_ids or [])],
                        "is_default": c.is_default,
                    }
                    for c in configs
                ],
                ensure_ascii=False,
            ),
        )
        doc_meta = []
        for doc in documents:
            if not doc.file_path:
                continue
            try:
                data = storage.read_file(doc.file_path)
            except FileNotFoundError:
                continue
            stored = f"{doc.id}_{doc.filename}"
            zf.writestr(f"documents/{stored}", data)
            doc_meta.append(
                {
                    "stored": stored,
                    "filename": doc.filename,
                    "content_type": doc.content_type,
                    "source_type": doc.source_type.value,
                    "source_url": doc.source_url,
                    "collection_id": str(doc.collection_id) if doc.collection_id else None,
                }
            )
        zf.writestr("documents.json", json.dumps(doc_meta, ensure_ascii=False))

    return buffer.getvalue()


async def import_project_archive(
    db: AsyncSession,
    owner: User,
    data: bytes,
    embedding_model: str,
    embedding_dimensions: int,
) -> tuple[Project, list[uuid.UUID]]:
    """Legt aus einem Archiv ein neues Projekt an. Gibt (Projekt, zu-ingestende
    Dokument-IDs) zurück — das Einreihen der Ingest-Jobs übernimmt der Aufrufer."""
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        manifest = json.loads(zf.read("manifest.json"))
        collections = json.loads(zf.read("collections.json"))
        configs = json.loads(zf.read("chat_configs.json"))
        doc_meta = json.loads(zf.read("documents.json"))

        meta_project = manifest.get("project", {})
        project = await create_project(
            db,
            owner=owner,
            name=meta_project.get("name") or "Importiertes Projekt",
            description=meta_project.get("description"),
            embedding_model=embedding_model,
            embedding_dimensions=embedding_dimensions,
        )

        # Sammlungen neu anlegen, alte→neue ID merken
        coll_map: dict[str, uuid.UUID] = {}
        for c in collections:
            new = Collection(
                project_id=project.id, name=c["name"], description=c.get("description")
            )
            db.add(new)
            await db.flush()
            coll_map[c["id"]] = new.id

        for c in configs:
            new_ids = [coll_map[i] for i in c.get("collection_ids", []) if i in coll_map]
            db.add(
                ChatConfig(
                    project_id=project.id,
                    name=c["name"],
                    system_prompt=c.get("system_prompt"),
                    model=c.get("model"),
                    temperature=c.get("temperature", 0.2),
                    top_k=c.get("top_k", 4),
                    rerank_enabled=c.get("rerank_enabled", True),
                    collection_ids=new_ids or None,
                    is_default=c.get("is_default", False),
                )
            )

        doc_ids: list[uuid.UUID] = []
        for meta in doc_meta:
            payload = zf.read(f"documents/{meta['stored']}")
            old_coll = meta.get("collection_id")
            coll_id = coll_map.get(old_coll) if old_coll else None
            try:
                doc = await create_document(
                    db,
                    project,
                    filename=meta["filename"],
                    data=payload,
                    content_type=meta.get("content_type"),
                    collection_id=coll_id,
                )
            except Exception as exc:
                logger.warning("Import: Dokument „%s“ übersprungen (%s)", meta.get("filename"), exc)
                continue
            doc_ids.append(doc.id)

    return project, doc_ids
