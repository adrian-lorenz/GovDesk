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


if __name__ == "__main__":
    main()
