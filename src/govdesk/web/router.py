# SPDX-FileCopyrightText: 2026 GovDesk-Mitwirkende
#
# SPDX-License-Identifier: EUPL-1.2

"""Aggregiert alle Web-Routen (HTMX/Server-Rendered)."""

from fastapi import APIRouter

from govdesk.web.routes.admin import router as admin_router
from govdesk.web.routes.apikeys import router as apikeys_router
from govdesk.web.routes.auth import router as auth_router
from govdesk.web.routes.chat_configs import router as chat_configs_router
from govdesk.web.routes.chats import router as chats_router
from govdesk.web.routes.connectors import router as connectors_router
from govdesk.web.routes.crawler import router as crawler_router
from govdesk.web.routes.documents import router as documents_router
from govdesk.web.routes.home import router as home_router
from govdesk.web.routes.members import router as members_router
from govdesk.web.routes.projects import router as projects_router
from govdesk.web.routes.setup import router as setup_router

router = APIRouter(include_in_schema=False)
router.include_router(home_router)
router.include_router(auth_router)
router.include_router(setup_router)
router.include_router(admin_router)
router.include_router(projects_router)
router.include_router(members_router)
router.include_router(apikeys_router)
router.include_router(documents_router)
router.include_router(connectors_router)
router.include_router(chat_configs_router)
router.include_router(chats_router)
router.include_router(crawler_router)
