# SPDX-FileCopyrightText: 2026 GovDesk-Mitwirkende
#
# SPDX-License-Identifier: EUPL-1.2

"""editor ordner

Revision: c3d1e8f7a201
Vorgänger: aad90a83ae77
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = 'c3d1e8f7a201'
down_revision: str | None = 'aad90a83ae77'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('editor_folders',
    sa.Column('project_id', sa.UUID(), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('parent_id', sa.UUID(), nullable=True),
    sa.Column('created_by', sa.UUID(), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], name=op.f('fk_editor_folders_created_by_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['parent_id'], ['editor_folders.id'], name=op.f('fk_editor_folders_parent_id_editor_folders'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], name=op.f('fk_editor_folders_project_id_projects'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_editor_folders'))
    )
    op.create_index(op.f('ix_editor_folders_project_id'), 'editor_folders', ['project_id'], unique=False)
    op.create_index(op.f('ix_editor_folders_parent_id'), 'editor_folders', ['parent_id'], unique=False)
    op.add_column('editor_documents', sa.Column('folder_id', sa.UUID(), nullable=True))
    op.create_index(op.f('ix_editor_documents_folder_id'), 'editor_documents', ['folder_id'], unique=False)
    op.create_foreign_key(
        op.f('fk_editor_documents_folder_id_editor_folders'),
        'editor_documents', 'editor_folders', ['folder_id'], ['id'], ondelete='SET NULL',
    )


def downgrade() -> None:
    op.drop_constraint(op.f('fk_editor_documents_folder_id_editor_folders'), 'editor_documents', type_='foreignkey')
    op.drop_index(op.f('ix_editor_documents_folder_id'), table_name='editor_documents')
    op.drop_column('editor_documents', 'folder_id')
    op.drop_index(op.f('ix_editor_folders_parent_id'), table_name='editor_folders')
    op.drop_index(op.f('ix_editor_folders_project_id'), table_name='editor_folders')
    op.drop_table('editor_folders')
