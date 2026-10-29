from __future__ import annotations

import base64
import hashlib
import os
from typing import Optional

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import settings

AES_GCM_PREFIX = "enc_aes256gcm_v1:"
SEEDED_DUMMY_PREFIX = "enc_aes256gcm_v1:dummy_"
NONCE_BYTE_LENGTH = 12


def _derive_aes256_key(key_material: Optional[str] = None) -> bytes:
    """Derive a deterministic 256-bit (32-byte) key via SHA-256."""
    raw = key_material or settings.ENCRYPTION_KEY or settings.AUTH_SECRET
    if not raw:
        raise ValueError("Missing key material for AES-256-GCM encryption")
    return hashlib.sha256(raw.encode("utf-8")).digest()


def encrypt_secret(plaintext: str, *, key_material: Optional[str] = None) -> str:
    """
    Encrypt a plaintext credential at rest using AES-256-GCM.
    Output format: `enc_aes256gcm_v1:<urlsafe_base64(nonce_12B + ciphertext + tag_16B)>`
    """
    if plaintext is None:
        raise ValueError("Cannot encrypt None plaintext")

    key = _derive_aes256_key(key_material)
    aesgcm = AESGCM(key)
    nonce = os.urandom(NONCE_BYTE_LENGTH)
    ciphertext_with_tag = aesgcm.encrypt(nonce, plaintext.encode("utf-8"), None)
    encoded = base64.urlsafe_b64encode(nonce + ciphertext_with_tag).decode("ascii")
    return f"{AES_GCM_PREFIX}{encoded}"


def decrypt_secret(ciphertext: str, *, key_material: Optional[str] = None) -> str:
    """
    Decrypt an `enc_aes256gcm_v1:` credential encrypted with AES-256-GCM.
    Maintains seamless backward compatibility with the seeded `enc_aes256gcm_v1:dummy_...`
    placeholder credentials created in Phase 1 `seed.ts`.
    """
    if not ciphertext:
        raise ValueError("Cannot decrypt empty ciphertext")

    # Seamless support for deterministic Phase 1 seeded dummy credentials
    if ciphertext.startswith(SEEDED_DUMMY_PREFIX):
        return ciphertext[len(AES_GCM_PREFIX) :]

    if not ciphertext.startswith(AES_GCM_PREFIX):
        raise ValueError(
            f"Unsupported ciphertext format: missing '{AES_GCM_PREFIX}' prefix"
        )

    b64_payload = ciphertext[len(AES_GCM_PREFIX) :]
    try:
        raw_bytes = base64.urlsafe_b64decode(b64_payload.encode("ascii"))
    except Exception as exc:
        raise ValueError("Invalid base64 encoding in encrypted secret") from exc

    # Minimum length = 12-byte nonce + 16-byte GCM authentication tag
    if len(raw_bytes) < NONCE_BYTE_LENGTH + 16:
        raise ValueError("Truncated AES-256-GCM payload")

    nonce = raw_bytes[:NONCE_BYTE_LENGTH]
    ct_and_tag = raw_bytes[NONCE_BYTE_LENGTH:]

    key = _derive_aes256_key(key_material)
    aesgcm = AESGCM(key)
    try:
        decrypted_bytes = aesgcm.decrypt(nonce, ct_and_tag, None)
    except InvalidTag as exc:
        raise ValueError(
            "AES-256-GCM authentication tag verification failed"
        ) from exc

    return decrypted_bytes.decode("utf-8")

