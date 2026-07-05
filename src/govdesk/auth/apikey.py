# SPDX-FileCopyrightText: 2026 GovDesk-Mitwirkende
#
# SPDX-License-Identifier: EUPL-1.2

"""API-Key-Authentifizierung für /api/v1 (Header: Authorization: Bearer gd_…)."""

from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends, HTTPException, Request, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from govdesk.core.security import hash_token
from govdesk.db.models import ApiKey, Project
from govdesk.db.session import get_db

_bearer = HTTPBearer(auto_error=False, description="API-Key im Format gd_…")


class ApiKeyContext:
    def __init__(self, api_key: ApiKey, project: Project) -> None:
        self.api_key = api_key
        self.project = project


def require_api_key(*scopes: str):
    """Dependency-Factory: prüft Key, Ablauf, Widerruf und geforderte Scopes."""

    async def dependency(
        request: Request,
        credentials: Annotated[HTTPAuthorizationCredentials | None, Security(_bearer)],
        db: Annotated[AsyncSession, Depends(get_db)],
    ) -> ApiKeyContext:
        if credentials is None or not credentials.credentials.startswith("gd_"):
            raise HTTPException(
                status_code=401,
                detail="API-Key fehlt (Header: Authorization: Bearer gd_…)",
            )
        raw_key = credentials.credentials
        result = await db.execute(
            select(ApiKey, Project)
            .join(Project, ApiKey.project_id == Project.id)
            .where(ApiKey.key_hash == hash_token(raw_key))
        )
        row = result.first()
        if row is None:
            raise HTTPException(status_code=401, detail="Ungültiger API-Key")
        api_key, project = row

        now = datetime.now(UTC)
        if api_key.revoked_at is not None:
            raise HTTPException(status_code=401, detail="API-Key wurde widerrufen")
        if api_key.expires_at is not None and now > api_key.expires_at.replace(tzinfo=UTC):
            raise HTTPException(status_code=401, detail="API-Key ist abgelaufen")
        if project.is_archived:
            raise HTTPException(status_code=403, detail="Projekt ist archiviert")
        missing = [s for s in scopes if s not in api_key.scopes]
        if missing:
            raise HTTPException(
                status_code=403,
                detail=f"API-Key fehlt Berechtigung: {', '.join(missing)}",
            )

        api_key.last_used_at = now
        await db.commit()
        request.state.api_key_id = api_key.id
        return ApiKeyContext(api_key, project)

    return dependency
