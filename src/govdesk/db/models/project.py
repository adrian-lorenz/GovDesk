# SPDX-FileCopyrightText: 2026 GovDesk-Mitwirkende
#
# SPDX-License-Identifier: EUPL-1.2

import enum
import uuid

from sqlalchemy import Boolean, Enum, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from govdesk.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class ProjectRole(enum.StrEnum):
    OWNER = "owner"
    ADMIN = "admin"
    EDITOR = "editor"
    VIEWER = "viewer"


# Rangfolge für "mindestens Rolle X"-Prüfungen
ROLE_ORDER = {
    ProjectRole.VIEWER: 0,
    ProjectRole.EDITOR: 1,
    ProjectRole.ADMIN: 2,
    ProjectRole.OWNER: 3,
}


class Project(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "projects"

    name: Mapped[str] = mapped_column(String(200))
    slug: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    description: Mapped[str | None] = mapped_column(Text)
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    # Pro Projekt eingefroren — Wechsel erfordert kompletten Neuaufbau der Collection
    embedding_model: Mapped[str] = mapped_column(String(120))
    qdrant_collection: Mapped[str] = mapped_column(String(120), unique=True)
    is_archived: Mapped[bool] = mapped_column(default=False)
    # Sicherer Standard: Ohne passende Projektquelle keine Antwort aus Modellwissen.
    rag_fallback_enabled: Mapped[bool] = mapped_column(Boolean, default=False)

    members: Mapped[list[ProjectMember]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )


class ProjectMember(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "project_members"
    __table_args__ = (UniqueConstraint("project_id", "user_id"),)

    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    role: Mapped[ProjectRole] = mapped_column(
        Enum(ProjectRole, name="project_role", values_callable=lambda e: [m.value for m in e])
    )

    project: Mapped[Project] = relationship(back_populates="members")
