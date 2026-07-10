# SPDX-FileCopyrightText: 2026 GovDesk-Mitwirkende
#
# SPDX-License-Identifier: EUPL-1.2

"""Chat-Verlauf → behördlicher Vermerk (läuft im Worker, nie im Request)."""

from govdesk.core.app_settings import RuntimeConfig
from govdesk.db.models import ChatSession, MessageRole
from govdesk.rag.llm import llm_provider_from_config

SUMMARY_SYSTEM = (
    "Du fasst einen Chat-Verlauf zu einem strukturierten behördlichen Vermerk zusammen. "
    "Antworte auf Deutsch in Markdown mit einer kurzen Überschrift, den wichtigsten "
    "Erkenntnissen als Aufzählung und – falls vorhanden – offenen Punkten. Keine Erfindungen."
)

PLATZHALTER_HTML = (
    '<p><em>Die Zusammenfassung wird im Hintergrund erstellt und erscheint hier '
    "automatisch, sobald sie fertig ist …</em></p>"
)


def strip_code_fence(text: str) -> str:
    """Entfernt umschließende ```-Codeblöcke, die manche LLMs um Markdown legen."""
    s = text.strip()
    if not s.startswith("```"):
        return s
    lines = s.splitlines()
    lines = lines[1:]  # öffnende Fence-Zeile (z. B. ```markdown) weg
    if lines and lines[-1].strip().startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines).strip()


def transcript_for(session: ChatSession) -> str:
    return "\n\n".join(
        f"{'Nutzer' if m.role == MessageRole.USER else 'Assistent'}: {m.content}"
        for m in session.messages
        if m.role in (MessageRole.USER, MessageRole.ASSISTANT)
    )


async def summarize_transcript(cfg: RuntimeConfig, transcript: str) -> str:
    """Roh-Markdown der Zusammenfassung (Rendern übernimmt der Aufrufer)."""
    return await llm_provider_from_config(cfg).complete(
        [
            {"role": "system", "content": SUMMARY_SYSTEM},
            {"role": "user", "content": transcript[:12000]},
        ],
        model=cfg.chat_model,
        temperature=0.3,
    )
