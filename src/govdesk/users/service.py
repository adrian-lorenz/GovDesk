# SPDX-FileCopyrightText: 2026 GovDesk-Mitwirkende
#
# SPDX-License-Identifier: EUPL-1.2

"""Nutzerverwaltung."""

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from govdesk.core.security import hash_password
from govdesk.db.models import User
from govdesk.db.session import get_session_factory


async def admin_exists(db: AsyncSession) -> bool:
    result = await db.execute(select(exists().where(User.is_platform_admin, User.is_active)))
    return bool(result.scalar())


async def create_user(
    db: AsyncSession,
    username: str,
    password: str | None,
    email: str | None = None,
    display_name: str | None = None,
    is_platform_admin: bool = False,
) -> User:
    user = User(
        username=username.strip(),
        email=email.strip().lower() if email else None,
        password_hash=hash_password(password) if password else None,
        display_name=display_name,
        is_platform_admin=is_platform_admin,
    )
    db.add(user)
    await db.flush()
    return user


async def create_admin_cli(username: str, email: str | None, password: str) -> None:
    """Headless-Admin-Anlage für Automatisierung/Air-Gap (Alternative zum Wizard)."""
    async with get_session_factory()() as db:
        user = await create_user(db, username, password, email, is_platform_admin=True)
        await db.commit()
        print(f"Plattform-Admin angelegt: {user.username}")
