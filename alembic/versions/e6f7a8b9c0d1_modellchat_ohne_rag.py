# SPDX-FileCopyrightText: 2026 GovDesk-Mitwirkende
#
# SPDX-License-Identifier: EUPL-1.2

"""Chat-Profilmodus für normalen Modellchat ohne RAG.

Revision: e6f7a8b9c0d1
Vorgänger: d4e5f6a7b8c9
"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "e6f7a8b9c0d1"
down_revision: str | None = "d4e5f6a7b8c9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "chat_configs",
        sa.Column(
            "retrieval_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )
    op.add_column(
        "chat_messages",
        sa.Column(
            "model_chat_used",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )

    connection = op.get_bind()
    project_ids = list(connection.execute(sa.text("SELECT id FROM projects")).scalars())
    for project_id in project_ids:
        connection.execute(
            sa.text(
                """
                INSERT INTO chat_configs (
                    id, project_id, name, system_prompt, model, temperature,
                    top_k, rerank_enabled, retrieval_enabled, collection_ids,
                    is_default, created_at, updated_at
                ) VALUES (
                    :id, :project_id, :name, :system_prompt, NULL, 0.4,
                    4, false, false, NULL, false, now(), now()
                )
                """
            ),
            {
                "id": uuid.uuid4(),
                "project_id": project_id,
                "name": "Allgemeiner Modellchat",
                "system_prompt": (
                    "Du bist ein hilfreicher Assistent für Behörden. Antworte auf Deutsch, "
                    "präzise, sachlich und transparent über Unsicherheiten."
                ),
            },
        )


def downgrade() -> None:
    op.execute(
        sa.text(
            """
            DELETE FROM chat_configs
            WHERE name = 'Allgemeiner Modellchat'
              AND retrieval_enabled = false
              AND is_default = false
            """
        )
    )
    op.drop_column("chat_messages", "model_chat_used")
    op.drop_column("chat_configs", "retrieval_enabled")
