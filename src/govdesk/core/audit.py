# SPDX-FileCopyrightText: 2026 GovDesk-Mitwirkende
#
# SPDX-License-Identifier: EUPL-1.2

"""Audit-Protokoll: append-only, für sicherheitsrelevante Aktionen."""

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from govdesk.db.models import AuditLog


async def audit(
    db: AsyncSession,
    action: str,
    actor_user_id: uuid.UUID | None = None,
    actor_api_key_id: uuid.UUID | None = None,
    project_id: uuid.UUID | None = None,
    target_type: str | None = None,
    target_id: str | None = None,
    ip: str | None = None,
    meta: dict[str, Any] | None = None,
) -> None:
    db.add(
        AuditLog(
            action=action,
            actor_user_id=actor_user_id,
            actor_api_key_id=actor_api_key_id,
            project_id=project_id,
            target_type=target_type,
            target_id=target_id,
            ip=ip,
            meta=meta,
        )
    )
