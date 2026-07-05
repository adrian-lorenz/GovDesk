# SPDX-FileCopyrightText: 2026 GovDesk-Mitwirkende
#
# SPDX-License-Identifier: EUPL-1.2

"""Login, Logout und Session-Verwaltung (serverseitig, sofort widerrufbar)."""

from datetime import UTC, datetime, timedelta

from itsdangerous import BadSignature, URLSafeSerializer
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from govdesk.core.config import get_settings
from govdesk.core.security import (
    hash_password,
    hash_token,
    new_csrf_token,
    new_token,
    password_needs_rehash,
    verify_password,
)
from govdesk.db.models import AuthSession, User

SESSION_COOKIE = "govdesk_session"


def _serializer() -> URLSafeSerializer:
    return URLSafeSerializer(get_settings().secret_key, salt="session")


async def authenticate(db: AsyncSession, username: str, password: str) -> User | None:
    result = await db.execute(select(User).where(User.username == username))
    user = result.scalar_one_or_none()
    if user is None or not user.is_active or user.password_hash is None:
        return None
    if not verify_password(user.password_hash, password):
        return None
    if password_needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)
    return user


async def create_session(
    db: AsyncSession,
    user: User,
    ip: str | None = None,
    user_agent: str | None = None,
) -> tuple[AuthSession, str]:
    """Legt eine Session an und liefert (Session, Cookie-Wert)."""
    settings = get_settings()
    token = new_token()
    session = AuthSession(
        user_id=user.id,
        token_hash=hash_token(token),
        csrf_token=new_csrf_token(),
        expires_at=datetime.now(UTC) + timedelta(days=settings.session_max_days),
        last_seen_at=datetime.now(UTC),
        ip=ip,
        user_agent=(user_agent or "")[:400] or None,
    )
    db.add(session)
    user.last_login_at = datetime.now(UTC)
    await db.flush()
    return session, _serializer().dumps(token)


async def resolve_session(db: AsyncSession, cookie_value: str) -> tuple[AuthSession, User] | None:
    """Cookie → Session + User, mit Idle- und Absolut-Ablauf."""
    try:
        token = _serializer().loads(cookie_value)
    except BadSignature:
        return None

    result = await db.execute(
        select(AuthSession, User)
        .join(User, AuthSession.user_id == User.id)
        .where(AuthSession.token_hash == hash_token(token))
    )
    row = result.first()
    if row is None:
        return None
    session, user = row

    now = datetime.now(UTC)
    settings = get_settings()
    expires_at = session.expires_at.replace(tzinfo=UTC)
    last_seen = (session.last_seen_at or session.created_at).replace(tzinfo=UTC)
    if not user.is_active or now > expires_at:
        await db.delete(session)
        return None
    if now - last_seen > timedelta(hours=settings.session_idle_hours):
        await db.delete(session)
        return None

    session.last_seen_at = now
    return session, user


async def destroy_session(db: AsyncSession, cookie_value: str) -> None:
    try:
        token = _serializer().loads(cookie_value)
    except BadSignature:
        return
    await db.execute(delete(AuthSession).where(AuthSession.token_hash == hash_token(token)))
