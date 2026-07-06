# SPDX-FileCopyrightText: 2026 GovDesk-Mitwirkende
#
# SPDX-License-Identifier: EUPL-1.2

"""Gemeinsamer Kontext für das Projekt-Seitenmenü (projects/_layout.html)."""

from typing import Any

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from govdesk.auth.deps import has_min_role
from govdesk.connectors.service import available_connectors
from govdesk.core.app_settings import get_setting
from govdesk.db.models import Project, ProjectRole, User

# Projekt-Sektionen, deren Sichtbarkeit für „normale" Mitglieder (Bearbeiter/
# Betrachter, nicht Projekt-Admin und nicht Plattform-Admin) konfigurierbar ist.
# Chat ist immer sichtbar, Mitglieder nur für Admins.
MEMBER_SECTIONS = {
    "editor": "Dokumente",
    "dokumente": "Wissensbasis",
    "crawler": "Internet-Agent",
    "connectors": "Connectoren",
    "chat-configs": "Chat-Profile",
    "retrieval": "Retrieval-Test",
}
VISIBILITY_SETTING_KEY = "member_visible_sections"


async def visible_member_sections(db: AsyncSession) -> set[str]:
    """Für normale Mitglieder freigegebene Sektionen (Default: alle)."""
    stored = await get_setting(db, VISIBILITY_SETTING_KEY, None)
    if not isinstance(stored, list):
        return set(MEMBER_SECTIONS)  # noch nicht konfiguriert → alles sichtbar
    return {s for s in stored if s in MEMBER_SECTIONS}


async def is_section_visible(db: AsyncSession, project: Project, user: User, section: str) -> bool:
    """Ob dem Nutzer die Sektion angezeigt werden darf (privilegiert → immer)."""
    if user.is_platform_admin or await has_min_role(db, project, user, ProjectRole.ADMIN):
        return True
    return section in await visible_member_sections(db)


async def project_menu_context(
    db: AsyncSession, project: Project, user: User, active: str
) -> dict[str, Any]:
    """Rollen + Sichtbarkeits-Flags für das Projekt-Seitenmenü.

    `active` markiert den aktiven Menüpunkt. `sichtbar` ist die Menge der
    Sektionen, die diesem Nutzer angezeigt werden dürfen — privilegierte Nutzer
    (Projekt-Admin+ oder Plattform-Admin) sehen alles, normale Mitglieder nur die
    plattformweit freigegebenen.
    """
    can_manage = await has_min_role(db, project, user, ProjectRole.ADMIN)
    privileged = can_manage or user.is_platform_admin
    sichtbar = set(MEMBER_SECTIONS) if privileged else await visible_member_sections(db)
    return {
        "project": project,
        "active": active,
        "can_edit": await has_min_role(db, project, user, ProjectRole.EDITOR),
        "can_manage": can_manage,
        "connectors_available": bool(await available_connectors(db)),
        "sichtbar": sichtbar,
        "privileged": privileged,
    }


async def ensure_section_visible(
    db: AsyncSession, project: Project, user: User, section: str
) -> None:
    """Serverseitige Absicherung: 403, wenn die Sektion für diesen Nutzer verborgen ist."""
    if not await is_section_visible(db, project, user, section):
        raise HTTPException(status_code=403, detail="Dieser Bereich ist nicht freigegeben.")
