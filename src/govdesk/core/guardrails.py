# SPDX-FileCopyrightText: 2026 GovDesk-Mitwirkende
#
# SPDX-License-Identifier: EUPL-1.2

"""Guardrails für Chat-Eingaben (regelbasiert, lokal — kein externer Dienst).

Prüft Nutzerfragen VOR dem Sprachmodell: Sperrbegriffe, Längenlimit und eine
einfache Prompt-Injection-Heuristik. Ausgabe-Guardrails (PII-Schwärzung etc.)
folgen als eigener Schritt. Konfiguration über die Admin-Einstellungen.
"""

from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from govdesk.core.app_settings import get_all_settings

# Typische Prompt-Injection-/Jailbreak-Formulierungen (DE + EN, Kleinschreibung).
_INJECTION_PATTERNS = (
    "ignore previous", "ignore all previous", "disregard previous", "disregard all",
    "vergiss alle", "vergiss die vorherigen", "ignoriere alle", "ignoriere die anweisung",
    "ignoriere vorherige", "system prompt", "systemprompt", "du bist jetzt", "act as",
    "reveal your instructions", "zeig deine anweisungen", "zeige deine anweisungen",
    "jailbreak", "developer mode", "entwicklermodus",
)


# Vordefinierte Themen-/Scope-Verbote → Anweisung, die dem System-Prompt beigefügt wird.
TOPIC_RULES: dict[str, tuple[str, str]] = {
    "politik": (
        "Politik & Wahlen",
        "Beantworte keine Fragen zu politischen Themen, Parteien, Wahlen oder "
        "politischen Meinungen.",
    ),
    "code": (
        "Programmcode",
        "Gib keinen Programmcode aus und hilf nicht beim Programmieren.",
    ),
    "medizin": (
        "Medizinische Beratung",
        "Gib keine medizinischen Ratschläge, Diagnosen oder Therapieempfehlungen.",
    ),
    "recht": (
        "Individuelle Rechtsberatung",
        "Erteile keine individuelle Rechtsberatung; verweise auf zuständige Stellen.",
    ),
    "meinung": (
        "Persönliche Meinungen",
        "Äußere keine persönlichen Meinungen, Wertungen oder Spekulationen.",
    ),
}


@dataclass(frozen=True)
class GuardrailConfig:
    enabled: bool = False
    blocklist: list[str] = field(default_factory=list)
    detect_injection: bool = True
    max_input_chars: int = 4000
    refusal_topics: list[str] = field(default_factory=list)
    scope_instructions: str = ""


async def load_guardrails(db: AsyncSession) -> GuardrailConfig:
    s = await get_all_settings(db)
    raw_block = s.get("guardrail_blocklist")
    blocklist = [b.strip() for b in raw_block if isinstance(b, str) and b.strip()] if isinstance(
        raw_block, list
    ) else []
    raw_topics = s.get("guardrail_refusal_topics")
    topics = (
        [t for t in raw_topics if t in TOPIC_RULES] if isinstance(raw_topics, list) else []
    )
    try:
        max_chars = int(s.get("guardrail_max_input_chars", 4000) or 0)
    except (TypeError, ValueError):
        max_chars = 4000
    return GuardrailConfig(
        enabled=bool(s.get("guardrails_enabled", False)),
        blocklist=blocklist,
        detect_injection=bool(s.get("guardrail_detect_injection", True)),
        max_input_chars=max_chars,
        refusal_topics=topics,
        scope_instructions=str(s.get("guardrail_scope_instructions") or ""),
    )


def scope_prompt(config: GuardrailConfig) -> str | None:
    """Baut die Guardrail-Vorgaben für den System-Prompt (oder None, wenn inaktiv)."""
    if not config.enabled:
        return None
    regeln = [TOPIC_RULES[t][1] for t in config.refusal_topics if t in TOPIC_RULES]
    if config.scope_instructions.strip():
        regeln.append(config.scope_instructions.strip())
    if not regeln:
        return None
    aufzaehlung = "\n".join(f"- {r}" for r in regeln)
    return (
        "Zusätzliche verbindliche Vorgaben (Guardrails):\n"
        f"{aufzaehlung}\n"
        "Wenn eine Anfrage dagegen verstößt, lehne höflich ab und weise auf den "
        "zulässigen Themenrahmen hin, ohne die verbotenen Inhalte zu liefern."
    )


def check_input(text: str, config: GuardrailConfig) -> str | None:
    """Gibt einen Ablehnungsgrund zurück, wenn die Eingabe blockiert wird — sonst None."""
    if not config.enabled:
        return None
    if config.max_input_chars > 0 and len(text) > config.max_input_chars:
        return f"Die Anfrage ist zu lang (max. {config.max_input_chars} Zeichen)."
    lowered = text.lower()
    for term in config.blocklist:
        if term.lower() in lowered:
            return "Die Anfrage enthält einen unzulässigen Begriff."
    if config.detect_injection and any(p in lowered for p in _INJECTION_PATTERNS):
        return "Die Anfrage wurde als möglicher Manipulationsversuch abgelehnt."
    return None
