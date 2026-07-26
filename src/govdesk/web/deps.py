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

from govdesk.core.branding import DEFAULT_UI_SCALE

TEMPLATES_DIR = Path(__file__).parent / "templates"
STATIC_DIR = Path(__file__).parent / "static"
VERSIONED_ASSETS = (
    STATIC_DIR / "css" / "app.css",
    STATIC_DIR / "js" / "theme.js",
)

templates = Jinja2Templates(directory=TEMPLATES_DIR)


def _asset_version() -> str:
    """Ändert sich unmittelbar, wenn eigene CSS-/JS-Assets bearbeitet werden."""
    return str(max(path.stat().st_mtime_ns for path in VERSIONED_ASSETS))


# Fallback für Templates, die außerhalb von render() gerendert werden.
templates.env.globals["asset_v"] = _asset_version()


def render(
    request: Request,
    name: str,
    context: dict[str, Any] | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    theme_policy = getattr(request.state, "branding_theme_policy", "both")
    requested_theme = request.cookies.get("govdesk_theme", "light")
    if theme_policy in {"light", "dark"}:
        theme = theme_policy
    else:
        theme = requested_theme if requested_theme in {"light", "dark"} else "light"
    ctx: dict[str, Any] = {
        "asset_v": _asset_version(),
        "theme": theme,
        "theme_policy": theme_policy,
        "csrf_token": getattr(request.state, "csrf_token", None),
        "current_user": getattr(request.state, "user", None),
        "platform_name": getattr(request.state, "platform_name", "GovDesk"),
        "platform_subtitle": getattr(request.state, "platform_subtitle", None),
        "platform_logo_hash": getattr(request.state, "platform_logo_hash", None),
        "branding_primary_color": getattr(request.state, "branding_primary_color", "#3154b8"),
        "branding_primary_on_color": getattr(request.state, "branding_primary_on_color", "#ffffff"),
        "branding_accent_color": getattr(request.state, "branding_accent_color", "#0f7b6c"),
        "branding_ui_scale": getattr(request.state, "branding_ui_scale", DEFAULT_UI_SCALE),
        # Naiv (UTC) — passend zu den DB-Timestamps ohne Zeitzone
        "now": datetime.now(UTC).replace(tzinfo=None),
    }
    if context:
        ctx.update(context)
    return templates.TemplateResponse(request, name, ctx, status_code=status_code)
