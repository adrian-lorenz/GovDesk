# SPDX-FileCopyrightText: 2026 GovDesk-Mitwirkende
#
# SPDX-License-Identifier: EUPL-1.2

"""Qdrant-Zugriff. Eine Collection pro Projekt = harte Mandantentrennung."""

import uuid
from dataclasses import dataclass
from typing import Any

from qdrant_client import AsyncQdrantClient, models

from govdesk.core.config import get_settings


@dataclass(frozen=True)
class ChunkPayload:
    point_id: uuid.UUID
    vector: list[float]
    project_id: uuid.UUID
    document_id: uuid.UUID
    chunk_index: int
    filename: str
    text: str
    heading_path: str | None = None
    page_no: int | None = None
    source_url: str | None = None
    collection_id: uuid.UUID | None = None


@dataclass(frozen=True)
class SearchHit:
    point_id: str
    score: float
    document_id: str
    chunk_index: int
    filename: str
    text: str
    heading_path: str | None
    page_no: int | None
    source_url: str | None


class VectorStore:
    def __init__(self, url: str | None = None) -> None:
        self._client = AsyncQdrantClient(url=url or get_settings().qdrant_url)

    async def close(self) -> None:
        await self._client.close()

    async def is_available(self) -> bool:
        try:
            await self._client.get_collections()
            return True
        except Exception:
            return False

    async def ensure_collection(self, name: str, dimensions: int) -> None:
        if not await self._client.collection_exists(name):
            await self._client.create_collection(
                collection_name=name,
                vectors_config=models.VectorParams(
                    size=dimensions, distance=models.Distance.COSINE
                ),
            )
            for field in ("project_id", "document_id", "collection_id"):
                await self._client.create_payload_index(
                    collection_name=name,
                    field_name=field,
                    field_schema=models.PayloadSchemaType.KEYWORD,
                )

    async def drop_collection(self, name: str) -> None:
        if await self._client.collection_exists(name):
            await self._client.delete_collection(name)

    async def upsert_chunks(self, collection: str, chunks: list[ChunkPayload]) -> None:
        points = [
            models.PointStruct(
                id=str(c.point_id),
                vector=c.vector,
                payload={
                    "project_id": str(c.project_id),
                    "document_id": str(c.document_id),
                    "collection_id": str(c.collection_id) if c.collection_id else None,
                    "chunk_index": c.chunk_index,
                    "filename": c.filename,
                    "text": c.text,
                    "heading_path": c.heading_path,
                    "page_no": c.page_no,
                    "source_url": c.source_url,
                },
            )
            for c in chunks
        ]
        await self._client.upsert(collection_name=collection, points=points, wait=True)

    async def delete_document(self, collection: str, document_id: uuid.UUID) -> None:
        await self._client.delete(
            collection_name=collection,
            points_selector=models.FilterSelector(
                filter=_document_filter(document_id=str(document_id))
            ),
            wait=True,
        )

    async def search(
        self,
        collection: str,
        vector: list[float],
        project_id: uuid.UUID,
        limit: int = 8,
        collection_ids: list[uuid.UUID] | None = None,
    ) -> list[SearchHit]:
        # Belt-and-Braces: zusätzlich zur Collection-Trennung nach Projekt filtern
        must: list[models.Condition] = [
            models.FieldCondition(key="project_id", match=models.MatchValue(value=str(project_id)))
        ]
        if collection_ids:
            must.append(
                models.FieldCondition(
                    key="collection_id",
                    match=models.MatchAny(any=[str(c) for c in collection_ids]),
                )
            )
        result = await self._client.query_points(
            collection_name=collection,
            query=vector,
            limit=limit,
            with_payload=True,
            query_filter=models.Filter(must=must),
        )
        hits: list[SearchHit] = []
        for point in result.points:
            payload: dict[str, Any] = point.payload or {}
            hits.append(
                SearchHit(
                    point_id=str(point.id),
                    score=point.score,
                    document_id=payload.get("document_id", ""),
                    chunk_index=payload.get("chunk_index", 0),
                    filename=payload.get("filename", ""),
                    text=payload.get("text", ""),
                    heading_path=payload.get("heading_path"),
                    page_no=payload.get("page_no"),
                    source_url=payload.get("source_url"),
                )
            )
        return hits


def _document_filter(document_id: str) -> models.Filter:
    return models.Filter(
        must=[models.FieldCondition(key="document_id", match=models.MatchValue(value=document_id))]
    )


def collection_name_for_project(project_id: uuid.UUID) -> str:
    return f"gd_{project_id.hex}"
