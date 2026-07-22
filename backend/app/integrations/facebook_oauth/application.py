"""Application-layer Facebook OAuth orchestration."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Protocol
from uuid import UUID

from .domain import FacebookOAuthAdminBinding, FacebookOAuthFlow, FacebookOAuthPage


class FacebookOAuthInvalidState(RuntimeError):
    """Raised when the callback state is missing or malformed."""


class FacebookOAuthFlowUnavailable(RuntimeError):
    """Raised when the encrypted Page-selection flow is missing or invalid."""


class FacebookOAuthStateStore(Protocol):
    async def save(
        self,
        *,
        state: str,
        admin: FacebookOAuthAdminBinding,
        ttl_seconds: int,
    ) -> None: ...

    async def consume(self, *, state: str) -> FacebookOAuthAdminBinding | None: ...


class FacebookOAuthFlowStore(Protocol):
    async def save(
        self,
        *,
        flow_id: str,
        flow: FacebookOAuthFlow,
        ttl_seconds: int,
    ) -> None: ...

    async def load(
        self,
        *,
        flow_id: str,
        admin: FacebookOAuthAdminBinding,
    ) -> FacebookOAuthFlow | None: ...

    async def consume(
        self,
        *,
        flow_id: str,
        admin: FacebookOAuthAdminBinding,
    ) -> FacebookOAuthFlow | None: ...


class FacebookOAuthCoordinator:
    """Issues single-use state and admin-bound OAuth flow capsules."""

    def __init__(
        self,
        *,
        state_store: FacebookOAuthStateStore,
        flow_store: FacebookOAuthFlowStore,
        ttl_seconds: int,
        state_factory: Callable[[], str],
        flow_id_factory: Callable[[], str],
    ) -> None:
        self._state_store = state_store
        self._flow_store = flow_store
        self._ttl_seconds = ttl_seconds
        self._state_factory = state_factory
        self._flow_id_factory = flow_id_factory

    async def issue_state(self, *, admin_id: UUID, token_version: int) -> str:
        admin = FacebookOAuthAdminBinding(
            admin_id=admin_id,
            token_version=token_version,
        )
        state = self._state_factory()
        await self._state_store.save(
            state=state,
            admin=admin,
            ttl_seconds=self._ttl_seconds,
        )
        return state

    async def consume_state(self, *, state: str) -> FacebookOAuthAdminBinding:
        admin = await self._state_store.consume(state=state)
        if admin is None:
            raise FacebookOAuthInvalidState()
        return admin

    async def store_flow(
        self,
        *,
        admin_id: UUID,
        token_version: int,
        user_token: str,
        pages: Sequence[FacebookOAuthPage],
    ) -> str:
        flow_pages = tuple(pages)
        if not user_token or not flow_pages:
            raise ValueError("facebook oauth flow payload is incomplete")
        flow = FacebookOAuthFlow(
            admin=FacebookOAuthAdminBinding(
                admin_id=admin_id,
                token_version=token_version,
            ),
            user_token=user_token,
            pages=flow_pages,
        )
        flow_id = self._flow_id_factory()
        await self._flow_store.save(
            flow_id=flow_id,
            flow=flow,
            ttl_seconds=self._ttl_seconds,
        )
        return flow_id

    async def load_flow(
        self,
        *,
        flow_id: str,
        admin_id: UUID,
        token_version: int,
        consume: bool = False,
    ) -> FacebookOAuthFlow:
        admin = FacebookOAuthAdminBinding(
            admin_id=admin_id,
            token_version=token_version,
        )
        if consume:
            flow = await self._flow_store.consume(flow_id=flow_id, admin=admin)
        else:
            flow = await self._flow_store.load(flow_id=flow_id, admin=admin)
        if flow is None:
            raise FacebookOAuthFlowUnavailable()
        return flow
