"""AES-GCM credential cipher for integration settings secrets."""

from __future__ import annotations

import base64
import hashlib
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import Settings, get_settings


class IntegrationSettingsCipher:
    """Small AES-GCM wrapper for settings secrets.

    The DB stores opaque `v1:<base64(nonce+ciphertext)>` values. In development,
    the JWT secret is accepted as a fallback key so local setup stays light; in
    production Settings.model_post_init requires INTEGRATION_SETTINGS_ENCRYPTION_KEY.

    Migration hazard (OPS-03/SEC-08): a value sealed under the JWT-secret fallback
    can only ever be reopened with that same secret. Setting the dedicated key on a
    deployment that has been encrypting under the fallback makes every stored
    credential undecryptable unless the old secret is preserved, and because
    `make backup` historically shipped only the DB dump, rotating or losing the
    secret silently destroys admin-managed integration credentials. Treat
    INTEGRATION_SETTINGS_ENCRYPTION_KEY as part of the backup set, never rotate it
    without re-sealing, and prefer a labelled derivation over reusing `jwt_secret`.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        raw = self._settings.integration_settings_encryption_key or self._settings.jwt_secret
        self._key = hashlib.sha256(raw.encode("utf-8")).digest()

    def encrypt(self, value: str) -> str:
        nonce = os.urandom(12)
        sealed = AESGCM(self._key).encrypt(nonce, value.encode("utf-8"), None)
        return "v1:" + base64.urlsafe_b64encode(nonce + sealed).decode("ascii")

    def decrypt(self, stored: str) -> str:
        if not stored:
            return ""
        if not stored.startswith("v1:"):
            # Allows manual dev rows / future imports to fail soft rather than
            # bricking runtime resolution.
            return stored
        payload = base64.urlsafe_b64decode(stored[3:].encode("ascii"))
        nonce, sealed = payload[:12], payload[12:]
        return AESGCM(self._key).decrypt(nonce, sealed, None).decode("utf-8")

    def encrypt_with_context(self, value: str, context: str) -> str:
        """Bind ``context`` into the AEAD associated data (Red Team #7).

        A ciphertext produced for one context (e.g. Page id ``A``) will NOT
        decrypt under another (Page id ``B``) — the GCM tag fails. This blocks
        a token row moved between Pages from decrypting successfully. Stored
        under a ``v2:`` prefix so legacy ``v1:`` rows decrypt unchanged via
        :meth:`decrypt_with_context`'s fallback.
        """
        nonce = os.urandom(12)
        aad = context.encode("utf-8")
        sealed = AESGCM(self._key).encrypt(nonce, value.encode("utf-8"), aad)
        return "v2:" + base64.urlsafe_b64encode(nonce + sealed).decode("ascii")

    def decrypt_with_context(self, stored: str, context: str) -> str:
        """Inverse of :meth:`encrypt_with_context`.

        ``v2:`` rows require the matching context; ``v1:`` rows (no context
        binding) decrypt via the legacy path for the rolling window. A ``v2:``
        row with the wrong context raises ``InvalidTag`` (the caller surfaces a
        reconnect-required error rather than accepting a swapped token).
        """
        if not stored:
            return ""
        if not stored.startswith("v2:"):
            return self.decrypt(stored)
        payload = base64.urlsafe_b64decode(stored[3:].encode("ascii"))
        nonce, sealed = payload[:12], payload[12:]
        aad = context.encode("utf-8")
        return AESGCM(self._key).decrypt(nonce, sealed, aad).decode("utf-8")
