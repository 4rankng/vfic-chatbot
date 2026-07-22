"""Redis-backed adapters for Facebook OAuth state and flow storage."""

from __future__ import annotations

import json
from uuid import UUID

from app.services.integration_settings import IntegrationSettingsCipher

from .domain import FacebookOAuthAdminBinding, FacebookOAuthFlow, FacebookOAuthPage


def _decode_text(raw: object) -> str | None:
    if raw is None:
        return None
    if isinstance(raw, bytes):
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError:
            return None
    if isinstance(raw, str):
        return raw
    return None


def _load_admin_binding(payload: str) -> FacebookOAuthAdminBinding | None:
    try:
        data = json.loads(payload)
        return FacebookOAuthAdminBinding(
            admin_id=UUID(str(data["admin_id"])),
            token_version=int(data["token_version"]),
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None


class RedisFacebookOAuthStateStore:
    def __init__(self, *, redis, key_prefix: str = "fb_oauth_state:") -> None:
        self._redis = redis
        self._key_prefix = key_prefix

    async def save(
        self,
        *,
        state: str,
        admin: FacebookOAuthAdminBinding,
        ttl_seconds: int,
    ) -> None:
        await self._redis.set(
            f"{self._key_prefix}{state}",
            json.dumps(
                {
                    "admin_id": str(admin.admin_id),
                    "token_version": int(admin.token_version),
                }
            ),
            ex=ttl_seconds,
        )

    async def consume(self, *, state: str) -> FacebookOAuthAdminBinding | None:
        payload = _decode_text(await self._redis.getdel(f"{self._key_prefix}{state}"))
        if payload is None:
            return None
        return _load_admin_binding(payload)


class RedisFacebookOAuthFlowStore:
    def __init__(
        self,
        *,
        redis,
        cipher: IntegrationSettingsCipher | None = None,
        key_prefix: str = "fb_oauth_flow:",
    ) -> None:
        self._redis = redis
        self._cipher = cipher or IntegrationSettingsCipher()
        self._key_prefix = key_prefix

    async def save(
        self,
        *,
        flow_id: str,
        flow: FacebookOAuthFlow,
        ttl_seconds: int,
    ) -> None:
        payload = self._cipher.encrypt(
            json.dumps(
                {
                    "admin_id": str(flow.admin.admin_id),
                    "token_version": int(flow.admin.token_version),
                    "user_token": flow.user_token,
                    "pages": [{"id": page.id, "name": page.name} for page in flow.pages],
                }
            )
        )
        await self._redis.set(
            self._flow_key(admin=flow.admin, flow_id=flow_id),
            payload,
            ex=ttl_seconds,
        )

    async def load(
        self,
        *,
        flow_id: str,
        admin: FacebookOAuthAdminBinding,
    ) -> FacebookOAuthFlow | None:
        payload = await self._redis.get(self._flow_key(admin=admin, flow_id=flow_id))
        return self._decode_flow(payload=payload, admin=admin)

    async def consume(
        self,
        *,
        flow_id: str,
        admin: FacebookOAuthAdminBinding,
    ) -> FacebookOAuthFlow | None:
        payload = await self._redis.getdel(self._flow_key(admin=admin, flow_id=flow_id))
        return self._decode_flow(payload=payload, admin=admin)

    def _flow_key(self, *, admin: FacebookOAuthAdminBinding, flow_id: str) -> str:
        return f"{self._key_prefix}{admin.admin_id}:{flow_id}"

    def _decode_flow(
        self,
        *,
        payload: object,
        admin: FacebookOAuthAdminBinding,
    ) -> FacebookOAuthFlow | None:
        ciphertext = _decode_text(payload)
        if ciphertext is None or not ciphertext.startswith("v1:"):
            return None
        try:
            data = json.loads(self._cipher.decrypt(ciphertext))
            if str(data["admin_id"]) != str(admin.admin_id) or int(data["token_version"]) != int(
                admin.token_version
            ):
                return None
            user_token = data["user_token"]
            raw_pages = data["pages"]
            if not isinstance(user_token, str) or not user_token:
                return None
            if not isinstance(raw_pages, list) or not raw_pages:
                return None
            pages: list[FacebookOAuthPage] = []
            for raw_page in raw_pages:
                if (
                    not isinstance(raw_page, dict)
                    or not isinstance(raw_page.get("id"), str)
                    or not raw_page["id"]
                    or not isinstance(raw_page.get("name"), str)
                    or not raw_page["name"]
                ):
                    return None
                pages.append(
                    FacebookOAuthPage(
                        id=raw_page["id"],
                        name=raw_page["name"],
                    )
                )
            return FacebookOAuthFlow(
                admin=admin,
                user_token=user_token,
                pages=tuple(pages),
            )
        except Exception:  # noqa: BLE001 - invalid ciphertext is an expired flow
            return None
