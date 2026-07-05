# SPDX-FileCopyrightText: 2026 GovDesk-Mitwirkende
#
# SPDX-License-Identifier: EUPL-1.2

"""REST-API: Retrieval-Suche (ohne LLM) über die Projekt-Dokumente."""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from govdesk.api.schemas import SearchHitOut, SearchRequest, SearchResponse
from govdesk.auth.apikey import ApiKeyContext, require_api_key
from govdesk.core.app_settings import get_runtime_config
from govdesk.db.session import get_db
from govdesk.rag.retrieval import retrieve

router = APIRouter(prefix="/search", tags=["Suche"])

Db = Annotated[AsyncSession, Depends(get_db)]
SearchKey = Annotated[ApiKeyContext, Depends(require_api_key("search:read"))]


@router.post("", response_model=SearchResponse, summary="Semantische Suche mit Reranking")
async def api_search(ctx: SearchKey, db: Db, body: SearchRequest) -> SearchResponse:
    cfg = await get_runtime_config(db)
    result = await retrieve(ctx.project, body.query, cfg, top_n=body.top_k, rerank=body.rerank)
    return SearchResponse(
        hits=[
            SearchHitOut(
                document_id=c.document_id,
                filename=c.filename,
                heading_path=c.heading_path,
                page_no=c.page_no,
                source_url=c.source_url,
                score=c.score,
                text=c.snippet,
            )
            for c in result.citations
        ]
    )
