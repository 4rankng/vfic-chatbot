"""Channel-provider contract tests for the recruiter conversation inbox."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import ANY, AsyncMock, patch

import httpx
import pytest
from fastapi import FastAPI
from httpx import ASGITransport

from app.api.conversations import router as conversations_router
from app.api.auth_dependencies import get_current_user
from app.core.db import get_db
from app.core.errors import register_domain_exception_handlers
from app.models.user import Role


_app = FastAPI()
register_domain_exception_handlers(_app)
_app.include_router(conversations_router, prefix="/api/v1")


@pytest.fixture
def transport():
    user = SimpleNamespace(id=uuid.uuid4(), role=Role.admin)
    db = AsyncMock()

    async def override_user():
        return user

    async def override_db():
        yield db

    _app.dependency_overrides[get_current_user] = override_user
    _app.dependency_overrides[get_db] = override_db
    yield ASGITransport(app=_app), db
    _app.dependency_overrides.clear()


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/api/v1/conversations", "/api/v1/conversations/needs-attention"])
async def test_unknown_channel_provider_returns_422(transport, path: str) -> None:
    http_transport, _db = transport
    async with httpx.AsyncClient(transport=http_transport, base_url="http://test") as client:
        response = await client.get(path, params={"channel_provider": "messenger"})

    assert response.status_code == 422


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path", ["/api/v1/conversations", "/api/v1/conversations/needs-attention"]
)
async def test_messenger_is_an_accepted_channel_scope(transport, path: str) -> None:
    """The inbox can scope to Messenger, not just the two Zalo adapters."""
    http_transport, _db = transport
    with patch("app.api.conversations.ConversationService") as service_class:
        service = service_class.return_value
        service.list = AsyncMock(return_value=([], 0))
        service.needs_attention_count = AsyncMock(return_value=0)
        async with httpx.AsyncClient(
            transport=http_transport, base_url="http://test"
        ) as client:
            response = await client.get(
                path, params={"channel_provider": "facebook_messenger"}
            )

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_list_threads_provider_through_normal_and_reason_paths(transport) -> None:
    http_transport, _db = transport
    with (
        patch("app.api.conversations.ConversationService") as service_class,
        patch(
            "app.api.conversations.run_conversation_attention_query",
            new_callable=AsyncMock,
            return_value=([], 0),
        ) as attention_query,
    ):
        service = service_class.return_value
        service.list = AsyncMock(return_value=([], 0))
        async with httpx.AsyncClient(transport=http_transport, base_url="http://test") as client:
            normal = await client.get(
                "/api/v1/conversations",
                params={"channel_provider": "zalo_oa", "q": "candidate"},
            )
            reason = await client.get(
                "/api/v1/conversations",
                params={"channel_provider": "zalo_bot", "reason": "UNREAD"},
            )

    assert normal.status_code == 200
    assert reason.status_code == 200
    assert service.list.await_args.kwargs["channel_provider"] == "zalo_oa"
    assert attention_query.await_args.kwargs["channel_provider"] == "zalo_bot"


@pytest.mark.asyncio
async def test_omitted_provider_preserves_aggregate_count_call(transport) -> None:
    http_transport, _db = transport
    with patch("app.api.conversations.ConversationService") as service_class:
        service_class.return_value.needs_attention_count = AsyncMock(return_value=7)
        async with httpx.AsyncClient(transport=http_transport, base_url="http://test") as client:
            response = await client.get("/api/v1/conversations/needs-attention")

    assert response.json() == {"count": 7}
    assert service_class.return_value.needs_attention_count.await_args.kwargs == {
        "viewer": ANY,
        "channel_provider": None,
    }


@pytest.mark.asyncio
async def test_batch_zalo_lookup_deduplicates_exact_requested_ids(transport) -> None:
    http_transport, _db = transport
    with patch("app.api.conversations.ConversationService") as service_class:
        service_class.return_value.list_by_zalo_ids = AsyncMock(return_value=[])
        async with httpx.AsyncClient(
            transport=http_transport,
            base_url="http://test",
        ) as client:
            response = await client.get(
                "/api/v1/conversations/by-zalo-ids",
                params={"ids": "oa:user-1,oa:user-1,bot:user-2"},
            )

    assert response.status_code == 200
    assert response.json() == {"data": [], "total": 0}
    assert service_class.return_value.list_by_zalo_ids.await_args.kwargs == {
        "viewer": ANY,
        "zalo_chat_ids": ["oa:user-1", "bot:user-2"],
    }


@pytest.mark.asyncio
async def test_batch_zalo_lookup_rejects_more_than_200_ids(transport) -> None:
    http_transport, _db = transport
    async with httpx.AsyncClient(
        transport=http_transport,
        base_url="http://test",
    ) as client:
        response = await client.get(
            "/api/v1/conversations/by-zalo-ids",
            params={"ids": ",".join(f"user-{index}" for index in range(201))},
        )

    assert response.status_code == 422


class _ScalarRows:
    def all(self):
        return []


@pytest.mark.asyncio
async def test_provider_and_search_reuse_one_identity_join() -> None:
    from app.services.conversation.repository import ConversationRepository

    db = SimpleNamespace(scalar=AsyncMock(return_value=0), scalars=AsyncMock(return_value=_ScalarRows()))
    viewer = SimpleNamespace(id=uuid.uuid4(), role=Role.admin)

    await ConversationRepository(db).list(
        viewer=viewer,
        channel_provider="zalo_bot",
        q="abc",
    )

    count_sql = str(db.scalar.await_args.args[0])
    page_sql = str(db.scalars.await_args.args[0])
    assert count_sql.count("JOIN contact_channel_identities") == 1
    assert page_sql.count("JOIN contact_channel_identities") == 1
    assert "contact_channel_identities.provider" in page_sql
    assert "contact_channel_identities.external_id" in page_sql


@pytest.mark.asyncio
async def test_batch_zalo_lookup_is_viewer_scoped_and_newest_first() -> None:
    from app.services.conversation.repository import ConversationRepository

    db = SimpleNamespace(scalars=AsyncMock(return_value=_ScalarRows()))
    viewer = SimpleNamespace(id=uuid.uuid4(), role=Role.admin)

    await ConversationRepository(db).list_by_zalo_ids(
        viewer=viewer,
        zalo_chat_ids=["oa:user-1", "bot:user-2"],
    )

    sql = str(db.scalars.await_args.args[0])
    assert "conversations.zalo_chat_id IN" in sql
    assert "conversations.updated_at DESC" in sql


@pytest.mark.asyncio
async def test_attention_reason_query_returns_total_for_empty_late_page() -> None:
    from app.services.dashboard.repository import DashboardRepository

    result = SimpleNamespace(
        mappings=lambda: [{"conversation_id": None, "total": 613}]
    )
    db = SimpleNamespace(execute=AsyncMock(return_value=result))

    ids, total = await DashboardRepository(db).attention_reason_page(
        None,
        reason="UNREAD",
        channel_provider="zalo_oa",
        page=100,
        per_page=25,
    )

    sql = db.execute.await_args.args[0].text
    params = db.execute.await_args.args[1]
    assert ids == []
    assert total == 613
    assert "ci.provider = CAST(:channel_provider AS text)" in sql
    assert "count(*)::int AS total FROM filtered" in sql
    assert "LEFT JOIN page_rows ON true" in sql
    assert params["offset"] == 2475


@pytest.mark.asyncio
async def test_attention_reason_service_uses_dedicated_page_query(monkeypatch) -> None:
    from app.composition.reporting import run_conversation_attention_query

    conversation_id = uuid.uuid4()
    dashboard_repo = SimpleNamespace(
        attention_reason_page=AsyncMock(return_value=([conversation_id], 1))
    )
    monkeypatch.setattr(
        "app.services.dashboard.repository.DashboardRepository",
        lambda _db: dashboard_repo,
    )
    row = SimpleNamespace(id=conversation_id)
    conversation_repo = SimpleNamespace(
        get_visible_by_ids=AsyncMock(return_value=[row])
    )
    monkeypatch.setattr(
        "app.services.conversation.repository.ConversationRepository",
        lambda _db: conversation_repo,
    )
    viewer = SimpleNamespace(id=uuid.uuid4(), role=Role.recruiter)

    rows, total = await run_conversation_attention_query(
        AsyncMock(),
        viewer=viewer,
        reason="WAITING_REPLY",
        channel_provider="zalo_bot",
        page=2,
        per_page=10,
    )

    assert rows == [row]
    assert total == 1
    dashboard_repo.attention_reason_page.assert_awaited_once_with(
        str(viewer.id),
        reason="WAITING_REPLY",
        channel_provider="zalo_bot",
        page=2,
        per_page=10,
    )
    conversation_repo.get_visible_by_ids.assert_awaited_once_with(
        viewer=viewer,
        ids=[conversation_id],
    )
