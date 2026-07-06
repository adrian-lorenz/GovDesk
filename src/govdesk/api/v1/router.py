# SPDX-FileCopyrightText: 2026 GovDesk-Mitwirkende
#
# SPDX-License-Identifier: EUPL-1.2

"""Öffentliche REST-API v1 — plattformweite API-Keys, Projekt über den Pfad.

Alle Endpunkte liegen unter /api/v1/projects/{project_id}/…; der API-Key
authentifiziert und trägt die Scopes, das Projekt kommt aus dem Pfad.
"""

from fastapi import APIRouter

from govdesk.api.v1.crawl import router as crawl_router
from govdesk.api.v1.documents import router as documents_router
from govdesk.api.v1.search import router as search_router

router = APIRouter(prefix="/api/v1/projects/{project_id}")
router.include_router(documents_router)
router.include_router(search_router)
router.include_router(crawl_router)
