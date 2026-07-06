# SPDX-FileCopyrightText: 2026 GovDesk-Mitwirkende
#
# SPDX-License-Identifier: EUPL-1.2

"""Editor-Dokumente: Sichtbarkeit, Speichern mit Revision, Historie."""

import uuid

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from govdesk.db.models import EditorDocument, EditorRevision, User


class VersionConflictError(Exception):
    """Das Dokument wurde zwischenzeitlich von jemand anderem gespeichert."""

    def __init__(self, current: EditorDocument) -> None:
        self.current = current


def _visible_filter(user: User):
    """Nicht-private Dokumente sieht jeder; private nur der Ersteller."""
    return or_(EditorDocument.is_private.is_(False), EditorDocument.created_by == user.id)


async def list_documents(
    db: AsyncSession, project_id: uuid.UUID, user: User
) -> list[EditorDocument]:
    result = await db.execute(
        select(EditorDocument)
        .where(EditorDocument.project_id == project_id, _visible_filter(user))
        .order_by(EditorDocument.updated_at.desc())
    )
    return list(result.scalars())


async def get_document(
    db: AsyncSession, document_id: uuid.UUID, project_id: uuid.UUID, user: User
) -> EditorDocument | None:
    doc = await db.get(EditorDocument, document_id)
    if doc is None or doc.project_id != project_id:
        return None
    # Privat: nur Ersteller (oder Plattform-Admin).
    if doc.is_private and doc.created_by != user.id and not user.is_platform_admin:
        return None
    return doc


async def create_document(
    db: AsyncSession, project_id: uuid.UUID, user: User, title: str, is_private: bool
) -> EditorDocument:
    doc = EditorDocument(
        project_id=project_id,
        title=title.strip() or "Unbenanntes Dokument",
        content="",
        is_private=is_private,
        created_by=user.id,
        updated_by=user.id,
    )
    db.add(doc)
    await db.flush()
    db.add(
        EditorRevision(document_id=doc.id, version=doc.version, content="", author_id=user.id)
    )
    return doc


async def save_document(
    db: AsyncSession, doc: EditorDocument, user: User, content: str, base_version: int
) -> EditorDocument:
    """Speichert optimistisch: nur wenn die Basisversion noch aktuell ist."""
    if doc.version != base_version:
        raise VersionConflictError(doc)
    doc.version += 1
    doc.content = content
    doc.updated_by = user.id
    db.add(
        EditorRevision(
            document_id=doc.id, version=doc.version, content=content, author_id=user.id
        )
    )
    await db.flush()
    return doc


async def list_revisions(db: AsyncSession, document_id: uuid.UUID) -> list[EditorRevision]:
    result = await db.execute(
        select(EditorRevision)
        .where(EditorRevision.document_id == document_id)
        .order_by(EditorRevision.version.desc())
    )
    return list(result.scalars())


async def usernames_for(
    db: AsyncSession, user_ids: set[uuid.UUID | None]
) -> dict[uuid.UUID | None, str]:
    """ID→Benutzername-Auflösung für die Anzeige (Historie/„zuletzt von")."""
    ids = {i for i in user_ids if i is not None}
    if not ids:
        return {}
    rows = (await db.execute(select(User.id, User.username).where(User.id.in_(ids)))).all()
    return {uid: name for uid, name in rows}
