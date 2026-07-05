# SPDX-FileCopyrightText: 2026 GovDesk-Mitwirkende
#
# SPDX-License-Identifier: EUPL-1.2

"""Migrationen anwenden: Alembic + procrastinate-Schema (idempotent)."""

import asyncio
from pathlib import Path

from alembic.config import Config

from alembic import command

REPO_ROOT = Path(__file__).resolve().parents[3]


def run_migrations() -> None:
    cfg = Config(str(REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(REPO_ROOT / "alembic"))
    command.upgrade(cfg, "head")
    asyncio.run(_apply_procrastinate_schema())
    print("Migrationen angewendet.")


async def _apply_procrastinate_schema() -> None:
    from procrastinate.exceptions import AlreadyEnqueued  # noqa: F401 — sanity import

    from govdesk.workers.app import queue

    async with queue.open_async():
        try:
            await queue.schema_manager.apply_schema_async()
        except Exception as exc:  # Schema existiert bereits
            if "already exists" not in str(exc):
                raise
