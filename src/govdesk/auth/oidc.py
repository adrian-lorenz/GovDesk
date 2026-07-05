# SPDX-FileCopyrightText: 2026 GovDesk-Mitwirkende
#
# SPDX-License-Identifier: EUPL-1.2

"""OIDC/Keycloak-Anbindung (authlib, Authorization Code + PKCE).

Nutzer werden über (issuer, subject) verknüpft; existiert keine Verknüpfung,
wird über die verifizierte E-Mail an ein bestehendes Konto gebunden, sonst
ein neues Konto provisioniert. Danach greift dieselbe Session-Mechanik wie
beim Passwort-Login.
"""

import logging
import re

from authlib.integrations.starlette_client import OAuth
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from govdesk.core.config import get_settings
from govdesk.db.models import OidcIdentity, User

logger = logging.getLogger(__name__)

_oauth: OAuth | None = None


def oidc_client():
    global _oauth
    settings = get_settings()
    if not settings.oidc_enabled or not settings.oidc_issuer:
        return None
    if _oauth is None:
        _oauth = OAuth()
        _oauth.register(
            name="keycloak",
            client_id=settings.oidc_client_id,
            client_secret=settings.oidc_client_secret,
            server_metadata_url=(
                f"{settings.oidc_issuer.rstrip('/')}/.well-known/openid-configuration"
            ),
            client_kwargs={"scope": "openid profile email", "code_challenge_method": "S256"},
        )
    return _oauth.keycloak


def _unique_username_base(claims: dict) -> str:
    raw = claims.get("preferred_username") or claims.get("email") or claims.get("sub") or "oidc"
    return re.sub(r"[^a-zA-Z0-9._@-]", "_", raw)[:140]


async def resolve_oidc_user(db: AsyncSession, claims: dict) -> User:
    """Identität auflösen: verknüpft → per E-Mail linken → provisionieren."""
    issuer = claims["iss"]
    subject = claims["sub"]

    identity = (
        await db.execute(
            select(OidcIdentity).where(
                OidcIdentity.issuer == issuer, OidcIdentity.subject == subject
            )
        )
    ).scalar_one_or_none()
    if identity is not None:
        user = await db.get(User, identity.user_id)
        if user is None or not user.is_active:
            raise PermissionError("Konto ist deaktiviert")
        return user

    email = (claims.get("email") or "").lower().strip()
    user = None
    if email and claims.get("email_verified"):
        user = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()

    if user is None:
        base = _unique_username_base(claims)
        username = base
        counter = 2
        while (
            await db.execute(select(User.id).where(User.username == username))
        ).scalar_one_or_none() is not None:
            username = f"{base}{counter}"
            counter += 1
        user = User(
            username=username,
            email=email or None,
            password_hash=None,  # reines OIDC-Konto
            display_name=claims.get("name"),
        )
        db.add(user)
        await db.flush()
        logger.info("OIDC: neues Konto provisioniert: %s", username)

    if not user.is_active:
        raise PermissionError("Konto ist deaktiviert")

    db.add(
        OidcIdentity(user_id=user.id, issuer=issuer, subject=subject, email_at_link=email or None)
    )
    await db.flush()
    return user
