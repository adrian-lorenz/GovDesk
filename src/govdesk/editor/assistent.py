# SPDX-FileCopyrightText: 2026 GovDesk-Mitwirkende
#
# SPDX-License-Identifier: EUPL-1.2

"""KI-Assistent im Dokumenten-Editor.

Zwei Modi:
- „frage":      beantwortet Fragen zum Dokument (Antwort als Markdown im Panel).
- „bearbeiten": liefert Ersatz-HTML für die Auswahl bzw. das ganze Dokument —
                der Client fügt es inline (rückgängig machbar) ein.

Kontext: aktuelles Dokument, optionale Auswahl, RAG-Treffer aus der
Wissensbasis des Projekts sowie Auszüge der anderen Editor-Dokumente.
"""

import asyncio
import html
import logging
import re

import nh3

from govdesk.core.app_settings import get_runtime_config
from govdesk.core.guardrails import check_input, load_guardrails, scope_prompt
from govdesk.db.models import EditorDocument, Project, User
from govdesk.db.session import get_session_factory
from govdesk.rag.llm import llm_provider_from_config
from govdesk.rag.retrieval import retrieve

logger = logging.getLogger(__name__)

# Grenzen, damit der Prompt auch bei großen Dokumenten handhabbar bleibt.
_MAX_DOC_CHARS = 24_000
_MAX_AUSWAHL_CHARS = 8_000
_MAX_ANDERE_DOCS = 5
_MAX_ANDERE_CHARS = 1_500

_PROMPT_FRAGE = """Du bist der Schreib-Assistent von GovDesk, einer souveränen \
Plattform für Behörden. Du hilfst beim Arbeiten an einem Dokument. Dir liegen \
das aktuelle Dokument, ggf. eine markierte Textstelle sowie Quellen aus der \
Wissensbasis des Projekts vor. Beantworte die Frage präzise, sachlich und auf \
Deutsch. Wenn du dich auf Quellen stützt, nenne sie mit [1], [2] usw."""

_PROMPT_ERSETZEN = """Du bist der Schreib-Assistent von GovDesk und überarbeitest \
eine markierte Textstelle eines Dokuments. Antworte AUSSCHLIESSLICH mit dem \
fertigen Ersatz-HTML für die markierte Stelle — ohne Erklärungen, ohne \
Markdown-Codeblöcke, ohne Anführungszeichen drumherum. Ersetze NUR die \
markierte Stelle; alles andere bleibt unangetastet. Halte dich strikt an die \
vorhandene Formatierung und Gliederung des Dokuments (gleiche Überschriften-\
Ebenen, gleicher Stil). Erlaubte Tags: p, br, b, strong, i, em, u, s, h1–h4, \
ul, ol, li, blockquote, a, code, pre. Schreibe auf Deutsch, im Stil einer \
Behörde: klar, korrekt, bürgernah. Nutze die Quellen, wo sie helfen."""

_PROMPT_EINFUEGEN = """Du bist der Schreib-Assistent von GovDesk und ergänzt ein \
bestehendes Dokument um einen neuen Abschnitt. Antworte AUSSCHLIESSLICH mit dem \
HTML des NEUEN Inhalts, der an der Einfügemarke ergänzt wird — ohne Erklärungen, \
ohne Markdown-Codeblöcke. Gib NIEMALS das ganze Dokument zurück und wiederhole \
keinen bestehenden Inhalt. Halte dich strikt an Stil, Ton und Formatierung des \
vorhandenen Dokuments (gleiche Überschriften-Ebenen, gleiche Gliederung). \
Erlaubte Tags: p, br, b, strong, i, em, u, s, h1–h4, ul, ol, li, blockquote, \
a, code, pre. Schreibe auf Deutsch, im Stil einer Behörde: klar, korrekt, \
bürgernah. Nutze die Quellen, wo sie helfen."""


def _sse(event: str, data: str) -> str:
    lines = "".join(f"data: {line}\n" for line in data.splitlines() or [""])
    return f"event: {event}\n{lines}\n"


def _als_text(html_inhalt: str, limit: int) -> str:
    """HTML → Klartext (alle Tags entfernt), auf limit Zeichen gekürzt."""
    text = nh3.clean(html_inhalt, tags=set()).strip()
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text[:limit]


