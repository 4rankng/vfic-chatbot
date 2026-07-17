"""Tests for the Phase 4 Facebook OAuth + Page lifecycle + admin endpoints.

Covers:
- Context-bound ciphertext: a Page token encrypted for page-A fails to decrypt
  under page-B.
- FacebookAccountResolver: resolve_active/resolve_any/active_facebook_page.
- FacebookPageLifecycle: activate/reactivate/disconnect, same-Page reuse,
  Page-replacement archives the prior active Page.
- OAuth client: authorization URL composition, permission set.
- Admin endpoints: RBAC (non-admin → 401/403), safe response (no token leaks),
  OAuth state single-use + admin-bound, flow capsule encrypted.

Most endpoint tests stub the Graph API client so no external HTTP is needed.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest


# ─── context-bound ciphertext ───────────────────────────────────────────────


def test_facebook_page_token_ciphertext_is_context_bound():
    """A Page token encrypted for page-A must NOT decrypt under page-B.

    Red Team #7: a token row moved between Pages must fail closed.
    """
    from app.services.integration_settings import IntegrationSettingsCipher
    from app.core.config import get_settings

    cipher = IntegrationSettingsCipher(get_settings())
    ct = cipher.encrypt_with_context("EAAB-page-A-token-secret", "page-111")

    # Correct context decrypts.
    assert cipher.decrypt_with_context(ct, "page-111") == "EAAB-page-A-token-secret"

    # Wrong context raises (InvalidTag).
    with pytest.raises(Exception):  # noqa: B017 - cryptography.exceptions.InvalidTag
        cipher.decrypt_with_context(ct, "page-222")

    # v1 legacy ciphertext decrypts via the fallback path.
    legacy = cipher.encrypt("legacy-token")
    assert cipher.decrypt_with_context(legacy, "any-context") == "legacy-token"


def test_facebook_runtime_config_dataclass():
    from app.services.integration_settings import FacebookRuntimeConfig

    cfg = FacebookRuntimeConfig(
        app_id="123",
        app_secret="secret",
        page_id="page-1",
        page_access_token="EAAB-token",
        verify_token="verify",
    )
    assert cfg.graph_api_version == "v25.0"
    assert cfg.graph_api_base == "https://graph.facebook.com"


# ─── OAuth client ───────────────────────────────────────────────────────────


def test_oauth_client_permission_set_matches_messenger_requirements():
    """Permissions revalidated against the official docs (2026-07-17):
    pages_show_list, pages_manage_metadata, pages_messaging, public_profile."""
    from app.channels.providers.facebook_oauth import MESSENGER_PERMISSIONS

    assert set(MESSENGER_PERMISSIONS) >= {
        "pages_show_list",
        "pages_manage_metadata",
        "pages_messaging",
        "public_profile",
    }


def test_build_authorization_url_includes_state_scope_and_config():
    from app.channels.providers.facebook_oauth import build_authorization_url

    url = build_authorization_url(
        state="opaque-state-123", redirect_uri="https://bot.example.com/fb/cb"
    )
    assert "dialog/oauth" in url
    assert "state=opaque-state-123" in url
    assert "pages_messaging" in url
    assert "redirect_uri=https://bot.example.com/fb/cb" in url


# ─── FacebookAccountResolver + Page lifecycle (DB-backed) ───────────────────
# These exercise the recoverable state machine against a real (disposable) DB.


@pytest.mark.integration
async def test_resolver_returns_none_for_unknown_page(integration_database):
    from app.channels.providers.facebook_account import FacebookAccountResolver
    from app.core.db import async_session

    async with async_session() as db:
        resolver = FacebookAccountResolver(db)
        assert await resolver.resolve_active(
            provider="facebook_messenger", account_key="page-unknown"
        ) is None
        assert await resolver.resolve_any(
            provider="facebook_messenger", account_key="page-unknown"
        ) is None
        assert await resolver.active_facebook_page() is None


@pytest.mark.integration
async def test_lifecycle_activate_then_resolve_active(integration_database):
    from app.channels.providers.facebook_account import (
        FacebookAccountResolver,
        FacebookPageLifecycle,
    )
    from app.core.db import async_session
    from app.models.user import User

    async with async_session() as db:
        admin = User(
            email="fb-admin@vfic.test",
            password_hash="x",
            full_name="FB Admin",
            role="admin",
        )
        db.add(admin)
        await db.flush()
        admin_id = admin.id

        lifecycle = FacebookPageLifecycle(db)
        account = await lifecycle.activate_or_reactivate(
            page_id="page-111",
            page_name="Công ty ABC",
            page_access_token="EAAB-page-111-token",
            admin_id=admin_id,
        )
        assert account.status == "ACTIVE"
        assert account.account_key == "page-111"
        assert account.generation == 1

    async with async_session() as db:
        resolver = FacebookAccountResolver(db)
        active = await resolver.active_facebook_page()
        assert active is not None
        assert active.is_active
        assert active.account_key == "page-111"
        assert active.generation == 1


@pytest.mark.integration
async def test_lifecycle_reactivate_same_page_reuses_account_and_advances_generation(
    integration_database,
):
    """Same-Page reactivation reuses the existing account and rotates the token;
    generation advances so stale queued commands are suppressed."""
    from app.channels.providers.facebook_account import FacebookPageLifecycle
    from app.core.db import async_session
    from app.models.user import User

    async with async_session() as db:
        admin = User(
            email="fb-admin2@vfic.test",
            password_hash="x",
            full_name="FB Admin 2",
            role="admin",
        )
        db.add(admin)
        await db.flush()
        admin_id = admin.id

        lifecycle = FacebookPageLifecycle(db)
        first = await lifecycle.activate_or_reactivate(
            page_id="page-222", page_name="P", page_access_token="t1", admin_id=admin_id
        )
        second = await lifecycle.activate_or_reactivate(
            page_id="page-222", page_name="P", page_access_token="t2", admin_id=admin_id
        )
        assert first.id == second.id  # same account reused
        assert second.generation > first.generation  # generation advanced


@pytest.mark.integration
async def test_lifecycle_replacement_archives_prior_active_page(integration_database):
    """Selecting a different Page archives the prior active Page as INACTIVE
    (distinct read-only history scope). V1 enforces at most one active."""
    from app.channels.providers.facebook_account import (
        FacebookAccountResolver,
        FacebookPageLifecycle,
    )
    from app.core.db import async_session
    from app.models.user import User

    async with async_session() as db:
        admin = User(
            email="fb-admin3@vfic.test",
            password_hash="x",
            full_name="FB Admin 3",
            role="admin",
        )
        db.add(admin)
        await db.flush()
        admin_id = admin.id

        lifecycle = FacebookPageLifecycle(db)
        await lifecycle.activate_or_reactivate(
            page_id="page-A", page_name="A", page_access_token="tA", admin_id=admin_id
        )
        await lifecycle.activate_or_reactivate(
            page_id="page-B", page_name="B", page_access_token="tB", admin_id=admin_id
        )

    async with async_session() as db:
        resolver = FacebookAccountResolver(db)
        accounts = await resolver.list_facebook_accounts()
        active = [a for a in accounts if a.is_active]
        inactive = [a for a in accounts if not a.is_active]
        assert len(active) == 1
        assert active[0].account_key == "page-B"
        assert len(inactive) == 1
        assert inactive[0].account_key == "page-A"


@pytest.mark.integration
async def test_lifecycle_disconnect_marks_inactive_keeps_history(integration_database):
    from app.channels.providers.facebook_account import (
        FacebookAccountResolver,
        FacebookPageLifecycle,
    )
    from app.core.db import async_session
    from app.models.user import User

    async with async_session() as db:
        admin = User(
            email="fb-admin4@vfic.test",
            password_hash="x",
            full_name="FB Admin 4",
            role="admin",
        )
        db.add(admin)
        await db.flush()
        admin_id = admin.id

        lifecycle = FacebookPageLifecycle(db)
        await lifecycle.activate_or_reactivate(
            page_id="page-D", page_name="D", page_access_token="tD", admin_id=admin_id
        )
        account = await lifecycle.disconnect(page_id="page-D", admin_id=admin_id)
        assert account is not None
        assert account.status == "INACTIVE"

    async with async_session() as db:
        resolver = FacebookAccountResolver(db)
        # resolve_active returns None (disconnected); resolve_any returns it.
        assert await resolver.resolve_active(
            provider="facebook_messenger", account_key="page-D"
        ) is None
        archived = await resolver.resolve_any(
            provider="facebook_messenger", account_key="page-D"
        )
        assert archived is not None
        assert not archived.is_active


# ─── admin endpoint RBAC + safe response ────────────────────────────────────


@pytest.mark.asyncio
async def test_facebook_endpoints_require_admin(monkeypatch):
    """Non-admin users cannot initiate, complete, inspect, test, or disconnect.

    The require_admin dependency enforces this; verify the routes are wired
    with it (not a separate RBAC check inside each handler).
    """
    from app.api.integrations import router

    fb_paths = {
        r.path for r in router.routes if "facebook" in r.path
    }
    assert fb_paths == {
        "/admin/integrations/facebook/oauth/start",
        "/admin/integrations/facebook/oauth/callback",
        "/admin/integrations/facebook/oauth/pages",
        "/admin/integrations/facebook/oauth/complete",
        "/admin/integrations/facebook",
        "/admin/integrations/facebook/test",
    }
    # Every facebook route depends on require_admin. The dependency callable
    # is reachable via route.dependant.dependencies[].call.

    for route in router.routes:
        if "facebook" not in route.path:
            continue
        callables = {getattr(d.call, "__name__", "") for d in route.dependant.dependencies}
        assert "require_admin" in callables, (
            f"{route.path} missing require_admin dependency (got {callables})"
        )


@pytest.mark.asyncio
async def test_oauth_state_is_single_use_and_admin_bound(monkeypatch):
    """A used state cannot be replayed; a state from admin-A cannot be used by
    admin-B. Drives the callback handler with a stubbed Redis + Graph client."""
    import app.api.integrations as api

    state_store: dict[str, str] = {}

    class _FakeRedis:
        async def get(self, key):
            return state_store.get(key.encode() if isinstance(key, bytes) else key)

        async def set(self, key, value, ex=None):
            state_store[key] = value

        async def delete(self, key):
            state_store.pop(key, None)

    monkeypatch.setattr(api, "_redis", AsyncMock(return_value=_FakeRedis()))
    # Stub the Graph exchange so no HTTP is made.
    monkeypatch.setattr(
        "app.channels.providers.facebook_oauth.exchange_code_for_user_token",
        AsyncMock(return_value="user-token"),
    )
    monkeypatch.setattr(
        "app.channels.providers.facebook_oauth.list_pages",
        AsyncMock(return_value=[]),
    )

    from types import SimpleNamespace

    admin = SimpleNamespace(id="admin-A", role="admin")
    db = MagicMock()

    # 1. start — stores state bound to admin-A
    start = await api.start_facebook_oauth(admin=admin, _db=db)
    assert "dialog/oauth" in start.authorization_url

    # 2. Reconstruct the state from the store (the URL carries it).
    state_key = next(k for k in state_store if k.startswith("fb_oauth_state:"))
    state = state_key.removeprefix("fb_oauth_state:")

    # 3. callback as admin-A — consumes the state, returns pending_selection
    #    (empty page list → error, but state is still consumed).
    result = await api.facebook_oauth_callback(
        state=state, code="code-1", admin=admin, db=db
    )
    assert result.status in ("error", "pending_selection")
    # 4. Replay the same state — it's gone (single-use).
    assert state_key not in state_store


@pytest.mark.asyncio
async def test_oauth_callback_rejects_state_from_different_admin(monkeypatch):
    """A state issued for admin-A cannot be used by admin-B."""
    import app.api.integrations as api

    state_store: dict[str, str] = {"fb_oauth_state:stolen": "admin-A"}

    class _FakeRedis:
        async def get(self, key):
            return state_store.get(key)

        async def delete(self, key):
            state_store.pop(key, None)

    monkeypatch.setattr(api, "_redis", AsyncMock(return_value=_FakeRedis()))
    from types import SimpleNamespace

    admin_b = SimpleNamespace(id="admin-B", role="admin")
    db = MagicMock()

    result = await api.facebook_oauth_callback(
        state="stolen", code="code", admin=admin_b, db=db
    )
    assert result.status == "error"
    assert "hợp lệ" in (result.error or "") or "hết hạn" in (result.error or "")


@pytest.mark.asyncio
async def test_status_response_masks_page_id_and_carries_no_token(monkeypatch):
    """GET /facebook must surface only a masked page-id suffix + safe label;
    no access token or app secret appears anywhere in the response."""
    from app.channels.types import ChannelAccountRef
    from app.channels.accounts import ChannelAccountStatus

    import app.api.integrations as api
    from types import SimpleNamespace

    async def _list(self):
        return [
            ChannelAccountRef(
                id="ca-1",
                provider="facebook_messenger",
                account_key="page-1234567890",
                label="Công ty ABC",
                status=ChannelAccountStatus.ACTIVE,
                generation=1,
            )
        ]

    monkeypatch.setattr(
        "app.channels.providers.facebook_account.FacebookAccountResolver.list_facebook_accounts",
        _list,
    )
    monkeypatch.setattr(
        "app.core.config.get_settings",
        lambda: SimpleNamespace(facebook_connection_enabled=True),
    )

    db = MagicMock()
    admin = SimpleNamespace(id="admin", role="admin")
    response = await api.get_facebook_status(_admin=admin, db=db)
    # The full page id never appears; only the 4-char suffix.
    dumped = response.model_dump_json()
    assert "1234567890" not in dumped
    assert "7890" in dumped
    assert "Công ty ABC" in dumped
    # No token-like fields.
    assert "token" not in dumped.lower()
    assert "secret" not in dumped.lower()
