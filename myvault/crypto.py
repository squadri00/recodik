"""Encryption for MyVault.

The Fernet key is derived from the install's *master password* via PBKDF2-HMAC-SHA256
with a random salt stored in ``meta``. The derived key is held only in this process's
memory after an explicit unlock; it is never written to disk or into a session cookie.

If the master password is lost the salt is useless on its own and encrypted field
values cannot be recovered. This is by design.
"""

from __future__ import annotations

import base64
import os

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

PBKDF2_ITERATIONS = 480_000
SALT_BYTES = 16
_VERIFIER_PLAINTEXT = b"myvault-key-verifier-v1"

# Process-global derived key. None => vault is locked.
_master_key: bytes | None = None


def new_salt() -> bytes:
    return os.urandom(SALT_BYTES)


def derive_key(master_password: str, salt: bytes) -> bytes:
    """Derive a urlsafe-base64 Fernet key from the master password and salt."""
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=PBKDF2_ITERATIONS,
    )
    return base64.urlsafe_b64encode(kdf.derive(master_password.encode("utf-8")))


def make_verifier(key: bytes) -> str:
    """A token that proves a later-derived key matches the one used at setup."""
    return Fernet(key).encrypt(_VERIFIER_PLAINTEXT).decode("ascii")


def check_key(key: bytes, verifier: str) -> bool:
    try:
        return Fernet(key).decrypt(verifier.encode("ascii")) == _VERIFIER_PLAINTEXT
    except (InvalidToken, ValueError):
        return False


# --- process-global unlock state -------------------------------------------------

def set_master_key(key: bytes) -> None:
    global _master_key
    _master_key = key


def clear_master_key() -> None:
    global _master_key
    _master_key = None


def is_unlocked() -> bool:
    return _master_key is not None


class VaultLocked(RuntimeError):
    """Raised when an encrypt/decrypt is attempted while the vault is locked."""


# --- value encryption ----------------------------------------------------------

def encrypt_value(plaintext: str) -> str:
    if _master_key is None:
        raise VaultLocked("Vault is locked")
    return encrypt_with(_master_key, plaintext)


def decrypt_value(token: str) -> str:
    if _master_key is None:
        raise VaultLocked("Vault is locked")
    return decrypt_with(_master_key, token)


def encrypt_with(key: bytes, plaintext: str) -> str:
    return Fernet(key).encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt_with(key: bytes, token: str) -> str:
    return Fernet(key).decrypt(token.encode("ascii")).decode("utf-8")
