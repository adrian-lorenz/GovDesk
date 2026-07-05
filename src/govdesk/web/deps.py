# SPDX-FileCopyrightText: 2026 GovDesk-Mitwirkende
#
# SPDX-License-Identifier: EUPL-1.2

"""Template-Rendering mit gemeinsamen Kontextvariablen (Theme, CSRF, User)."""

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

TEMPLATES_DIR = Path(__file__).parent / "templates"

templates = Jinja2Templates(directory=TEMPLATES_DIR)


def render(
    request: Request,
    name: str,
    context: dict[str, Any] | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    ctx: dict[str, Any] = {
        "theme": request.cookies.get("govdesk_theme", "light"),
        "csrf_token": getattr(request.state, "csrf_token", None),
        "current_user": getattr(request.state, "user", None),
        "platform_name": getattr(request.state, "platform_name", "GovDesk"),
        "platform_subtitle": getattr(request.state, "platform_subtitle", None),
        # Naiv (UTC) — passend zu den DB-Timestamps ohne Zeitzone
        "now": datetime.now(UTC).replace(tzinfo=None),
    }
    if context:
        ctx.update(context)
    return templates.TemplateResponse(request, name, ctx, status_code=status_code)
