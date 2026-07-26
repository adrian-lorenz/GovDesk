# SPDX-FileCopyrightText: 2026 GovDesk-Mitwirkende
#
# SPDX-License-Identifier: EUPL-1.2

"""SSE-Streaming einer Chat-Antwort: Retrieval → Prompt → Token-Stream → Zitate."""

import asyncio
import html
import logging
import uuid

import markdown_it
import nh3

from govdesk.core.app_settings import get_runtime_config
from govdesk.core.guardrails import check_input, load_guardrails, scope_prompt
from govdesk.db.models import MessageRole, Project
from govdesk.db.session import get_session_factory
from govdesk.rag.llm import llm_provider_from_config
from govdesk.rag.retrieval import RetrievalResult, retrieve

logger = logging.getLogger(__name__)

_md = markdown_it.MarkdownIt("commonmark", {"typographer": True})

SYSTEM_PROMPT = """Du bist GovDesk, ein Assistent für Behörden. Beantworte Fragen \
ausschließlich auf Grundlage der bereitgestellten Quellen. Zitiere Belege im Text \
mit [1], [2] usw. entsprechend der Quellen-Nummerierung. Wenn die Quellen keine \
Antwort hergeben, sage das offen. Antworte auf Deutsch, präzise und sachlich."""

NO_SOURCES_ANSWER = (
    "Ich habe dazu noch keine passende Quelle in der Wissensbasis gefunden. "
    "Möglicherweise werden die ausgewählten Dokumente noch eingebettet. "
    "Bitte warten Sie, bis ihr Status „Bereit“ ist, und versuchen Sie es dann erneut."
)

MODEL_KNOWLEDGE_NOTICE = (
    "⚠️ **Hinweis: Keine passende Quelle in der Wissensbasis gefunden. "
    "Die folgende Antwort basiert auf allgemeinem Modellwissen und ist nicht "
    "durch Projektquellen belegt.**"
)

MODEL_KNOWLEDGE_SYSTEM_PROMPT = """Du bist GovDesk, ein Assistent für Behörden. \
Für die aktuelle Frage wurde keine passende Quelle in der Projekt-Wissensbasis \
gefunden. Beantworte sie anhand deines allgemeinen Modellwissens auf Deutsch, \
präzise und sachlich. Erfinde keine Quellen, Fundstellen oder Quellennummern. \
Behaupte nicht, dass deine Antwort durch die Projekt-Wissensbasis belegt ist. \
Weise auf Unsicherheit hin, besonders bei rechtlichen oder zeitabhängigen Aussagen."""

MODEL_CHAT_SYSTEM_PROMPT = """Du bist GovDesk, ein hilfreicher Assistent für Behörden. \
Dies ist ein normaler Modellchat ohne Zugriff auf die Projekt-Wissensbasis. Antworte \
auf Deutsch, präzise und sachlich. Erfinde keine Quellen oder Fundstellen und weise \
bei rechtlichen oder zeitabhängigen Aussagen transparent auf Unsicherheiten hin."""

MODEL_CHAT_DISABLED_ANSWER = (
    "Der Modellchat ohne Wissensbasis ist derzeit durch die Plattform-Administration "
    "deaktiviert. Bitte wählen Sie für einen neuen Chat ein RAG-Profil."
)


def render_markdown(text: str) -> str:
    return nh3.clean(_md.render(text))


def _sse(event: str, data: str) -> str:
    lines = "".join(f"data: {line}\n" for line in data.splitlines() or [""])
    return f"event: {event}\n{lines}\n"


