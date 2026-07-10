# SPDX-FileCopyrightText: 2026 GovDesk-Mitwirkende
#
# SPDX-License-Identifier: EUPL-1.2

import uuid
from typing import Annotated

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from sqlalchemy import select

from govdesk.auth.deps import CurrentUser, Db, ProjectViewer, has_min_role
from govdesk.chat.service import (
    add_message,
    chat_sessions_for_project,
    create_chat_session,
    delete_chat_session,
    delete_empty_chat_sessions,
    get_chat_session,
    last_message,
)
from govdesk.chat.streaming import render_markdown, stream_answer
from govdesk.chat.zusammenfassung import PLATZHALTER_HTML, transcript_for
from govdesk.core.audit import audit
from govdesk.db.models import ChatConfig, MessageRole, ProjectRole
from govdesk.editor.service import create_document as create_editor_document
from govdesk.editor.service import save_document as save_editor_document
from govdesk.web.deps import render
from govdesk.web.project_layout import is_section_visible

router = APIRouter()


async def _own_session(db: Db, session_id: uuid.UUID, project, user):
    session = await get_chat_session(db, session_id, with_messages=True)
    if session is None or session.project_id != project.id or session.user_id != user.id:
        raise HTTPException(status_code=404, detail="Chat nicht gefunden")
    return session


@router.post("/projects/{project_id}/chats")
async def chat_create(
    project: ProjectViewer,
    user: CurrentUser,
    db: Db,
    chat_config_id: Annotated[str, Form()] = "",
) -> RedirectResponse:
    config_id = None
    if chat_config_id:
        config = await db.get(ChatConfig, uuid.UUID(chat_config_id))
        if config is None or config.project_id != project.id:
            raise HTTPException(status_code=404, detail="Chat-Profil nicht gefunden")
        config_id = config.id
    else:
        default = (
            await db.execute(
                select(ChatConfig).where(ChatConfig.project_id == project.id, ChatConfig.is_default)
            )
        ).scalar_one_or_none()
        config_id = default.id if default else None
    # Vorher ungenutzte leere Chats entfernen, damit sie sich nicht anhäufen.
    await delete_empty_chat_sessions(db, project, user)
    session = await create_chat_session(db, project, user, chat_config_id=config_id)
    await db.commit()
    return RedirectResponse(f"/projects/{project.id}/chats/{session.id}", status_code=303)


@router.post("/projects/{project_id}/chats/{chat_id}/delete")
async def chat_delete(
    project: ProjectViewer,
    user: CurrentUser,
    db: Db,
    chat_id: uuid.UUID,
) -> RedirectResponse:
    session = await _own_session(db, chat_id, project, user)
    await delete_chat_session(db, session)
    # Nach dem Löschen direkt einen neuen Chat starten (nicht zurück zum Projekt).
    await delete_empty_chat_sessions(db, project, user)
    neu = await create_chat_session(db, project, user)
    await db.commit()
    return RedirectResponse(f"/projects/{project.id}/chats/{neu.id}", status_code=303)


@router.get("/projects/{project_id}/chats/{chat_id}", response_class=HTMLResponse)
async def chat_page(
    request: Request,
    project: ProjectViewer,
    user: CurrentUser,
    db: Db,
    chat_id: uuid.UUID,
) -> HTMLResponse:
    session = await _own_session(db, chat_id, project, user)
    messages = [
        {
            "role": m.role.value,
            "content": m.content,
            "html": render_markdown(m.content) if m.role == MessageRole.ASSISTANT else None,
            "citations": m.citations or [],
        }
        for m in session.messages
    ]
    chats = await chat_sessions_for_project(db, project, user)
    can_edit = await has_min_role(db, project, user, ProjectRole.EDITOR)
    editor_visible = await is_section_visible(db, project, user, "editor")
    return render(
        request,
        "chats/chat.html",
        {
            "project": project,
            "chat": session,
            "messages": messages,
            "chats": chats,
            "can_edit": can_edit,
            "editor_visible": editor_visible,
        },
    )


@router.post("/projects/{project_id}/chats/{chat_id}/messages", response_class=HTMLResponse)
async def chat_message(
    request: Request,
    project: ProjectViewer,
    user: CurrentUser,
    db: Db,
    chat_id: uuid.UUID,
    frage: Annotated[str, Form()],
) -> HTMLResponse:
    session = await _own_session(db, chat_id, project, user)
    frage = frage.strip()
    if not frage:
        raise HTTPException(status_code=422, detail="Leere Nachricht")
    await add_message(db, session, MessageRole.USER, frage)
    await db.commit()
    return render(
        request,
        "partials/_chat_austausch.html",
        {"project": project, "chat": session, "frage": frage},
    )


@router.post("/projects/{project_id}/chats/{chat_id}/als-dokument")
async def chat_to_document(
    project: ProjectViewer, user: CurrentUser, db: Db, chat_id: uuid.UUID
) -> RedirectResponse:
    """Fasst den Chat per KI zusammen und legt ein bearbeitbares Editor-Dokument an."""
    if not await has_min_role(db, project, user, ProjectRole.EDITOR):
        raise HTTPException(status_code=403, detail="Bearbeiter-Rolle erforderlich")
    session = await _own_session(db, chat_id, project, user)
    if not transcript_for(session).strip():
        raise HTTPException(status_code=422, detail="Der Chat enthält noch keine Nachrichten.")

    # Die eigentliche Zusammenfassung läuft im Worker (Queue) — der Klick legt
    # nur das Platzhalter-Dokument an und blockiert die Oberfläche nicht. Der
    # Editor-Long-Poll ersetzt den Platzhalter, sobald der Job fertig ist.
    title = f"Zusammenfassung: {session.title or 'Chat'}"[:300]
    doc = await create_editor_document(db, project.id, user, title, is_private=False)
    doc = await save_editor_document(db, doc, user, PLATZHALTER_HTML, doc.version)
    await audit(
        db,
        "editor_document.from_chat",
        actor_user_id=user.id,
        project_id=project.id,
        target_type="editor_document",
        target_id=str(doc.id),
        meta={"chat_id": str(chat_id)},
    )
    await db.commit()
    # Erst nach dem Commit einreihen — der Worker muss die Zeilen sehen.
    from govdesk.workers.tasks import summarize_chat

    await summarize_chat.defer_async(
        chat_id=str(chat_id), document_id=str(doc.id), user_id=str(user.id)
    )
    return RedirectResponse(f"/projects/{project.id}/editor/{doc.id}", status_code=303)


@router.get("/projects/{project_id}/chats/{chat_id}/stream")
async def chat_stream(
    project: ProjectViewer, user: CurrentUser, db: Db, chat_id: uuid.UUID
) -> StreamingResponse:
    session = await _own_session(db, chat_id, project, user)
    last = await last_message(db, session.id)
    if last is None or last.role != MessageRole.USER:
        # Nichts zu beantworten (z. B. Reload) — sofort abschließen
        async def empty():
            yield "event: done\ndata: \n\n"

        return StreamingResponse(empty(), media_type="text/event-stream")

    return StreamingResponse(
        stream_answer(project, session.id, last.content),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
