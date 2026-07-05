# SPDX-FileCopyrightText: 2026 GovDesk-Mitwirkende
#
# SPDX-License-Identifier: EUPL-1.2

"""Passwort-Hashing (argon2id) und Token-Erzeugung/-Hashing."""

import hashlib
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, VerifyMismatchError

_hasher = PasswordHasher(time_cost=3, memory_cost=64 * 1024, parallelism=2)


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except VerifyMismatchError, VerificationError:
        return False


def password_needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)


def new_token() -> str:
    """Opaker Token (256 Bit) für Sessions."""
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    """Nur der Hash wird gespeichert — ein DB-Leak gibt keine gültigen Cookies preis."""
    return hashlib.sha256(token.encode()).hexdigest()


def new_csrf_token() -> str:
    return secrets.token_hex(32)


def new_api_key() -> tuple[str, str, str]:
    """Erzeugt einen API-Key: (Klartext, Prefix, Hash).

    Format gd_<keyid>_<secret>; der Prefix dient dem indizierten Lookup,
    gespeichert wird nur der Hash des vollständigen Schlüssels.
    """
    key_id = secrets.token_hex(4)
    secret = secrets.token_urlsafe(32)
    full_key = f"gd_{key_id}_{secret}"
    return full_key, f"gd_{key_id}", hash_token(full_key)
