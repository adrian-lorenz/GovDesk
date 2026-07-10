# SPDX-FileCopyrightText: 2026 GovDesk-Mitwirkende
#
# SPDX-License-Identifier: EUPL-1.2

"""Projekt-Verwaltung."""

import re
import unicodedata
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from govdesk.db.models import Project, ProjectMember, ProjectRole, User
from govdesk.rag.vectorstore import VectorStore, collection_name_for_project


def _slugify(name: str) -> str:
    normalized = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", normalized.lower()).strip("-")
    return slug[:60] or "projekt"


async def _unique_slug(db: AsyncSession, name: str) -> str:
    base = _slugify(name)
    slug = base
    counter = 2
    while True:
        result = await db.execute(select(Project.id).where(Project.slug == slug))
        if result.scalar_one_or_none() is None:
            return slug
        slug = f"{base}-{counter}"
        counter += 1


async def create_project(
    db: AsyncSession,
    owner: User,
    name: str,
    description: str | None,
    embedding_model: str,
    embedding_dimensions: int,
) -> Project:
    project_id = uuid.uuid4()
    project = Project(
        id=project_id,
        name=name.strip(),
        slug=await _unique_slug(db, name),
        description=description,
        owner_id=owner.id,
        embedding_model=embedding_model,
        qdrant_collection=collection_name_for_project(project_id),
    )
    db.add(project)
    db.add(ProjectMember(project_id=project_id, user_id=owner.id, role=ProjectRole.OWNER))
    await db.flush()

    store = VectorStore()
    try:
        await store.ensure_collection(project.qdrant_collection, embedding_dimensions)
    finally:
        await store.close()
    return project


async def archive_project(db: AsyncSession, project: Project) -> None:
    """„Löschen mit Wissensbasis behalten": Projekt verschwindet aus allen
    Listen und ist nicht mehr nutzbar; Daten und Qdrant-Collection bleiben.
    Über den Archiv-Bereich wiederherstellbar."""
    project.is_archived = True
    await db.flush()


async def restore_project(db: AsyncSession, project: Project) -> None:
    project.is_archived = False
    await db.flush()


async def archived_projects(db: AsyncSession) -> list[Project]:
    result = await db.execute(
        select(Project).where(Project.is_archived).order_by(Project.updated_at.desc())
    )
    return list(result.scalars())


async def delete_project_permanently(db: AsyncSession, project: Project) -> None:
    """Endgültig löschen: Qdrant-Collection, gespeicherte Dateien und alle
    Datenbankzeilen (Kaskaden über die Fremdschlüssel)."""
    from govdesk.db.models import Document
    from govdesk.documents.storage import delete_file

    pfade = (
        await db.execute(
            select(Document.file_path).where(
                Document.project_id == project.id, Document.file_path.isnot(None)
            )
        )
    ).scalars()
    for pfad in pfade:
        delete_file(pfad)

    store = VectorStore()
    try:
        await store.drop_collection(project.qdrant_collection)
    finally:
        await store.close()

    await db.delete(project)
    await db.flush()


async def projects_for_user(db: AsyncSession, user: User) -> list[Project]:
    query = select(Project).where(~Project.is_archived).order_by(Project.created_at.desc())
    if not user.is_platform_admin:
        query = query.join(ProjectMember, ProjectMember.project_id == Project.id).where(
            ProjectMember.user_id == user.id
        )
    result = await db.execute(query)
    return list(result.scalars())
