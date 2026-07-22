from __future__ import annotations

from collections.abc import Iterator, Mapping
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException

from app.api import auth_dependencies
from app.identity.application.authentication import AccessTokenAuthenticator
from app.identity.domain.errors import AuthenticationError


class TrackingPayload(Mapping[str, object]):
    def __init__(self, values: dict[str, object], events: list[str]) -> None:
        self._values = values
        self._events = events

    def __getitem__(self, key: str) -> object:
        self._events.append(f"payload[{key}]")
        return self._values[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._values)

    def __len__(self) -> int:
        return len(self._values)

    def get(self, key: str, default: object = None) -> object:
        self._events.append(f"payload.get({key})")
        return self._values.get(key, default)


class TrackingDecoder:
    def __init__(self, payload: Mapping[str, object], events: list[str]) -> None:
        self._payload = payload
        self._events = events

    async def decode(self, token: str) -> Mapping[str, object]:
        self._events.append(f"decode:{token}")
        return self._payload


class TrackingUser:
    def __init__(self, *, token_version: int, disabled: bool, events: list[str]) -> None:
        self._token_version = token_version
        self._disabled = disabled
        self._events = events

    @property
    def disabled(self) -> bool:
        self._events.append("user.disabled")
        return self._disabled

    @property
    def token_version(self) -> int:
        self._events.append("user.token_version")
        return self._token_version


class TrackingUsers:
    def __init__(self, user: object | None, events: list[str]) -> None:
        self._user = user
        self._events = events

    async def get_by_id(self, user_id: UUID) -> object | None:
        self._events.append(f"repo:{user_id}")
        return self._user


@pytest.mark.asyncio
async def test_access_token_authenticator_preserves_validation_order_and_returns_user() -> None:
    events: list[str] = []
    user_id = uuid4()
    payload = TrackingPayload({"type": "access", "sub": str(user_id), "ver": 3}, events)
    user = TrackingUser(token_version=3, disabled=False, events=events)
    authenticator = AccessTokenAuthenticator(
        decoder=TrackingDecoder(payload, events),
        users=TrackingUsers(user, events),
    )

    authenticated = await authenticator.authenticate("token-1")

    assert authenticated is user
    assert events == [
        "decode:token-1",
        "payload.get(type)",
        "payload.get(sub)",
        f"repo:{user_id}",
        "user.disabled",
        "payload.get(ver)",
        "user.token_version",
    ]


@pytest.mark.asyncio
async def test_access_token_authenticator_rejects_non_access_tokens_before_lookup() -> None:
    events: list[str] = []
    authenticator = AccessTokenAuthenticator(
        decoder=TrackingDecoder(TrackingPayload({"type": "refresh"}, events), events),
        users=TrackingUsers(object(), events),
    )

    with pytest.raises(AuthenticationError):
        await authenticator.authenticate("token-2")

    assert events == ["decode:token-2", "payload.get(type)"]


@pytest.mark.asyncio
async def test_access_token_authenticator_rejects_invalid_uuid_before_lookup() -> None:
    events: list[str] = []
    authenticator = AccessTokenAuthenticator(
        decoder=TrackingDecoder(
            TrackingPayload({"type": "access", "sub": "not-a-uuid"}, events),
            events,
        ),
        users=TrackingUsers(object(), events),
    )

    with pytest.raises(AuthenticationError):
        await authenticator.authenticate("token-3")

    assert events == ["decode:token-3", "payload.get(type)", "payload.get(sub)"]


@pytest.mark.asyncio
async def test_access_token_dependency_raises_exact_401_credentials_error(monkeypatch) -> None:
    class FailingAuthenticator:
        async def authenticate(self, token: str) -> object:
            raise AuthenticationError(token)

    monkeypatch.setattr(
        auth_dependencies,
        "build_access_token_authenticator",
        lambda _db: FailingAuthenticator(),
    )

    with pytest.raises(HTTPException) as exc_info:
        await auth_dependencies.get_user_from_token("bad-token", SimpleNamespace())

    exc = exc_info.value
    assert exc.status_code == 401
    assert exc.detail == "Could not validate credentials"
    assert exc.headers == {"WWW-Authenticate": "Bearer"}
