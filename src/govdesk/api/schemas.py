# SPDX-FileCopyrightText: 2026 GovDesk-Mitwirkende
#
# SPDX-License-Identifier: EUPL-1.2

"""Pydantic-Schemas der öffentlichen REST-API."""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class DocumentOut(BaseModel):
    id: uuid.UUID
    filename: str
    status: str
    source_type: str
    size_bytes: int | None
    chunk_count: int
    error: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class DocumentListOut(BaseModel):
    documents: list[DocumentOut]


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000, description="Suchanfrage")
    top_k: int = Field(default=5, ge=1, le=20)
    rerank: bool = True


class SearchHitOut(BaseModel):
    document_id: str
    filename: str
    heading_path: str | None
    page_no: int | None
    source_url: str | None
    score: float
    text: str


class SearchResponse(BaseModel):
    hits: list[SearchHitOut]


class ErrorOut(BaseModel):
    detail: str
