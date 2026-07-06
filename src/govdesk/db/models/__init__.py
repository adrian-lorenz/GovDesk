# SPDX-FileCopyrightText: 2026 GovDesk-Mitwirkende
#
# SPDX-License-Identifier: EUPL-1.2

"""Alle Modelle importieren, damit Alembic/Base.metadata sie kennt."""

from govdesk.db.models.apikey import API_SCOPES, ApiKey
from govdesk.db.models.audit import AuditLog
from govdesk.db.models.chat import ChatConfig, ChatMessage, ChatSession, MessageRole
from govdesk.db.models.connector import (
    ConnectorItem,
    ConnectorJob,
    ConnectorJobStatus,
    ConnectorSource,
)
from govdesk.db.models.crawler import (
    CrawlJob,
    CrawlJobStatus,
    CrawlMode,
    CrawlPage,
    CrawlSource,
)
from govdesk.db.models.document import (
    Collection,
    Document,
    DocumentChunk,
    DocumentSource,
    DocumentStatus,
)
from govdesk.db.models.project import ROLE_ORDER, Project, ProjectMember, ProjectRole
from govdesk.db.models.settings import AppSetting
from govdesk.db.models.user import AuthSession, OidcIdentity, User

__all__ = [
    "API_SCOPES",
    "ROLE_ORDER",
    "ApiKey",
    "AppSetting",
    "AuditLog",
    "AuthSession",
    "ChatConfig",
    "ChatMessage",
    "ChatSession",
    "Collection",
    "ConnectorItem",
    "ConnectorJob",
    "ConnectorJobStatus",
    "ConnectorSource",
    "CrawlJob",
    "CrawlJobStatus",
    "CrawlMode",
    "CrawlPage",
    "CrawlSource",
    "Document",
    "DocumentChunk",
    "DocumentSource",
    "DocumentStatus",
    "MessageRole",
    "OidcIdentity",
    "Project",
    "ProjectMember",
    "ProjectRole",
    "User",
]
