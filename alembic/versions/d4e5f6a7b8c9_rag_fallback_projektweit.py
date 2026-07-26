# SPDX-FileCopyrightText: 2026 GovDesk-Mitwirkende
#
# SPDX-License-Identifier: EUPL-1.2

"""Projektweiter RAG-Fallback und Kennzeichnung von Modellwissen.

Revision: d4e5f6a7b8c9
Vorgänger: c3d1e8f7a201
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "d4e5f6a7b8c9"
down_revision: str | None = "c3d1e8f7a201"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "projects",
        sa.Column(
            "rag_fallback_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "chat_messages",
        sa.Column(
            "model_knowledge_used",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("chat_messages", "model_knowledge_used")
    op.drop_column("projects", "rag_fallback_enabled")
