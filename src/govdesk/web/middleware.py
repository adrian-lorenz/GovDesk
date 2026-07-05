# SPDX-FileCopyrightText: 2026 GovDesk-Mitwirkende
#
# SPDX-License-Identifier: EUPL-1.2

"""Web-Middleware: Session-Auflösung, CSRF-Schutz, Setup-Weiterleitung."""

from fastapi import Request, Response
from fastapi.responses import RedirectResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from govdesk.auth.service import SESSION_COOKIE, resolve_session
from govdesk.core.app_settings import get_all_settings
from govdesk.db.session import get_session_factory
from govdesk.users.service import admin_exists

# Pfade ohne Session-/Setup-Logik
EXEMPT_PREFIXES = ("/static/", "/healthz", "/api/")
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


class WebSessionMiddleware(BaseHTTPMiddleware):
    """Löst die Session auf (request.state.user/csrf_token), prüft CSRF für
    unsichere Methoden und leitet vor Abschluss der Ersteinrichtung auf /setup."""

    def __init__(self, app) -> None:
        super().__init__(app)
        # Sobald ein Admin existiert, bleibt das so — Cache spart eine Query pro Request.
        self._setup_done = False

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        path = request.url.path
        if path.startswith(EXEMPT_PREFIXES):
            return await call_next(request)

        request.state.user = None
        request.state.csrf_token = None
        request.state.platform_name = "GovDesk"
        request.state.platform_subtitle = None

        async with get_session_factory()() as db:
            cookie = request.cookies.get(SESSION_COOKIE)
            if cookie:
                resolved = await resolve_session(db, cookie)
                if resolved is not None:
                    session, user = resolved
                    request.state.user = user
                    request.state.csrf_token = session.csrf_token
            if not self._setup_done:
                self._setup_done = await admin_exists(db)
            settings = await get_all_settings(db)
            request.state.platform_name = settings.get("platform_name") or "GovDesk"
            request.state.platform_subtitle = settings.get("platform_subtitle") or None
            await db.commit()

        # Ersteinrichtung erzwingen bzw. abgeschlossenes Setup sperren
        if not self._setup_done and not path.startswith("/setup"):
            return RedirectResponse("/setup", status_code=303)
        if self._setup_done and path.startswith("/setup"):
            return RedirectResponse("/", status_code=303)

        # CSRF: unsichere Methoden brauchen den Header der Session (hx-boost
        # schickt ihn bei allen Formularen mit; Body wird hier bewusst nie
        # gelesen, sonst wäre er für die Route konsumiert)
        if request.method not in SAFE_METHODS and request.state.user is not None:
            sent = request.headers.get("X-CSRF-Token")
            if not sent or sent != request.state.csrf_token:
                return Response("CSRF-Prüfung fehlgeschlagen", status_code=403)

        return await call_next(request)
