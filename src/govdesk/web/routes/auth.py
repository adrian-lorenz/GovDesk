# SPDX-FileCopyrightText: 2026 GovDesk-Mitwirkende
#
# SPDX-License-Identifier: EUPL-1.2

import base64
import binascii
import logging
from typing import Annotated

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from govdesk.auth.deps import Db
from govdesk.auth.oidc import oidc_client, resolve_oidc_user
from govdesk.auth.service import SESSION_COOKIE, authenticate, create_session, destroy_session
from govdesk.core.app_settings import get_setting
from govdesk.core.audit import audit
from govdesk.core.config import get_settings
from govdesk.core.ratelimit import limiter
from govdesk.web.deps import render

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/branding/logo", response_class=Response)
async def branding_logo(db: Db) -> Response:
    encoded = await get_setting(db, "branding_logo_data")
    if not isinstance(encoded, str) or not encoded:
        raise HTTPException(status_code=404, detail="Kein Logo konfiguriert")
    try:
        data = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise HTTPException(status_code=404, detail="Logo nicht lesbar") from exc
    logo_hash = await get_setting(db, "branding_logo_hash", "")
    return Response(
        content=data,
        media_type="image/png",
        headers={
            "Cache-Control": "public, max-age=3600",
            "ETag": f'"{logo_hash}"',
        },
    )


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request) -> HTMLResponse:
    if getattr(request.state, "user", None) is not None:
        return RedirectResponse("/", status_code=303)  # type: ignore[return-value]
    settings = get_settings()
    return render(
        request,
        "auth/login.html",
        {
            "oidc_enabled": settings.oidc_enabled,
            "local_login_enabled": settings.local_login_enabled,
        },
    )


@router.get("/auth/oidc/login")
async def oidc_login(request: Request):
    client = oidc_client()
    if client is None:
        raise HTTPException(status_code=404, detail="OIDC ist nicht konfiguriert")
    redirect_uri = str(request.url_for("oidc_callback"))
    return await client.authorize_redirect(request, redirect_uri)


@router.get("/auth/oidc/callback")
async def oidc_callback(request: Request, db: Db):
    client = oidc_client()
    if client is None:
        raise HTTPException(status_code=404, detail="OIDC ist nicht konfiguriert")
    try:
        token = await client.authorize_access_token(request)
        claims = token.get("userinfo") or {}
        user = await resolve_oidc_user(db, claims)
    except PermissionError:
        return render(
            request,
            "auth/login.html",
            {
                "error": "Dieses Konto ist deaktiviert.",
                "oidc_enabled": True,
                "local_login_enabled": get_settings().local_login_enabled,
            },
            status_code=403,
        )
    except Exception:
        logger.exception("OIDC-Anmeldung fehlgeschlagen")
        return render(
            request,
            "auth/login.html",
            {
                "error": "OIDC-Anmeldung fehlgeschlagen — bitte erneut versuchen.",
                "oidc_enabled": True,
                "local_login_enabled": get_settings().local_login_enabled,
            },
            status_code=400,
        )
    ip = request.client.host if request.client else None
    await audit(db, "user.login_oidc", actor_user_id=user.id, ip=ip)
    _, cookie_value = await create_session(
        db, user, ip=ip, user_agent=request.headers.get("user-agent")
    )
    await db.commit()
    response = RedirectResponse("/", status_code=303)
    response.set_cookie(
        SESSION_COOKIE,
        cookie_value,
        httponly=True,
        samesite="lax",
        secure=get_settings().cookie_secure,
        max_age=get_settings().session_max_days * 24 * 3600,
    )
    return response


@router.post("/login")
@limiter.limit("5/minute")
async def login(
    request: Request,
    db: Db,
    username: Annotated[str, Form()],
    password: Annotated[str, Form()],
):
    if not get_settings().local_login_enabled:
        raise HTTPException(status_code=403, detail="Passwort-Anmeldung ist deaktiviert")
    ip = request.client.host if request.client else None
    user = await authenticate(db, username.strip(), password)
    if user is None:
        await audit(db, "user.login_failed", ip=ip, meta={"username": username.strip()[:150]})
        await db.commit()
        return render(
            request,
            "auth/login.html",
            {"error": "Anmeldung fehlgeschlagen — Benutzername oder Passwort falsch."},
            status_code=401,
        )
    await audit(db, "user.login", actor_user_id=user.id, ip=ip)
    _, cookie_value = await create_session(
        db,
        user,
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    await db.commit()
    response = RedirectResponse("/", status_code=303)
    response.set_cookie(
        SESSION_COOKIE,
        cookie_value,
        httponly=True,
        samesite="lax",
        secure=get_settings().cookie_secure,
        max_age=get_settings().session_max_days * 24 * 3600,
    )
    return response


@router.post("/logout")
async def logout(request: Request, db: Db) -> RedirectResponse:
    cookie = request.cookies.get(SESSION_COOKIE)
    if cookie:
        await destroy_session(db, cookie)
        await db.commit()
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(SESSION_COOKIE)
    return response
