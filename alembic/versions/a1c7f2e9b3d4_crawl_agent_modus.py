# SPDX-FileCopyrightText: 2026 GovDesk-Mitwirkende
#
# SPDX-License-Identifier: EUPL-1.2

"""Crawl-Agent-Modus: topic-Feld + Enum-Wert 'agent'

Revision: a1c7f2e9b3d4
Vorgänger: 184e09a2d971
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'a1c7f2e9b3d4'
down_revision: str | None = '184e09a2d971'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('crawl_sources', sa.Column('topic', sa.Text(), nullable=True))
    # Neuer Modus für den LLM-geführten Agent. ADD VALUE läuft ab PG12 auch
    # innerhalb einer Transaktion; IF NOT EXISTS macht die Migration idempotent.
    op.execute("ALTER TYPE crawl_mode ADD VALUE IF NOT EXISTS 'agent'")


def downgrade() -> None:
    op.drop_column('crawl_sources', 'topic')
    # Hinweis: PostgreSQL kann einzelne Enum-Werte nicht entfernen; 'agent'
    # bleibt im Typ crawl_mode bestehen (harmlos, da ungenutzt).
