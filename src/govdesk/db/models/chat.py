# SPDX-FileCopyrightText: 2026 GovDesk-Mitwirkende
#
# SPDX-License-Identifier: EUPL-1.2

import enum
import uuid
from typing import Any

from sqlalchemy import Enum, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from govdesk.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class MessageRole(enum.StrEnum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class ChatConfig(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Konfigurierbare Chat-Profile pro Projekt (System-Prompt, Modell, Retrieval)."""

    __tablename__ = "chat_configs"

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(150))
    system_prompt: Mapped[str | None] = mapped_column(Text)
    # NULL = Plattform-Standardmodell
    model: Mapped[str | None] = mapped_column(String(120))
    temperature: Mapped[float] = mapped_column(default=0.2)
    top_k: Mapped[int] = mapped_column(default=4)
    rerank_enabled: Mapped[bool] = mapped_column(default=True)
    # Leer = alle Sammlungen des Projekts
    collection_ids: Mapped[list[uuid.UUID] | None] = mapped_column(ARRAY(PgUUID(as_uuid=True)))
    is_default: Mapped[bool] = mapped_column(default=False)


class ChatSession(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "chat_sessions"

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    chat_config_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("chat_configs.id", ondelete="SET NULL")
    )
    title: Mapped[str | None] = mapped_column(String(300))

    messages: Mapped[list[ChatMessage]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="ChatMessage.created_at",
    )


class ChatMessage(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "chat_messages"

    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("chat_sessions.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[MessageRole] = mapped_column(
        Enum(MessageRole, name="message_role", values_callable=lambda e: [m.value for m in e])
    )
    content: Mapped[str] = mapped_column(Text)
    citations: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    model: Mapped[str | None] = mapped_column(String(120))

    session: Mapped[ChatSession] = relationship(back_populates="messages")
