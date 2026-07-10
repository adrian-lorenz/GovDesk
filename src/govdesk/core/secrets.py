# SPDX-FileCopyrightText: 2026 GovDesk-Mitwirkende
#
# SPDX-License-Identifier: EUPL-1.2

"""Verschlüsselung von Geheimnissen (z. B. Connector-App-Passwörter) für die DB.

Symmetrische Verschlüsselung mit Fernet (AES-128-CBC + HMAC). Der Schlüssel wird
deterministisch aus `GOVDESK_SECRET_KEY` abgeleitet — es ist also kein zusätzliches
Schlüsselmanagement nötig, aber: Ändert sich der Secret-Key, sind bereits
verschlüsselte Werte nicht mehr entschlüsselbar (dann Geheimnisse neu eintragen).

Ablage-Konvention in JSON-Feldern: ein Geheimnis wird als ``{"__enc__": "<token>"}``
gespeichert. So bleiben Altbestände (Klartext-Strings) abwärtskompatibel lesbar.
"""

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from govdesk.core.config import get_settings

ENC_MARKER = "__enc__"


def _fernet() -> Fernet:
    digest = hashlib.sha256(get_settings().secret_key.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt(token: str) -> str:
    return _fernet().decrypt(token.encode()).decode()


def seal(plaintext: str) -> dict[str, str]:
    """Geheimnis in die JSON-Ablageform bringen."""
    return {ENC_MARKER: encrypt(plaintext)}


def unseal(value: object) -> object:
    """Umkehrung von :func:`seal`. Nicht-versiegelte Werte werden unverändert
    zurückgegeben (Abwärtskompatibilität mit Klartext-Altbeständen)."""
    if isinstance(value, dict) and ENC_MARKER in value:
        try:
            return decrypt(value[ENC_MARKER])
        except InvalidToken:
            return ""
    return value