def _fence_entfernen(text: str) -> str:
    """Entfernt einen umschließenden Markdown-Codeblock, falls das Modell doch
    einen ausgibt (```html … ```)."""
    m = re.fullmatch(r"```[a-zA-Z]*\n(.*?)\n?```", text.strip(), re.DOTALL)
    return m.group(1) if m else text


async def stream_assist(
    project: Project,
    doc: EditorDocument,
    user: User,
    frage: str,
    modus: str,
    auswahl_html: str,
    sanitize_html,
):
    """Async-Generator für die SSE-Response des Editor-Assistenten."""
    answer_parts: list[str] = []
    modus = modus if modus in {"frage", "bearbeiten"} else "frage"

    try:
        async with get_session_factory()() as db:
            cfg = await get_runtime_config(db)
            guardrails = await load_guardrails(db)

            # Auszüge der anderen sichtbaren Editor-Dokumente des Projekts.
            from govdesk.editor.service import list_documents

            andere = [
                d
                for d in await list_documents(db, project.id, user, all_folders=True)
                if d.id != doc.id
            ][:_MAX_ANDERE_DOCS]
            andere_kontext = "\n\n".join(
                f"— Dokument „{d.title}“:\n{_als_text(d.content, _MAX_ANDERE_CHARS)}"
                for d in andere
                if d.content.strip()
            )

        guard_reason = check_input(frage, guardrails)
        if guard_reason is not None:
            yield _sse("token", html.escape(guard_reason))
            yield _sse("done", html.escape(guard_reason))
            return

        retrieval = await retrieve(project, frage, cfg, top_n=4)

        if modus == "frage":
            system = _PROMPT_FRAGE
        elif auswahl_html.strip():
            system = _PROMPT_ERSETZEN
        else:
            # Ohne Auswahl wird eingefügt, nicht ersetzt — sonst droht
            # Datenverlust, wenn das Modell das Dokument neu erfindet.
            system = _PROMPT_EINFUEGEN
        guard_scope = scope_prompt(guardrails)
        if guard_scope:
            system = f"{system}\n\n{guard_scope}"

        kontext_teile = [
            f"Aktuelles Dokument „{doc.title}“:\n{_als_text(doc.content, _MAX_DOC_CHARS)}"
        ]
        if auswahl_html.strip():
            kontext_teile.append(
                "Markierte Stelle (HTML):\n" + auswahl_html[:_MAX_AUSWAHL_CHARS]
            )
        if retrieval.context:
            kontext_teile.append(f"Quellen aus der Wissensbasis:\n{retrieval.context}")
        if andere_kontext:
            kontext_teile.append(f"Weitere Dokumente im Projekt (Auszüge):\n{andere_kontext}")

        messages = [
            {"role": "system", "content": system},
            {"role": "system", "content": "\n\n---\n\n".join(kontext_teile)},
            {"role": "user", "content": frage},
        ]

        provider = llm_provider_from_config(cfg)
        heartbeat = asyncio.get_event_loop().time()
        async for token in provider.stream_chat(messages, model=cfg.chat_model, temperature=0.2):
            answer_parts.append(token)
            yield _sse("token", html.escape(token))
            now = asyncio.get_event_loop().time()
            if now - heartbeat > 15:
                heartbeat = now
                yield ": heartbeat\n\n"

    except Exception:
        logger.exception("Editor-Assistent fehlgeschlagen (Dokument %s)", doc.id)
        fehler = (
            "Es ist ein Fehler aufgetreten — ist das Sprachmodell erreichbar? "
            "Bitte prüfen Sie die Einstellungen."
        )
        yield _sse("token", html.escape(fehler))
        yield _sse("fehler", html.escape(fehler))
        return

    answer = "".join(answer_parts).strip()
    if modus == "bearbeiten":
        # Ersatz-HTML: serverseitig säubern, bevor es der Client einfügt.
        ersatz = sanitize_html(_fence_entfernen(answer))
        yield _sse("ersatz", ersatz)
    else:
        from govdesk.chat.streaming import render_markdown

        yield _sse("done", render_markdown(answer))
