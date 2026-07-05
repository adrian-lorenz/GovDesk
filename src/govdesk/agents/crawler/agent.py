# SPDX-FileCopyrightText: 2026 GovDesk-Mitwirkende
#
# SPDX-License-Identifier: EUPL-1.2

"""LLM-geführte Crawl-Entscheidungen: Ist eine Seite zum Thema relevant, und
welchen Links soll der Agent folgen? Ein einziger LLM-Call pro Seite."""

import json
import logging
import re
from dataclasses import dataclass

from govdesk.rag.llm import LLMProvider

logger = logging.getLogger(__name__)

_MAX_MARKDOWN_CHARS = 4000
_MAX_CANDIDATES = 40

_SYSTEM = (
    "Du bist ein Rechercheassistent, der einen Web-Crawler steuert. "
    "Du entscheidest, ob der Inhalt einer Seite zum Suchauftrag passt und "
    "welchen Links es sich lohnt zu folgen, um den Auftrag zu erfüllen. "
    "Antworte ausschließlich mit einem JSON-Objekt, ohne Erklärungen."
)


@dataclass
class PageDecision:
    """Ergebnis der LLM-Bewertung einer Seite."""

    relevant: bool
    follow: list[int]  # Indizes in die übergebene Kandidatenliste


def _build_prompt(
    topic: str,
    url: str,
    title: str,
    markdown: str,
    candidates: list[tuple[str, str]],
) -> str:
    snippet = markdown.strip()[:_MAX_MARKDOWN_CHARS]
    links = candidates[:_MAX_CANDIDATES]
    link_lines = (
        "\n".join(f"[{i}] {text or '(ohne Text)'} — {u}" for i, (u, text) in enumerate(links))
        or "(keine Links auf dieser Seite)"
    )
    return (
        f"Suchauftrag: {topic}\n\n"
        f"Aktuelle Seite: {title} ({url})\n"
        f"Inhalt (gekürzt):\n{snippet}\n\n"
        f"Links auf der Seite:\n{link_lines}\n\n"
        "Aufgabe:\n"
        "1. Ist der Inhalt dieser Seite für den Suchauftrag relevant und sollte "
        "er in die Wissensbasis aufgenommen werden?\n"
        "2. Welchen der nummerierten Links sollte der Crawler folgen, weil sie "
        "voraussichtlich weitere relevante Informationen enthalten?\n\n"
        'Antworte als JSON: {"relevant": true/false, "follow": [Liste der Link-Indizes]}. '
        "Wähle nur Links, die dem Auftrag dienen; leere Liste, wenn keiner passt."
    )


def _parse(raw: str, candidate_count: int) -> PageDecision | None:
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if match is None:
        return None
    try:
        obj = json.loads(match.group(0))
    except ValueError:
        return None
    relevant = bool(obj.get("relevant", True))
    follow_raw = obj.get("follow") or []
    follow = []
    if isinstance(follow_raw, list):
        for item in follow_raw:
            try:
                idx = int(item)
            except TypeError, ValueError:
                continue
            if 0 <= idx < candidate_count and idx not in follow:
                follow.append(idx)
    return PageDecision(relevant=relevant, follow=follow)


async def evaluate_page(
    llm: LLMProvider,
    model: str,
    topic: str,
    url: str,
    title: str,
    markdown: str,
    candidates: list[tuple[str, str]],
) -> PageDecision:
    """Bewertet Relevanz + wählt zu folgende Links (Indizes in ``candidates``).

    Fail-open: Bei LLM-Fehler oder unparsbarer Antwort gilt die Seite als
    relevant (Inhalt nicht still verwerfen), aber es wird keinem Link gefolgt
    (kein Runaway).
    """
    prompt = _build_prompt(topic, url, title, markdown, candidates)
    try:
        raw = await llm.complete(
            [{"role": "system", "content": _SYSTEM}, {"role": "user", "content": prompt}],
            model=model,
            temperature=0.0,
        )
    except Exception as exc:  # noqa: BLE001 — bewusst breit, LLM darf den Crawl nicht killen
        logger.warning("LLM-Bewertung für %s fehlgeschlagen: %s", url, exc)
        return PageDecision(relevant=True, follow=[])

    decision = _parse(raw, min(len(candidates), _MAX_CANDIDATES))
    if decision is None:
        logger.warning("LLM-Antwort für %s nicht als JSON lesbar: %r", url, raw[:200])
        return PageDecision(relevant=True, follow=[])
    return decision
