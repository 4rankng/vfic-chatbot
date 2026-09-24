"""Storage primitives shared by every provider group in this package.

Row reads/decryption, the plaintext upsert, the AEAD-context row read, the
probe-artifact rows, and the cache-namespace invalidation mechanics. Mixed into
:class:`~app.services.integration_settings.service.IntegrationSettingsService`,
which owns ``db`` / ``settings`` / ``cipher``.
"""

from __future__ import annotations

import json
import logging
from typing import Iterable

from cryptography.exceptions import InvalidTag
from sqlalchemy import select

from app.core.cache import bump_cache_version
from app.core.preamble_cache import (
    NS_INTEGRATION_CUSTOM_LLM,
    NS_INTEGRATION_MINIMAX,
    NS_INTEGRATION_OPENROUTER,
    evict_local_namespace,
)
from app.models.integration import IntegrationSetting
from app.services.integration_settings._shared import LLM_DEFAULT_PROVIDER

logger = logging.getLogger(__name__)

# Real-probe outcomes per provider (persisted so the settings page can show
# "tested 2 minutes ago · 412 ms" across reloads). Stored as plaintext JSON in
# non-secret rows — a probe artifact, not configuration.
PROVIDER_TEST_KEYS = {
    "minimax": "minimax_last_test",
    "openrouter": "openrouter_last_test",
    "custom": "custom_llm_last_test",
}


class StorageMixin:
    """DB row primitives + cache invalidation shared across provider groups."""

    async def _stored_values(self, keys: Iterable[str]) -> dict[str, str]:
        if not hasattr(self.db, "scalars"):
            return {}
        result = await self.db.scalars(
            select(IntegrationSetting).where(IntegrationSetting.key.in_(list(keys)))
        )
        rows = result.all() if hasattr(result, "all") else []
        if hasattr(rows, "__await__"):
            return {}
        values: dict[str, str] = {}
        for row in rows:
            try:
                values[row.key] = self.cipher.decrypt(row.encrypted_value)
            except InvalidTag:
                # Wrong key (rotation) or corrupt ciphertext. Skip the row so
                # callers fall back to Settings env vars instead of 500ing the
                # admin view; mirrors `_stored_value_with_context`'s handling.
                # Log the key name only — never the ciphertext or plaintext.
                logger.warning(
                    "integration setting decrypt failed key=%s "
                    "(wrong key / corrupt row); falling back to env",
                    row.key,
                )
        return values

    async def _write_setting(
        self,
        key: str,
        value: str,
        *,
        actor_id=None,
        is_secret: bool,
    ) -> bool:
        cleaned = value.strip()
        if not cleaned:
            return False
        stored_value = self.cipher.encrypt(cleaned) if is_secret else cleaned
        row = await self.db.get(IntegrationSetting, key)
        if row is None:
            row = IntegrationSetting(
                key=key,
                encrypted_value=stored_value,
                is_secret=is_secret,
                updated_by=actor_id,
            )
            self.db.add(row)
        else:
            row.encrypted_value = stored_value
            row.is_secret = is_secret
            row.updated_by = actor_id
        return True

    async def _bump_provider_namespaces(self, primary: str, changed: list[str]) -> None:
        """Invalidate the provider snapshots affected by an integration save.

        ``llm_default_provider`` is a shared routing key cached inside EVERY
        provider's snapshot: saving "default = custom" from the Xiaomi or
        OpenRouter panel must also invalidate the MiniMax copy (and vice
        versa), otherwise the routing flip stays stale until the snapshot TTL
        expires — exactly during the quota emergency the flip is for.
        """
        namespaces: list[str] = [primary]
        if LLM_DEFAULT_PROVIDER in changed:
            namespaces = [
                NS_INTEGRATION_MINIMAX,
                NS_INTEGRATION_OPENROUTER,
                NS_INTEGRATION_CUSTOM_LLM,
            ]
        for ns in namespaces:
            evict_local_namespace(ns)
            await bump_cache_version(ns)

    # ── Per-provider probe results ("tested 2 minutes ago · 412 ms") ────────

    async def record_provider_test_result(self, provider: str, payload: dict) -> None:
        """Persist one real-probe outcome so it survives a page reload.

        Stored as plaintext JSON in a non-secret row — a probe artifact, not
        configuration. Failures are persisted too, so a dead provider keeps
        showing its error instead of looking silently healthy.
        """
        key = PROVIDER_TEST_KEYS[provider]
        raw = json.dumps(payload)
        row = await self.db.get(IntegrationSetting, key)
        if row is None:
            row = IntegrationSetting(key=key, encrypted_value=raw, is_secret=False)
            self.db.add(row)
        else:
            row.encrypted_value = raw
            row.is_secret = False
        await self.db.commit()

    async def get_provider_test_result(self, provider: str) -> dict | None:
        row = await self.db.get(IntegrationSetting, PROVIDER_TEST_KEYS[provider])
        if row is None or row.is_secret:
            return None
        try:
            return json.loads(row.encrypted_value or "")
        except ValueError:
            return None

    async def _stored_value_with_context(self, key: str, context: str) -> str:
        """Fetch one encrypted setting row and decrypt with AEAD context.

        Page tokens must be context-bound (``v2:``); a legacy ``v1:`` row is
        rejected as corrupt so a token moved between Pages cannot decrypt via
        the context-less fallback (Red Team #7).
        """
        if not hasattr(self.db, "scalars"):
            return ""
        row = await self.db.scalar(select(IntegrationSetting).where(IntegrationSetting.key == key))
        if row is None:
            return ""
        stored = row.encrypted_value or ""
        if not stored.startswith("v2:"):
            # A v1 row for a Page token is either a corrupt write or a legacy
            # import. Fail closed (reconnect required) rather than decrypting
            # without the context binding.
            logger.warning("facebook page token rejected (not context-bound) key=%s", key)
            return ""
        try:
            return self.cipher.decrypt_with_context(stored, context)
        except Exception:  # noqa: BLE001 — wrong-context / corrupt ciphertext
            # A token moved between Pages or a rotated encryption key. Surface
            # as "not resolvable" so the caller fails closed (reconnect required).
            logger.warning(
                "facebook page token decrypt failed key=%s (wrong context or corrupt)",
                key,
            )
            return ""
