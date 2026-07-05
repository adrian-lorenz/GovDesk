# SPDX-FileCopyrightText: 2026 GovDesk-Mitwirkende
#
# SPDX-License-Identifier: EUPL-1.2

"""Öffentliche REST-API v1 — Authentifizierung über projekt-gebundene API-Keys."""

from fastapi import APIRouter

from govdesk.api.v1.crawl import router as crawl_router
from govdesk.api.v1.documents import router as documents_router
from govdesk.api.v1.search import router as search_router

router = APIRouter(prefix="/api/v1")
router.include_router(documents_router)
router.include_router(search_router)
router.include_router(crawl_router)
