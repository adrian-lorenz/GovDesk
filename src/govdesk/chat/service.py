# SPDX-FileCopyrightText: 2026 GovDesk-Mitwirkende
#
# SPDX-License-Identifier: EUPL-1.2

"""Chat-Sitzungen und Nachrichten."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from govdesk.db.models import ChatMessage, ChatSession, MessageRole, Project, User


async def create_chat_session(
    db: AsyncSession, project: Project, user: User, chat_config_id: uuid.UUID | None = None
) -> ChatSession:
    session = ChatSession(project_id=project.id, user_id=user.id, chat_config_id=chat_config_id)
    db.add(session)
    await db.flush()
    return session


async def get_chat_session(
    db: AsyncSession, session_id: uuid.UUID, with_messages: bool = False
) -> ChatSession | None:
    query = select(ChatSession).where(ChatSession.id == session_id)
    if with_messages:
        query = query.options(selectinload(ChatSession.messages))
    result = await db.execute(query)
    return result.scalar_one_or_none()


async def chat_sessions_for_project(
    db: AsyncSession, project: Project, user: User
) -> list[ChatSession]:
    # Nur „echte" Chats: der Titel wird mit der ersten Nachricht gesetzt —
    # leere (ungenutzte) Sitzungen werden nicht gelistet/gespeichert.
    result = await db.execute(
        select(ChatSession)
        .where(
            ChatSession.project_id == project.id,
            ChatSession.user_id == user.id,
            ChatSession.title.isnot(None),
        )
        .order_by(ChatSession.updated_at.desc())
    )
    return list(result.scalars())


async def delete_empty_chat_sessions(db: AsyncSession, project: Project, user: User) -> None:
    """Räumt leere (nachrichtenlose) Chats des Nutzers auf — leere Chats
    sollen nicht dauerhaft gespeichert werden."""
    result = await db.execute(
        select(ChatSession).where(
            ChatSession.project_id == project.id,
            ChatSession.user_id == user.id,
            ChatSession.title.is_(None),
        )
    )
    for session in result.scalars():
        await db.delete(session)


async def delete_chat_session(db: AsyncSession, session: ChatSession) -> None:
    """Löscht eine Chat-Sitzung samt Nachrichten (Cascade)."""
    await db.delete(session)


async def add_message(
    db: AsyncSession,
    session: ChatSession,
    role: MessageRole,
    content: str,
    citations: list[dict] | None = None,
    model: str | None = None,
    model_knowledge_used: bool = False,
    model_chat_used: bool = False,
) -> ChatMessage:
    message = ChatMessage(
        session_id=session.id,
        role=role,
        content=content,
        citations=citations,
        model=model,
        model_knowledge_used=model_knowledge_used,
        model_chat_used=model_chat_used,
    )
    db.add(message)
    if session.title is None and role == MessageRole.USER:
        session.title = content[:80] + ("…" if len(content) > 80 else "")
    await db.flush()
    return message


async def last_message(db: AsyncSession, session_id: uuid.UUID) -> ChatMessage | None:
    result = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def history_for_llm(db: AsyncSession, session_id: uuid.UUID, limit: int = 12) -> list[dict]:
    """Letzte Nachrichten als LLM-Messages (ältere werden abgeschnitten)."""
    result = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.created_at.desc())
        .limit(limit)
    )
    messages = list(result.scalars())[::-1]
    return [{"role": m.role.value, "content": m.content} for m in messages]
