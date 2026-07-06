# SPDX-FileCopyrightText: 2026 GovDesk-Mitwirkende
#
# SPDX-License-Identifier: EUPL-1.2

"""Kommandozeile: govdesk serve | worker | migrate | createadmin."""

import argparse
import asyncio
import sys


def main() -> None:
    parser = argparse.ArgumentParser(prog="govdesk", description="GovDesk – Verwaltung")
    sub = parser.add_subparsers(dest="command", required=True)

    serve = sub.add_parser("serve", help="Webserver starten")
    serve.add_argument("--host", default="0.0.0.0")  # noqa: S104 — Container-Default
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--reload", action="store_true", help="Autoreload (Entwicklung)")

    sub.add_parser("worker", help="Job-Worker starten")
    sub.add_parser("migrate", help="Datenbank-Migrationen anwenden")

    createadmin = sub.add_parser("createadmin", help="Plattform-Admin anlegen (headless)")
    createadmin.add_argument("--username", required=True)
    createadmin.add_argument("--email", default=None)
    createadmin.add_argument(
        "--password",
        default=None,
        help="Wird ohne Angabe interaktiv abgefragt",
    )

    export = sub.add_parser("export", help="Projekt als ZIP-Archiv exportieren")
    export.add_argument("--project", required=True, help="Projekt-ID oder -Slug")
    export.add_argument("--out", required=True, help="Zieldatei (.zip)")

    imp = sub.add_parser("import", help="Projekt-Archiv importieren (neu einbetten)")
    imp.add_argument("--file", required=True, help="Archiv (.zip)")
    imp.add_argument("--owner", required=True, help="Benutzername des Eigentümers")

    args = parser.parse_args()

    if args.command == "serve":
        import uvicorn

        uvicorn.run(
            "govdesk.main:app",
            host=args.host,
            port=args.port,
            reload=args.reload,
            proxy_headers=True,
        )
    elif args.command == "worker":
        from govdesk.workers.app import run_worker

        asyncio.run(run_worker())
    elif args.command == "migrate":
        from govdesk.db.migrate import run_migrations

        run_migrations()
    elif args.command == "createadmin":
        from govdesk.users.service import create_admin_cli

        password = args.password
        if not password:
            import getpass

            password = getpass.getpass("Passwort: ")
            if getpass.getpass("Passwort (Wiederholung): ") != password:
                print("Passwörter stimmen nicht überein.", file=sys.stderr)
                raise SystemExit(1)
        asyncio.run(create_admin_cli(args.username, args.email, password))
    elif args.command == "export":
        asyncio.run(_export_cli(args.project, args.out))
    elif args.command == "import":
        asyncio.run(_import_cli(args.file, args.owner))


async def _export_cli(project_ref: str, out: str) -> None:
    import uuid
    from pathlib import Path

    from sqlalchemy import select

    from govdesk.db.models import Project
    from govdesk.db.session import get_session_factory
    from govdesk.porting import export_project_archive

    async with get_session_factory()() as db:
        project = None
        try:
            project = await db.get(Project, uuid.UUID(project_ref))
        except ValueError:
            project = (
                await db.execute(select(Project).where(Project.slug == project_ref))
            ).scalar_one_or_none()
        if project is None:
            print(f"Projekt „{project_ref}“ nicht gefunden.", file=sys.stderr)
            raise SystemExit(1)
        data = await export_project_archive(db, project)
    await asyncio.to_thread(Path(out).write_bytes, data)
    print(f"Exportiert: {out} ({len(data)} Bytes)")


async def _import_cli(file: str, owner: str) -> None:
    from pathlib import Path

    from sqlalchemy import select

    from govdesk.core.app_settings import get_runtime_config
    from govdesk.core.config import get_settings
    from govdesk.db.models import User
    from govdesk.db.session import get_session_factory
    from govdesk.porting import import_project_archive
    from govdesk.workers.app import queue
    from govdesk.workers.tasks import ingest_document

    data = await asyncio.to_thread(Path(file).read_bytes)
    async with get_session_factory()() as db:
        user = (await db.execute(select(User).where(User.username == owner))).scalar_one_or_none()
        if user is None:
            print(f"Benutzer „{owner}“ nicht gefunden.", file=sys.stderr)
            raise SystemExit(1)
        cfg = await get_runtime_config(db)
        project, doc_ids = await import_project_archive(
            db, user, data, cfg.embedding_model, get_settings().embedding_dimensions
        )
        await db.commit()
    async with queue.open_async():
        for did in doc_ids:
            await ingest_document.defer_async(document_id=str(did))
    print(f"Importiert: {project.name} — {len(doc_ids)} Dokument(e), Re-Ingest eingeplant.")


if __name__ == "__main__":
    main()
