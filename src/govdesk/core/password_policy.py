# SPDX-FileCopyrightText: 2026 GovDesk-Mitwirkende
#
# SPDX-License-Identifier: EUPL-1.2

"""Konfigurierbare Passwort-Richtlinie für lokale Konten (angelehnt an BSI).

Greift nur für lokale Passwörter; bei OIDC/SSO liegt die Richtlinie beim
Identity-Provider. Werte kommen aus app_settings (Admin-Einstellungen).
"""

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from govdesk.core.app_settings import get_all_settings

# Kleine Sperrliste offensichtlich schwacher Passwörter (Kleinbuchstaben-Vergleich).
# Kein Ersatz für einen vollständigen Abgleich (z. B. HIBP) — das ist ein Folgeschritt.
_COMMON = {
    "passwort", "password", "12345678", "123456789", "1234567890", "qwertz123",
    "qwerty123", "passwort1", "password1", "admin123", "govdesk123", "willkommen",
    "geheim123", "letmein123", "changeme123", "sommer2026", "winter2026",
}


@dataclass(frozen=True)
class PasswordPolicy:
    min_length: int = 12
    require_upper: bool = True
    require_lower: bool = True
    require_digit: bool = True
    require_special: bool = False
    block_common: bool = True


def _b(store: dict, key: str, default: bool) -> bool:
    val = store.get(key)
    return default if val is None else bool(val)


async def load_policy(db: AsyncSession) -> PasswordPolicy:
    s = await get_all_settings(db)
    raw_len = s.get("pw_min_length")
    try:
        min_length = max(8, int(raw_len)) if raw_len is not None else 12
    except (TypeError, ValueError):
        min_length = 12
    return PasswordPolicy(
        min_length=min_length,
        require_upper=_b(s, "pw_require_upper", True),
        require_lower=_b(s, "pw_require_lower", True),
        require_digit=_b(s, "pw_require_digit", True),
        require_special=_b(s, "pw_require_special", False),
        block_common=_b(s, "pw_block_common", True),
    )


def validate(password: str, policy: PasswordPolicy) -> list[str]:
    """Liefert eine Liste von Verstößen (leer = Passwort erfüllt die Richtlinie)."""
    errors: list[str] = []
    if len(password) < policy.min_length:
        errors.append(f"mindestens {policy.min_length} Zeichen")
    if policy.require_upper and not any(c.isupper() for c in password):
        errors.append("mindestens ein Großbuchstabe")
    if policy.require_lower and not any(c.islower() for c in password):
        errors.append("mindestens ein Kleinbuchstabe")
    if policy.require_digit and not any(c.isdigit() for c in password):
        errors.append("mindestens eine Ziffer")
    if policy.require_special and password.isalnum():
        errors.append("mindestens ein Sonderzeichen")
    if policy.block_common and password.lower() in _COMMON:
        errors.append("kein häufig verwendetes / bekanntes Passwort")
    return errors
