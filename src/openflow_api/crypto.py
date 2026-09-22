from __future__ import annotations

import base64
import os
from typing import Any

from cryptography.fernet import Fernet


class SecretsManager:
    """Manages encryption and decryption of tenant connector secrets.
    
    Encryption Standard:
        Fernet symmetric encryption using AES-128-CBC with PKCS7 padding
        and HMAC-SHA256 for integrity and authenticity (fixing A5).
    """

    def __init__(self, primary_key: str | bytes | None = None) -> None:
        key = primary_key or os.getenv("FERNET_KEY")
        if not key:
            # Generate a secure fallback key for testing if none is set
            self._key = Fernet.generate_key()
        elif isinstance(key, str):
            self._key = key.encode("utf-8")
        else:
            self._key = key

        try:
            self._fernet = Fernet(self._key)
        except Exception as exc:
            raise ValueError(
                "Invalid FERNET_KEY: must be 32 url-safe base64-encoded bytes."
            ) from exc

    @classmethod
    def generate_new_key(cls) -> str:
        """Generates a fresh 32-byte url-safe base64 encoded Fernet key."""
        return Fernet.generate_key().decode("utf-8")

    def encrypt(self, plain_text: str) -> str:
        """Encrypts a plaintext secret into an authenticated ciphertext string."""
        if not plain_text:
            return ""
        return self._fernet.encrypt(plain_text.encode("utf-8")).decode("utf-8")

    def decrypt(self, cipher_text: str) -> str:
        """Decrypts an authenticated ciphertext string back into plaintext."""
        if not cipher_text:
            return ""
        return self._fernet.decrypt(cipher_text.encode("utf-8")).decode("utf-8")

