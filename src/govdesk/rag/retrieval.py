# SPDX-FileCopyrightText: 2026 GovDesk-Mitwirkende
#
# SPDX-License-Identifier: EUPL-1.2

"""Retrieval-Pipeline: Query → Embedding → Qdrant → Reranker → Kontext + Zitate."""

import logging
from dataclasses import dataclass

from govdesk.core.app_settings import RuntimeConfig
from govdesk.db.models import Project
from govdesk.rag.embeddings import embedding_provider_from_config
from govdesk.rag.reranker import RerankerClient
from govdesk.rag.vectorstore import SearchHit, VectorStore

logger = logging.getLogger(__name__)

# Kandidaten für den Reranker vs. finale Kontextgröße
CANDIDATES_WITH_RERANK = 24
TOP_N = 4
CONTEXT_TOKEN_BUDGET = 2400


@dataclass(frozen=True)
class Citation:
    number: int
    document_id: str
    filename: str
    heading_path: str | None
    page_no: int | None
    source_url: str | None
    score: float
    snippet: str

    def as_dict(self) -> dict:
        return {
            "number": self.number,
            "document_id": self.document_id,
            "filename": self.filename,
            "heading_path": self.heading_path,
            "page_no": self.page_no,
            "source_url": self.source_url,
            "score": round(self.score, 4),
            "snippet": self.snippet[:300],
        }


@dataclass(frozen=True)
class RetrievalResult:
    context: str
    citations: list[Citation]


async def retrieve(
    project: Project,
    query: str,
    cfg: RuntimeConfig,
    top_n: int = TOP_N,
    collection_ids: list | None = None,
    rerank: bool | None = None,
) -> RetrievalResult:
    use_rerank = cfg.reranker_enabled if rerank is None else (rerank and cfg.reranker_enabled)
    embedder = embedding_provider_from_config(cfg)
    vectors = await embedder.embed([query], model=project.embedding_model)

    store = VectorStore()
    try:
        limit = CANDIDATES_WITH_RERANK if use_rerank else max(top_n * 2, 8)
        hits = await store.search(
            collection=project.qdrant_collection,
            vector=vectors[0],
            project_id=project.id,
            limit=limit,
            collection_ids=collection_ids,
        )
    finally:
        await store.close()

    if not hits:
        return RetrievalResult(context="", citations=[])

    if use_rerank:
        hits = await _maybe_rerank(query, hits, cfg)
    hits = hits[:top_n]

    citations: list[Citation] = []
    context_parts: list[str] = []
    used_tokens = 0
    for number, hit in enumerate(hits, start=1):
        hit_tokens = len(hit.text) // 4
        if used_tokens + hit_tokens > CONTEXT_TOKEN_BUDGET and citations:
            break
        used_tokens += hit_tokens
        source = hit.heading_path or f"Seite {hit.page_no}" if hit.page_no else hit.heading_path
        label = f"{hit.filename}" + (f", {source}" if source else "")
        context_parts.append(f"[{number}] ({label})\n{hit.text}")
        citations.append(
            Citation(
                number=number,
                document_id=hit.document_id,
                filename=hit.filename,
                heading_path=hit.heading_path,
                page_no=hit.page_no,
                source_url=hit.source_url,
                score=hit.score,
                snippet=hit.text,
            )
        )

    return RetrievalResult(context="\n\n".join(context_parts), citations=citations)


async def _maybe_rerank(query: str, hits: list[SearchHit], cfg: RuntimeConfig) -> list[SearchHit]:
    if len(hits) <= 1:
        return hits
    client = RerankerClient(cfg.reranker_url)
    try:
        ranking = await client.rerank(query, [h.text for h in hits])
    except Exception:
        # Reranker nicht erreichbar → Vektor-Ranking beibehalten statt Fehler
        logger.warning("Reranker nicht erreichbar — nutze reines Vektor-Ranking", exc_info=True)
        return hits
    reranked = []
    for index, score in ranking:
        hit = hits[index]
        reranked.append(
            SearchHit(
                point_id=hit.point_id,
                score=score,
                document_id=hit.document_id,
                chunk_index=hit.chunk_index,
                filename=hit.filename,
                text=hit.text,
                heading_path=hit.heading_path,
                page_no=hit.page_no,
                source_url=hit.source_url,
            )
        )
    return reranked