async def stream_answer(
    project: Project,
    session_id: uuid.UUID,
    question: str,
    *,
    show_retrieval_details: bool = False,
):
    """Async-Generator für die SSE-Response.

    Öffnet eigene DB-Sessions (kurzlebig), damit die Verbindung nicht für die
    gesamte Streaming-Dauer blockiert ist.
    """
    answer_parts: list[str] = []
    retrieval: RetrievalResult | None = None
    model_knowledge_used = False
    model_chat_used = False

    model = None
    try:
        async with get_session_factory()() as db:
            cfg = await get_runtime_config(db)
            guardrails = await load_guardrails(db)
            from govdesk.chat.service import get_chat_session, history_for_llm
            from govdesk.db.models import ChatConfig

            history = await history_for_llm(db, session_id)
            chat_config: ChatConfig | None = None
            session = await get_chat_session(db, session_id)
            if session is not None and session.chat_config_id is not None:
                chat_config = await db.get(ChatConfig, session.chat_config_id)

        # Guardrails: Eingabe VOR dem Sprachmodell prüfen.
        guard_reason = check_input(question, guardrails)
        if guard_reason is not None:
            async with get_session_factory()() as db:
                from govdesk.core.audit import audit

                await audit(
                    db, "guardrail.blocked", project_id=project.id, meta={"reason": guard_reason}
                )
                await db.commit()
            answer_parts.append(guard_reason)
            yield _sse("token", html.escape(guard_reason))
        else:
            system_prompt = (chat_config.system_prompt or None) if chat_config else None
            model = (chat_config.model if chat_config else None) or cfg.chat_model
            temperature = chat_config.temperature if chat_config else 0.2
            top_n = chat_config.top_k if chat_config else 4
            rerank = chat_config.rerank_enabled if chat_config else True
            collection_ids = list(chat_config.collection_ids or []) if chat_config else None
            retrieval_enabled = chat_config.retrieval_enabled if chat_config else True

            if not retrieval_enabled:
                if not cfg.model_chat_enabled:
                    answer_parts.append(MODEL_CHAT_DISABLED_ANSWER)
                    yield _sse("token", html.escape(MODEL_CHAT_DISABLED_ANSWER))
                else:
                    model_chat_used = True
                    base_system = (
                        f"{system_prompt}\n\n{MODEL_CHAT_SYSTEM_PROMPT}"
                        if system_prompt
                        else MODEL_CHAT_SYSTEM_PROMPT
                    )
                    guard_scope = scope_prompt(guardrails)
                    if guard_scope:
                        base_system = f"{base_system}\n\n{guard_scope}"
                    messages = [{"role": "system", "content": base_system}, *history]
                    provider = llm_provider_from_config(cfg)
                    heartbeat = asyncio.get_event_loop().time()
                    async for token in provider.stream_chat(
                        messages, model=model, temperature=temperature
                    ):
                        answer_parts.append(token)
                        yield _sse("token", html.escape(token))
                        now = asyncio.get_event_loop().time()
                        if now - heartbeat > 15:
                            heartbeat = now
                            yield ": heartbeat\n\n"
            else:
                retrieval = await retrieve(
                    project,
                    question,
                    cfg,
                    top_n=top_n,
                    collection_ids=collection_ids or None,
                    rerank=rerank,
                )

            if retrieval_enabled and not retrieval.context:
                if not project.rag_fallback_enabled:
                    answer_parts.append(NO_SOURCES_ANSWER)
                    yield _sse("token", html.escape(NO_SOURCES_ANSWER))
                else:
                    model_knowledge_used = True
                    notice = f"{MODEL_KNOWLEDGE_NOTICE}\n\n"
                    answer_parts.append(notice)
                    yield _sse("token", html.escape(notice))

                    base_system = (
                        f"{system_prompt}\n\n{MODEL_KNOWLEDGE_SYSTEM_PROMPT}"
                        if system_prompt
                        else MODEL_KNOWLEDGE_SYSTEM_PROMPT
                    )
                    guard_scope = scope_prompt(guardrails)
                    if guard_scope:
                        base_system = f"{base_system}\n\n{guard_scope}"
                    messages = [{"role": "system", "content": base_system}, *history]
                    provider = llm_provider_from_config(cfg)
                    heartbeat = asyncio.get_event_loop().time()
                    async for token in provider.stream_chat(
                        messages, model=model, temperature=temperature
                    ):
                        answer_parts.append(token)
                        yield _sse("token", html.escape(token))
                        now = asyncio.get_event_loop().time()
                        if now - heartbeat > 15:
                            heartbeat = now
                            yield ": heartbeat\n\n"
            elif retrieval_enabled:
                base_system = system_prompt or SYSTEM_PROMPT
                guard_scope = scope_prompt(guardrails)
                if guard_scope:
                    base_system = f"{base_system}\n\n{guard_scope}"
                messages = [{"role": "system", "content": base_system}]
                messages.append(
                    {
                        "role": "system",
                        "content": f"Quellen:\n\n{retrieval.context}",
                    }
                )
                messages.extend(history)

                provider = llm_provider_from_config(cfg)
                heartbeat = asyncio.get_event_loop().time()

                async for token in provider.stream_chat(
                    messages, model=model, temperature=temperature
                ):
                    answer_parts.append(token)
                    yield _sse("token", html.escape(token))
                    now = asyncio.get_event_loop().time()
                    if now - heartbeat > 15:
                        heartbeat = now
                        yield ": heartbeat\n\n"

    except Exception:
        logger.exception("Chat-Streaming fehlgeschlagen (Session %s)", session_id)
        yield _sse(
            "token",
            html.escape(
                "\n\nEs ist ein Fehler aufgetreten — ist das Sprachmodell erreichbar? "
                "Bitte prüfen Sie die Einstellungen."
            ),
        )

    answer = "".join(answer_parts).strip()
    citations = [c.as_dict() for c in retrieval.citations] if retrieval else []

    if answer:
        async with get_session_factory()() as db:
            from govdesk.chat.service import add_message, get_chat_session

            session = await get_chat_session(db, session_id)
            if session is not None:
                await add_message(
                    db,
                    session,
                    MessageRole.ASSISTANT,
                    answer,
                    citations=citations,
                    model=model,
                    model_knowledge_used=model_knowledge_used,
                    model_chat_used=model_chat_used,
                )
                await db.commit()

    # Abschluss-Event: ersetzt den Token-Rohstream durch final gerendertes
    # Markdown samt Quellen-Panel (Partial serverseitig gerendert)
    from govdesk.web.deps import templates

    final_html = templates.env.get_template("partials/_antwort_final.html").render(
        html_content=render_markdown(answer),
        citations=citations,
        project_id=project.id,
        model_knowledge_used=model_knowledge_used,
        model_chat_used=model_chat_used,
        show_retrieval_details=show_retrieval_details,
    )
    yield _sse("done", final_html)
