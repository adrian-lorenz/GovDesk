# SPDX-FileCopyrightText: 2026 GovDesk-Mitwirkende
#
# SPDX-License-Identifier: EUPL-1.2

"""API-Keys plattformweit (project_id entfernen)

Revision: f1a2b3c4d5e6
Vorgänger: ec2aabd8009a
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f1a2b3c4d5e6"
down_revision: str | None = "ec2aabd8009a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(op.f("fk_api_keys_project_id_projects"), "api_keys", type_="foreignkey")
    op.drop_index(op.f("ix_api_keys_project_id"), table_name="api_keys")
    op.drop_column("api_keys", "project_id")


def downgrade() -> None:
    op.add_column("api_keys", sa.Column("project_id", sa.UUID(), nullable=True))
    op.create_index(op.f("ix_api_keys_project_id"), "api_keys", ["project_id"], unique=False)
    op.create_foreign_key(
        op.f("fk_api_keys_project_id_projects"),
        "api_keys",
        "projects",
        ["project_id"],
        ["id"],
        ondelete="CASCADE",
    )
