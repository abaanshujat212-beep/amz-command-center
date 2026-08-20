"""Token vault: envelope encryption for Amazon refresh tokens.

Rules enforced here:
  * tokens are stored as ciphertext (bytea), never plain text
  * a per-row DEK is wrapped by the KEK from KEK_BASE64
  * key_version allows rotation without downtime
  * missing KEK means the service refuses to start (fail closed)
  * Amazon rotates refresh tokens — always persist the newest one
"""

from __future__ import annotations

import base64
import os
from dataclasses import dataclass

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_TOKEN_PREFIXES = ("Atzr|", "Atza|")


class VaultNotConfigured(RuntimeError):
    pass


def _kek() -> bytes:
    raw = os.environ.get("KEK_BASE64", "")
    if not raw:
        raise VaultNotConfigured(
            "KEK_BASE64 is not set. Refusing to start: refresh tokens cannot be "
            "stored or read without an encryption key."
        )
    key = base64.b64decode(raw)
    if len(key) != 32:
        raise VaultNotConfigured("KEK_BASE64 must decode to exactly 32 bytes")
    return key


def kek_version() -> int:
    return int(os.environ.get("KEK_VERSION", "1"))


@dataclass(frozen=True)
class Sealed:
    ciphertext: bytes
    key_version: int


def seal(plaintext: str) -> Sealed:
    """Encrypt a refresh token. Layout: [12B nonce][32B wrapped DEK][ciphertext]."""
    kek = _kek()
    dek = os.urandom(32)
    dek_nonce = os.urandom(12)
    wrapped = AESGCM(kek).encrypt(dek_nonce, dek, None)

    data_nonce = os.urandom(12)
    body = AESGCM(dek).encrypt(data_nonce, plaintext.encode(), None)

    blob = (
        len(wrapped).to_bytes(2, "big")
        + dek_nonce
        + wrapped
        + data_nonce
        + body
    )
    return Sealed(ciphertext=blob, key_version=kek_version())


def unseal(blob: bytes) -> str:
    kek = _kek()
    wrapped_len = int.from_bytes(blob[:2], "big")
    pos = 2
    dek_nonce, pos = blob[pos : pos + 12], pos + 12
    wrapped, pos = blob[pos : pos + wrapped_len], pos + wrapped_len
    data_nonce, pos = blob[pos : pos + 12], pos + 12
    body = blob[pos:]

    dek = AESGCM(kek).decrypt(dek_nonce, wrapped, None)
    return AESGCM(dek).decrypt(data_nonce, body, None).decode()


def redact(text: str) -> str:
    """Mask anything that looks like an Amazon token before it reaches a log."""
    out = text
    for prefix in _TOKEN_PREFIXES:
        while prefix in out:
            start = out.index(prefix)
            end = start + len(prefix)
            while end < len(out) and (out[end].isalnum() or out[end] in "-_.|"):
                end += 1
            out = out[:start] + prefix + "***REDACTED***" + out[end:]
    return out
