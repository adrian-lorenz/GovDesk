# SPDX-FileCopyrightText: 2026 GovDesk-Mitwirkende
#
# SPDX-License-Identifier: EUPL-1.2

"""Demo-Daten: Admin, Projekt und ein Beispieldokument mit Ingestion.

Nutzung:  uv run python scripts/seed.py
Idempotent — vorhandene Objekte werden nicht dupliziert.
"""

import asyncio
import sys
from pathlib import Path

from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

ADMIN_USER = "admin"
ADMIN_PASSWORT = "GovDesk-Demo-2026!"
PROJEKT_NAME = "Demo: Stadtbibliothek"
FIXTURE = Path(__file__).parent.parent / "tests" / "fixtures" / "mustersatzung.txt"


async def main() -> None:
    from govdesk.core.app_settings import get_runtime_config
    from govdesk.core.config import get_settings
    from govdesk.db.models import Document, Project, User
    from govdesk.db.session import get_session_factory
    from govdesk.documents.service import create_document, enqueue_ingest
    from govdesk.projects.service import create_project
    from govdesk.users.service import create_user
    from govdesk.workers.app import queue

    async with get_session_factory()() as db:
        admin = (
            await db.execute(select(User).where(User.username == ADMIN_USER))
        ).scalar_one_or_none()
        if admin is None:
            admin = await create_user(db, ADMIN_USER, ADMIN_PASSWORT, is_platform_admin=True)
            print(f"Admin angelegt: {ADMIN_USER} / {ADMIN_PASSWORT}")
        else:
            print("Admin existiert bereits")

        project = (
            await db.execute(select(Project).where(Project.name == PROJEKT_NAME))
        ).scalar_one_or_none()
        if project is None:
            cfg = await get_runtime_config(db)
            project = await create_project(
                db,
                owner=admin,
                name=PROJEKT_NAME,
                description="Automatisch angelegtes Demo-Projekt",
                embedding_model=cfg.embedding_model,
                embedding_dimensions=get_settings().embedding_dimensions,
            )
            print(f"Projekt angelegt: {PROJEKT_NAME}")

        existing_doc = (
            await db.execute(select(Document.id).where(Document.project_id == project.id).limit(1))
        ).scalar_one_or_none()
        document = None
        if existing_doc is None and FIXTURE.exists():
            document = await create_document(
                db,
                project,
                filename=FIXTURE.name,
                data=FIXTURE.read_bytes(),
                content_type="text/plain",
            )
            print(f"Dokument angelegt: {FIXTURE.name}")
        await db.commit()

        if document is not None:
            async with queue.open_async():
                await enqueue_ingest(document)
            print("Ingestion eingereiht — Worker verarbeitet das Dokument.")

    print("Seed abgeschlossen.")


if __name__ == "__main__":
    asyncio.run(main())
