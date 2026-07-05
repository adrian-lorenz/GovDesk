# SPDX-FileCopyrightText: 2026 GovDesk-Mitwirkende
#
# SPDX-License-Identifier: EUPL-1.2

"""App-Factory für GovDesk."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from govdesk.core.config import get_settings
from govdesk.db.session import dispose_engine, get_session_factory

STATIC_DIR = Path(__file__).parent / "web" / "static"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    get_settings().data_dir.mkdir(parents=True, exist_ok=True)
    # Job-Queue öffnen, damit Web-Requests Jobs einreihen können
    from govdesk.workers.app import queue

    async with queue.open_async():
        yield
    await dispose_engine()


def create_app() -> FastAPI:
    app = FastAPI(
        title="GovDesk",
        description="Souveräne KI/RAG-Plattform für Behörden",
        lifespan=lifespan,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        redoc_url=None,
    )

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/healthz", include_in_schema=False)
    async def healthz() -> dict[str, str]:
        try:
            async with get_session_factory()() as session:
                await session.execute(text("SELECT 1"))
            db_status = "ok"
        except Exception:
            db_status = "fehler"
        return {"status": "ok", "datenbank": db_status}

    from slowapi.errors import RateLimitExceeded
    from slowapi.extension import _rate_limit_exceeded_handler
    from starlette.middleware.sessions import SessionMiddleware

    from govdesk.api.v1.router import router as api_router
    from govdesk.core.ratelimit import limiter
    from govdesk.web.middleware import WebSessionMiddleware
    from govdesk.web.router import router as web_router
    from govdesk.web.security_headers import SecurityHeadersMiddleware

    app.state.limiter = limiter
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # type: ignore[arg-type]
    app.add_middleware(WebSessionMiddleware)
    # Signierte Cookie-Session nur für den OIDC-Handshake (state/nonce, authlib)
    settings = get_settings()
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.secret_key,
        session_cookie="govdesk_oidc",
        https_only=settings.cookie_secure,
        same_site="lax",
    )
    app.include_router(web_router)
    app.include_router(api_router)

    return app


app = create_app()
