# SPDX-FileCopyrightText: 2026 GovDesk-Mitwirkende
#
# SPDX-License-Identifier: EUPL-1.2

"""procrastinate-App: Postgres-basierte Job-Queue (kein Redis nötig)."""

import procrastinate

from govdesk.core.config import get_settings


def create_procrastinate_app() -> procrastinate.App:
    return procrastinate.App(
        connector=procrastinate.PsycopgConnector(
            conninfo=get_settings().database_url_psycopg,
        ),
        import_paths=["govdesk.workers.tasks"],
    )


queue = create_procrastinate_app()


async def run_worker() -> None:
    async with queue.open_async():
        await queue.run_worker_async(concurrency=4)
