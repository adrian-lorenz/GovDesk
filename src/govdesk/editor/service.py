# SPDX-FileCopyrightText: 2026 GovDesk-Mitwirkende
#
# SPDX-License-Identifier: EUPL-1.2

"""Editor-Dokumente: Sichtbarkeit, Speichern mit Revision, Historie, Ordner."""

import uuid

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from govdesk.db.models import EditorDocument, EditorFolder, EditorRevision, User


class VersionConflictError(Exception):
    """Das Dokument wurde zwischenzeitlich von jemand anderem gespeichert."""

    def __init__(self, current: EditorDocument) -> None:
        self.current = current


def _visible_filter(user: User):
    """Nicht-private Dokumente sieht jeder; private nur der Ersteller."""
    return or_(EditorDocument.is_private.is_(False), EditorDocument.created_by == user.id)


async def list_documents(
    db: AsyncSession,
    project_id: uuid.UUID,
    user: User,
    folder_id: uuid.UUID | None = None,
    all_folders: bool = False,
) -> list[EditorDocument]:
    """Dokumente eines Projekts — standardmäßig nur die des angegebenen Ordners
    (None = oberste Ebene); all_folders=True liefert ordnerübergreifend alle."""
    query = select(EditorDocument).where(
        EditorDocument.project_id == project_id, _visible_filter(user)
    )
    if not all_folders:
        query = query.where(EditorDocument.folder_id == folder_id)
    result = await db.execute(query.order_by(EditorDocument.updated_at.desc()))
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


# ---------------------------------------------------------------------------
# Ordner der Dokumentenbibliothek
# ---------------------------------------------------------------------------


async def get_folder(
    db: AsyncSession, folder_id: uuid.UUID, project_id: uuid.UUID
) -> EditorFolder | None:
    folder = await db.get(EditorFolder, folder_id)
    if folder is None or folder.project_id != project_id:
        return None
    return folder


async def list_folders(
    db: AsyncSession, project_id: uuid.UUID, parent_id: uuid.UUID | None
) -> list[EditorFolder]:
    result = await db.execute(
        select(EditorFolder)
        .where(EditorFolder.project_id == project_id, EditorFolder.parent_id == parent_id)
        .order_by(EditorFolder.name)
    )
    return list(result.scalars())


async def create_folder(
    db: AsyncSession,
    project_id: uuid.UUID,
    user: User,
    name: str,
    parent_id: uuid.UUID | None,
) -> EditorFolder:
    folder = EditorFolder(
        project_id=project_id,
        name=name.strip()[:200] or "Neuer Ordner",
        parent_id=parent_id,
        created_by=user.id,
    )
    db.add(folder)
    await db.flush()
    return folder


async def folder_breadcrumbs(
    db: AsyncSession, folder: EditorFolder | None
) -> list[EditorFolder]:
    """Pfad von der Wurzel bis zum Ordner (für die Breadcrumb-Leiste)."""
    crumbs: list[EditorFolder] = []
    current = folder
    # Schutz vor (theoretisch unmöglichen) Zyklen: Tiefe begrenzen.
    for _ in range(50):
        if current is None:
            break
        crumbs.append(current)
        if current.parent_id is None:
            break
        current = await db.get(EditorFolder, current.parent_id)
    return list(reversed(crumbs))


async def is_descendant_folder(
    db: AsyncSession, folder: EditorFolder, candidate_ancestor_id: uuid.UUID
) -> bool:
    """True, wenn candidate_ancestor_id über folder liegt oder folder selbst ist —
    verhindert, dass ein Ordner in sich selbst verschoben wird."""
    current: EditorFolder | None = folder
    for _ in range(50):
        if current is None:
            return False
        if current.id == candidate_ancestor_id:
            return True
        if current.parent_id is None:
            return False
        current = await db.get(EditorFolder, current.parent_id)
    return False


async def delete_folder(db: AsyncSession, folder: EditorFolder) -> None:
    """Löscht einen Ordner; Inhalte (Dokumente + Unterordner) wandern in den
    Elternordner, damit nichts unbeabsichtigt verloren geht."""
    docs = await db.execute(select(EditorDocument).where(EditorDocument.folder_id == folder.id))
    for doc in docs.scalars():
        doc.folder_id = folder.parent_id
    subs = await db.execute(select(EditorFolder).where(EditorFolder.parent_id == folder.id))
    for sub in subs.scalars():
        sub.parent_id = folder.parent_id
    await db.flush()
    await db.delete(folder)


async def usernames_for(
    db: AsyncSession, user_ids: set[uuid.UUID | None]
) -> dict[uuid.UUID | None, str]:
    """ID→Benutzername-Auflösung für die Anzeige (Historie/„zuletzt von")."""
    ids = {i for i in user_ids if i is not None}
    if not ids:
        return {}
    rows = (await db.execute(select(User.id, User.username).where(User.id.in_(ids)))).all()
    return {uid: name for uid, name in rows}
