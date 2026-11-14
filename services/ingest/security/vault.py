"""Token vault: envelope encryption for Amazon refresh tokens.

Rules enforced here:
  * tokens are stored as ciphertext (bytea), never plain text
  * a per-row DEK is wrapped by a versioned KEK
  * KEK_BASE64/KEK_VERSION are current; the optional previous pair supports rotation
  * missing KEK means the service refuses to start (fail closed)
  * Amazon rotates refresh tokens — always persist the newest one
"""

from __future__ import annotations

import base64
import binascii
import os
from dataclasses import dataclass

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_TOKEN_PREFIXES = ("Atzr|", "Atza|")


class VaultNotConfigured(RuntimeError):
    pass


def _decode_kek(raw: str, name: str) -> bytes:
    if not raw:
        raise VaultNotConfigured(
            f"{name} is not set. Refusing to start: refresh tokens cannot be "
            "stored or read without an encryption key."
        )
    try:
        key = base64.b64decode(raw, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise VaultNotConfigured(f"{name} must be valid base64") from exc
    if len(key) != 32:
        raise VaultNotConfigured(f"{name} must decode to exactly 32 bytes")
    return key


def kek_version() -> int:
    try:
        version = int(os.environ.get("KEK_VERSION", "1"))
    except ValueError as exc:
        raise VaultNotConfigured("KEK_VERSION must be a positive integer") from exc
    if version < 1:
        raise VaultNotConfigured("KEK_VERSION must be a positive integer")
    return version


def _keks() -> dict[int, bytes]:
    current_version = kek_version()
    keys = {current_version: _decode_kek(os.environ.get("KEK_BASE64", ""), "KEK_BASE64")}
    previous_raw = os.environ.get("KEK_PREVIOUS_BASE64", "")
    previous_version_raw = os.environ.get("KEK_PREVIOUS_VERSION", "")
    if bool(previous_raw) != bool(previous_version_raw):
        raise VaultNotConfigured(
            "KEK_PREVIOUS_BASE64 and KEK_PREVIOUS_VERSION must be set together"
        )
    if previous_raw:
        try:
            previous_version = int(previous_version_raw)
        except ValueError as exc:
            raise VaultNotConfigured("KEK_PREVIOUS_VERSION must be a positive integer") from exc
        if previous_version < 1 or previous_version == current_version:
            raise VaultNotConfigured(
                "KEK_PREVIOUS_VERSION must be positive and differ from KEK_VERSION"
            )
        keys[previous_version] = _decode_kek(previous_raw, "KEK_PREVIOUS_BASE64")
    return keys


@dataclass(frozen=True)
class Sealed:
    ciphertext: bytes
    key_version: int


def seal(plaintext: str) -> Sealed:
    """Encrypt a refresh token. Layout: [12B nonce][32B wrapped DEK][ciphertext]."""
    version = kek_version()
    kek = _keks()[version]
    dek = os.urandom(32)
    dek_nonce = os.urandom(12)
    wrapped = AESGCM(kek).encrypt(dek_nonce, dek, None)

    data_nonce = os.urandom(12)
    body = AESGCM(dek).encrypt(data_nonce, plaintext.encode(), None)

    blob = len(wrapped).to_bytes(2, "big") + dek_nonce + wrapped + data_nonce + body
    return Sealed(ciphertext=blob, key_version=version)


def unseal(blob: bytes, key_version: int) -> str:
    """Decrypt using the exact KEK version recorded with the ciphertext."""
    version = key_version
    keyring = _keks()
    if version not in keyring:
        raise VaultNotConfigured(f"KEK version {version} is not configured")
    kek = keyring[version]
    if len(blob) < 2:
        raise ValueError("encrypted token has an invalid envelope")
    wrapped_len = int.from_bytes(blob[:2], "big")
    if wrapped_len != 48 or len(blob) < 2 + 12 + wrapped_len + 12 + 16:
        raise ValueError("encrypted token has an invalid envelope")
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
