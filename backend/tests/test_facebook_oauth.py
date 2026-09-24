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

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from urllib.parse import parse_qs, urlencode, urlparse
from uuid import UUID

import httpx
import pytest


def _oauth_flow_capsule(
    *, admin_id: UUID, token_version: int, pages: list[dict[str, str]] | None = None
) -> str:
    from app.services.integration_settings import IntegrationSettingsCipher

    return IntegrationSettingsCipher().encrypt(
        json.dumps(
            {
                "admin_id": str(admin_id),
                "token_version": token_version,
                "user_token": "secret-user-token",
                "pages": pages or [{"id": "page-1", "name": "Trang Một"}],
            }
        )
    )


def _encrypted_oauth_payload(payload) -> str:
    from app.services.integration_settings import IntegrationSettingsCipher

    return IntegrationSettingsCipher().encrypt(json.dumps(payload))


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
    # pages_user_gender is intentionally NOT requested: without the Business
    # Asset User Profile Access feature Facebook rejects the whole dialog with
    # "Invalid Scope: pages_user_gender", blocking Page linking. Gender is
    # inferred per turn by Jev instead.
    assert "pages_user_gender" not in MESSENGER_PERMISSIONS


def test_build_authorization_url_includes_state_scope_and_config():
    import app.channels.providers.facebook_oauth as oauth
    from app.services.integration_settings import FacebookOAuthConfig

    cfg = FacebookOAuthConfig(
        app_id="app-123",
        app_secret="app-secret",
        login_config_id="login-config-456",
        verify_token="verify",
        graph_api_version="v25.0",
        graph_api_base="https://graph.facebook.com",
    )

    redirect_uri = "https://bot.example.com/fb/cb?view=compact&source=settings"
    url = oauth.build_authorization_url(
        state="opaque-state-123", redirect_uri=redirect_uri, config=cfg
    )
    parsed = urlparse(url)
    query = parse_qs(parsed.query)

    assert parsed.scheme == "https"
    assert parsed.netloc == "www.facebook.com"
    assert parsed.path == "/v25.0/dialog/oauth"
    assert query["client_id"] == ["app-123"]
    assert query["config_id"] == ["login-config-456"]
    assert query["state"] == ["opaque-state-123"]
    assert query["redirect_uri"] == [redirect_uri]
    assert "pages_messaging" in query["scope"][0].split(",")


def test_build_authorization_url_rejects_missing_app_id():
    """A missing app_id must fail closed here, not produce a broken URL that
    Facebook rejects with a generic "Invalid app ID" page."""
    import app.channels.providers.facebook_oauth as oauth
    from app.services.integration_settings import FacebookOAuthConfig

    cfg = FacebookOAuthConfig(app_id="", app_secret="s", login_config_id="c")
    with pytest.raises(oauth.FacebookOAuthError):
        oauth.build_authorization_url(
            state="s", redirect_uri="https://example.com/cb", config=cfg
        )


@pytest.mark.asyncio
async def test_subscribe_app_requires_explicit_true_acknowledgement(monkeypatch):
    import app.channels.providers.facebook_oauth as oauth

    monkeypatch.setattr(
        oauth, "_bounded_post", AsyncMock(return_value={"success": True})
    )

    await oauth.subscribe_app_to_page("full-page-id", "secret-page-token")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response",
    [
        {},
        {"success": False},
        {"success": "true"},
        {"success": 1},
        {"error": {"message": "secret-page-token rejected"}},
    ],
)
async def test_subscribe_app_rejects_missing_or_malformed_acknowledgement(
    monkeypatch, response
):
    import app.channels.providers.facebook_oauth as oauth

    monkeypatch.setattr(oauth, "_bounded_post", AsyncMock(return_value=response))

    with pytest.raises(oauth.FacebookOAuthError) as exc_info:
        await oauth.subscribe_app_to_page("full-page-id", "secret-page-token")

    assert str(exc_info.value) == "page subscription failed"


@pytest.mark.asyncio
async def test_page_is_app_subscribed_true_when_app_in_list(monkeypatch):
    import app.channels.providers.facebook_oauth as oauth

    monkeypatch.setattr(
        oauth,
        "_bounded_get",
        AsyncMock(return_value={"data": [{"id": "other-app"}, {"id": "app-123"}]}),
    )

    assert await oauth.page_is_app_subscribed(
        "full-page-id", "secret-page-token", "app-123"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response",
    [
        {"data": [{"id": "other-app"}]},
        {"data": []},
        {},
    ],
)
async def test_page_is_app_subscribed_false_when_app_absent(monkeypatch, response):
    import app.channels.providers.facebook_oauth as oauth

    monkeypatch.setattr(oauth, "_bounded_get", AsyncMock(return_value=response))

    assert not await oauth.page_is_app_subscribed(
        "full-page-id", "secret-page-token", "app-123"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "app_id,response",
    [
        # Unknown app id: the lookup cannot prove anything; fail closed.
        ("", {"data": [{"id": "app-123"}]}),
        # Graph error envelope: raise without echoing the provider body.
        ("app-123", {"error": {"message": "secret-page-token invalid"}}),
    ],
)
async def test_page_is_app_subscribed_fails_closed(monkeypatch, app_id, response):
    import app.channels.providers.facebook_oauth as oauth

    monkeypatch.setattr(oauth, "_bounded_get", AsyncMock(return_value=response))

    with pytest.raises(oauth.FacebookOAuthError) as exc_info:
        await oauth.page_is_app_subscribed("full-page-id", "secret-page-token", app_id)

    assert "secret-page-token" not in str(exc_info.value)


# ─── admin endpoint RBAC + safe response ────────────────────────────────────
# (DB-backed resolver/lifecycle tests live in tests/integration/test_facebook_lifecycle.py)


@pytest.mark.asyncio
async def test_oauth_start_returns_400_when_app_id_not_configured(monkeypatch):
    """A missing Meta App ID surfaces a clear Vietnamese 400 instead of building
    an OAuth URL with an empty ``client_id`` that Facebook rejects generically."""
    import app.api.integrations as api
    from app.shared.domain.errors import BadRequestError

    from app.services.integration_settings import FacebookOAuthConfig

    class _SettingsService:
        def __init__(self, _db):
            pass

        async def resolve_facebook_oauth(self):
            # No app_id — simulates an admin who has not yet configured Meta App
            # credentials via the UI and has no META_APP_ID env var either.
            return FacebookOAuthConfig(app_id="")

    monkeypatch.setattr(api, "IntegrationSettingsService", _SettingsService)

    with pytest.raises(BadRequestError) as exc_info:
        await api.start_facebook_oauth(
            admin=SimpleNamespace(id=UUID(int=1), token_version=1),
            db=MagicMock(),
        )

    assert exc_info.value.status_code == 400
    assert "Meta App ID" in exc_info.value.detail


@pytest.mark.asyncio
async def test_reveal_returns_plaintext_secrets_and_forbids_caching(monkeypatch):
    """Reveal hands a re-authenticated admin the stored secrets verbatim, uncached.

    The masked GET view cannot serve re-registering a webhook on Meta, which
    needs the verify token exactly. The response must not be cached anywhere.
    SEC-07: the request carries the admin's password again; the endpoint passes
    it (with the actor's stored hash) to the step-up-gated service call.
    """
    import app.api.integrations as api
    from fastapi import Response

    calls: list[dict] = []

    class _SettingsService:
        def __init__(self, db):
            pass

        async def reveal_facebook_oauth(self, *, actor_id, password, password_hash):
            calls.append(
                {"actor_id": actor_id, "password": password, "password_hash": password_hash}
            )
            return SimpleNamespace(
                app_secret="super-secret-value",
                verify_token="verify-token-value",
            )

    monkeypatch.setattr(api, "IntegrationSettingsService", _SettingsService)
    response = Response()
    result = await api.reveal_facebook_credentials(
        response=response,
        password="re-entered-password",
        admin=SimpleNamespace(id="admin-id", password_hash="stored-hash"),
        db=MagicMock(),
    )

    assert result.facebook_app_secret == "super-secret-value"
    assert result.facebook_webhook_verify_token == "verify-token-value"
    assert response.headers["Cache-Control"] == "no-store"
    assert calls == [
        {
            "actor_id": "admin-id",
            "password": "re-entered-password",
            "password_hash": "stored-hash",
        }
    ]


def _reveal_app(monkeypatch, *, password_hash: str):
    """Real integrations router + real step-up service over a stub session."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.api import integrations as api
    from app.api.auth_dependencies import require_admin
    from app.core.config import Settings
    from app.core.errors import register_domain_exception_handlers
    from app.services.integration_settings import IntegrationSettingsService
    from app.shared.infrastructure.db import get_request_db

    class _Service(IntegrationSettingsService):
        def __init__(self, db) -> None:
            super().__init__(
                db,
                settings=Settings(
                    app_env="development",
                    meta_app_secret="meta-secret-value",
                    meta_webhook_verify_token="verify-token-value",
                ),
            )

    db = MagicMock()
    db.scalars = AsyncMock(return_value=SimpleNamespace(all=lambda: []))
    db.flush = AsyncMock()
    db.commit = AsyncMock()

    app = FastAPI()
    register_domain_exception_handlers(app)
    app.include_router(api.router, prefix="/api/v1")
    app.dependency_overrides[require_admin] = lambda: SimpleNamespace(
        id=UUID(int=7), password_hash=password_hash
    )
    app.dependency_overrides[get_request_db] = lambda: db
    monkeypatch.setattr(api, "IntegrationSettingsService", _Service)
    return TestClient(app)


def test_reveal_endpoint_rejects_a_request_without_step_up(monkeypatch):
    """SEC-07: no password re-entry → the handler never runs, nothing is revealed."""
    from app.core.security import hash_password_sync

    client = _reveal_app(monkeypatch, password_hash=hash_password_sync("s3cret-password"))
    path = "/api/v1/admin/integrations/facebook/credentials/reveal"

    assert client.post(path).status_code == 422
    assert client.post(path, json={"password": ""}).status_code == 422
    assert client.post(path, json={"password": "wrong-password"}).status_code == 400


def test_reveal_endpoint_returns_secrets_after_correct_password(monkeypatch):
    """SEC-07: the correct re-entry reveals the secrets, uncached and audited."""
    from app.core.security import hash_password_sync

    audits: list = []

    async def _record_audit(db, **kwargs):
        audits.append(kwargs)
        return None

    monkeypatch.setattr("app.services.integration_settings.providers.facebook.record_audit", _record_audit)
    client = _reveal_app(monkeypatch, password_hash=hash_password_sync("s3cret-password"))

    response = client.post(
        "/api/v1/admin/integrations/facebook/credentials/reveal",
        json={"password": "s3cret-password"},
    )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {
        "facebook_app_secret": "meta-secret-value",
        "facebook_webhook_verify_token": "verify-token-value",
    }
    assert [a["action"] for a in audits] == ["reveal_facebook_credentials"]


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
        "/admin/integrations/facebook/credentials",
        "/admin/integrations/facebook/credentials/reveal",
        "/admin/integrations/facebook",
        "/admin/integrations/facebook/test",
        "/admin/integrations/facebook/pages/{page_id}/projects",
        "/admin/integrations/facebook/pages/{page_id}/projects/{project_id}",
    }
    # The callback is authenticated by its single-use state because Meta's
    # browser redirect cannot carry the application's Authorization header.
    # Every other Facebook endpoint remains Bearer-authenticated admin-only.
    for route in router.routes:
        if "facebook" not in route.path:
            continue
        callables = {getattr(d.call, "__name__", "") for d in route.dependant.dependencies}
        if route.path.endswith("/oauth/callback"):
            assert "require_admin" not in callables
        else:
            assert "require_admin" in callables, (
                f"{route.path} missing require_admin dependency (got {callables})"
            )


@pytest.mark.asyncio
async def test_oauth_state_is_single_use_and_admin_bound(monkeypatch):
    """A used state cannot be replayed; a state from admin-A cannot be used by
    admin-B. Drives the callback handler with a stubbed Redis + Graph client."""
    import app.api.integrations as api
    from app.services.integration_settings import FacebookOAuthConfig

    state_store: dict[str, str] = {}

    class _FakeRedis:
        async def set(self, key, value, ex=None):
            state_store[key] = value

        async def getdel(self, key):
            return state_store.pop(key, None)

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

    admin_id = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
    admin = SimpleNamespace(
        id=admin_id, role="admin", disabled=False, token_version=7
    )
    db = MagicMock()
    db.get = AsyncMock(return_value=admin)

    # Stub the settings service so start + callback resolve app credentials
    # without hitting Postgres (the callback now reads the DB-resolved config
    # before exchanging the code).
    _oauth_cfg = FacebookOAuthConfig(
        app_id="app-123",
        app_secret="app-secret",
        login_config_id="cfg-1",
        verify_token="verify",
    )

    class _SettingsService:
        def __init__(self, _db):
            pass

        async def resolve_facebook_oauth(self):
            return _oauth_cfg

    monkeypatch.setattr(api, "IntegrationSettingsService", _SettingsService)

    # 1. start — stores state bound to admin-A
    start = await api.start_facebook_oauth(admin=admin, db=db)
    authorization_url = urlparse(start.authorization_url)
    assert authorization_url.netloc == "www.facebook.com"
    assert authorization_url.path.endswith("/dialog/oauth")

    # 2. Reconstruct the state from the store (the URL carries it).
    state_key = next(k for k in state_store if k.startswith("fb_oauth_state:"))
    state = state_key.removeprefix("fb_oauth_state:")

    stored_state = json.loads(state_store[state_key])
    assert stored_state == {"admin_id": str(admin_id), "token_version": 7}

    # 3. callback consumes the state before returning a generic error redirect
    #    (empty page list), without needing an Authorization header.
    result = await api.facebook_oauth_callback(
        state=state, code="code-1", db=db
    )
    assert result.status_code == 302
    assert "facebook_oauth_status=error" in result.headers["location"]
    assert "facebook_oauth_error=no_pages" in result.headers["location"]
    # 4. Replay the same state — it's gone (single-use).
    assert state_key not in state_store
    replay = await api.facebook_oauth_callback(state=state, code="code-1", db=db)
    assert "facebook_oauth_error=invalid_state" in replay.headers["location"]


@pytest.mark.asyncio
async def test_oauth_callback_rejects_changed_admin_session(monkeypatch):
    """A state cannot survive an admin token-version change."""
    import app.api.integrations as api

    admin_id = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
    state_store: dict[str, str] = {
        "fb_oauth_state:stale": json.dumps(
            {"admin_id": str(admin_id), "token_version": 3}
        )
    }

    class _FakeRedis:
        async def getdel(self, key):
            return state_store.pop(key, None)

    monkeypatch.setattr(api, "_redis", AsyncMock(return_value=_FakeRedis()))
    db = MagicMock()
    db.get = AsyncMock(
        return_value=SimpleNamespace(
            id=admin_id, role="admin", disabled=False, token_version=4
        )
    )

    result = await api.facebook_oauth_callback(
        state="stale", code="code", db=db
    )
    assert result.status_code == 302
    assert "facebook_oauth_error=session_changed" in result.headers["location"]
    assert "stale" not in state_store


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "provider_error",
    [
        httpx.ReadTimeout("provider transport exposed secret-user-token"),
        ValueError("malformed provider JSON exposed secret-user-token"),
    ],
)
async def test_oauth_callback_safely_redirects_expected_provider_failures(
    monkeypatch, provider_error
):
    import app.api.integrations as api

    admin_id = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
    state_store = {
        "fb_oauth_state:provider-failure": json.dumps(
            {"admin_id": str(admin_id), "token_version": 3}
        )
    }

    class _FakeRedis:
        async def getdel(self, key):
            return state_store.pop(key, None)

    list_pages = AsyncMock()
    monkeypatch.setattr(api, "_redis", AsyncMock(return_value=_FakeRedis()))
    monkeypatch.setattr(
        "app.channels.providers.facebook_oauth.exchange_code_for_user_token",
        AsyncMock(side_effect=provider_error),
    )
    monkeypatch.setattr(
        "app.channels.providers.facebook_oauth.list_pages", list_pages
    )
    db = MagicMock()
    db.get = AsyncMock(
        return_value=SimpleNamespace(
            id=admin_id, role="admin", disabled=False, token_version=3
        )
    )

    from app.services.integration_settings import FacebookOAuthConfig

    class _SettingsService:
        def __init__(self, _db):
            pass

        async def resolve_facebook_oauth(self):
            return FacebookOAuthConfig(
                app_id="app-123",
                app_secret="app-secret",
                login_config_id="cfg-1",
                verify_token="verify",
            )

    monkeypatch.setattr(api, "IntegrationSettingsService", _SettingsService)

    response = await api.facebook_oauth_callback(
        state="provider-failure", code="secret-provider-code", db=db
    )

    location = response.headers["location"]
    assert response.status_code == 302
    assert "facebook_oauth_error=exchange_failed" in location
    assert "secret-user-token" not in location
    assert "secret-provider-code" not in location
    list_pages.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("admin", "error_code"),
    [
        (None, "invalid_admin"),
        (SimpleNamespace(role="admin", disabled=True, token_version=3), "invalid_admin"),
        (SimpleNamespace(role="recruiter", disabled=False, token_version=3), "invalid_admin"),
    ],
)
async def test_oauth_callback_reloads_and_validates_admin(monkeypatch, admin, error_code):
    import app.api.integrations as api

    admin_id = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
    state_store = {
        "fb_oauth_state:state": json.dumps(
            {"admin_id": str(admin_id), "token_version": 3}
        )
    }

    class _FakeRedis:
        async def getdel(self, key):
            return state_store.pop(key, None)

    monkeypatch.setattr(api, "_redis", AsyncMock(return_value=_FakeRedis()))
    db = MagicMock()
    db.get = AsyncMock(return_value=admin)

    result = await api.facebook_oauth_callback(state="state", code="code", db=db)

    assert f"facebook_oauth_error={error_code}" in result.headers["location"]


@pytest.mark.asyncio
async def test_oauth_callback_redirect_is_allowlisted_and_opaque(monkeypatch):
    import app.api.integrations as api
    from app.channels.providers.facebook_oauth import FacebookPageSummary

    admin_id = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
    state_store: dict[str, str] = {
        "fb_oauth_state:valid": json.dumps(
            {"admin_id": str(admin_id), "token_version": 3}
        )
    }

    class _FakeRedis:
        async def getdel(self, key):
            return state_store.pop(key, None)

        async def set(self, key, value, ex=None):
            state_store[key] = value

    monkeypatch.setattr(api, "_redis", AsyncMock(return_value=_FakeRedis()))
    monkeypatch.setattr(
        api,
        "_fb_callback_url",
        lambda: "https://app.example.com/api/v1/admin/integrations/facebook/oauth/callback",
    )
    monkeypatch.setattr(
        api,
        "_fb_frontend_redirect_url",
        lambda **params: "https://app.example.com/#/settings?" + urlencode(
            {
                "facebook_oauth_status": params["status"],
                "facebook_oauth_flow_id": params["flow_id"],
            }
        ),
    )
    monkeypatch.setattr(
        "app.channels.providers.facebook_oauth.exchange_code_for_user_token",
        AsyncMock(return_value="secret-user-token"),
    )
    monkeypatch.setattr(
        "app.channels.providers.facebook_oauth.list_pages",
        AsyncMock(return_value=[FacebookPageSummary(id="page-1", name="Trang Một")]),
    )
    db = MagicMock()
    db.get = AsyncMock(
        return_value=SimpleNamespace(
            id=admin_id, role="admin", disabled=False, token_version=3
        )
    )

    from app.services.integration_settings import FacebookOAuthConfig

    class _SettingsService:
        def __init__(self, _db):
            pass

        async def resolve_facebook_oauth(self):
            return FacebookOAuthConfig(
                app_id="app-123",
                app_secret="app-secret",
                login_config_id="cfg-1",
                verify_token="verify",
            )

    monkeypatch.setattr(api, "IntegrationSettingsService", _SettingsService)

    response = await api.facebook_oauth_callback(
        state="valid", code="provider-secret-code", db=db
    )

    location = response.headers["location"]
    parsed = urlparse(location)
    fragment_path, fragment_query = parsed.fragment.split("?", 1)
    query = parse_qs(fragment_query)
    assert (parsed.scheme, parsed.netloc, fragment_path) == (
        "https",
        "app.example.com",
        "/settings",
    )
    assert query["facebook_oauth_status"] == ["pending_selection"]
    assert len(query["facebook_oauth_flow_id"][0]) >= 16
    assert "provider-secret-code" not in location
    assert "secret-user-token" not in location
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["referrer-policy"] == "no-referrer"

    from app.services.integration_settings import IntegrationSettingsCipher

    flow_key = next(key for key in state_store if key.startswith("fb_oauth_flow:"))
    assert flow_key.startswith(f"fb_oauth_flow:{admin_id}:")
    flow = json.loads(IntegrationSettingsCipher().decrypt(state_store[flow_key]))
    assert flow["admin_id"] == str(admin_id)
    assert flow["token_version"] == 3


@pytest.mark.asyncio
async def test_oauth_pages_accepts_only_own_current_session(monkeypatch):
    import app.api.integrations as api

    admin_id = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
    capsule = _oauth_flow_capsule(admin_id=admin_id, token_version=3)

    requested_keys: list[str] = []

    class _FakeRedis:
        async def get(self, key):
            requested_keys.append(key)
            return capsule

    monkeypatch.setattr(api, "_redis", AsyncMock(return_value=_FakeRedis()))
    monkeypatch.setattr(
        "app.channels.providers.facebook_account.FacebookAccountResolver.list_facebook_accounts",
        AsyncMock(return_value=[]),
    )
    admin = SimpleNamespace(id=admin_id, token_version=3)

    result = await api.list_facebook_pages(
        flow_id="owned-flow", admin=admin, db=MagicMock()
    )

    assert [(page.id, page.name) for page in result.pages] == [
        ("page-1", "Trang Một")
    ]
    assert requested_keys == [f"fb_oauth_flow:{admin_id}:owned-flow"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "admin",
    [
        SimpleNamespace(
            id=UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"), token_version=3
        ),
        SimpleNamespace(
            id=UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"), token_version=4
        ),
    ],
)
async def test_oauth_pages_rejects_other_admin_or_changed_session(monkeypatch, admin):
    import app.api.integrations as api

    capsule = _oauth_flow_capsule(
        admin_id=UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
        token_version=3,
    )

    class _FakeRedis:
        async def get(self, key):
            return capsule

    monkeypatch.setattr(api, "_redis", AsyncMock(return_value=_FakeRedis()))

    with pytest.raises(api.GoneError) as exc_info:
        await api.list_facebook_pages(
            flow_id="not-owned", admin=admin, db=MagicMock()
        )

    assert exc_info.value.status_code == 410
    assert exc_info.value.detail == (
        "Phiên chọn Trang không hợp lệ hoặc đã hết hạn. Vui lòng kết nối lại."
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "capsule",
    [
        None,
        "not-valid-ciphertext",
        json.dumps(
            {
                "admin_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                "token_version": 3,
                "user_token": "plaintext-must-not-be-accepted",
                "pages": [{"id": "page-1", "name": "Trang Một"}],
            }
        ),
    ],
)
async def test_oauth_pages_missing_or_invalid_flow_returns_410(monkeypatch, capsule):
    import app.api.integrations as api

    class _FakeRedis:
        async def get(self, key):
            return capsule

    monkeypatch.setattr(api, "_redis", AsyncMock(return_value=_FakeRedis()))

    with pytest.raises(api.GoneError) as exc_info:
        await api.list_facebook_pages(
            flow_id="expired-flow",
            admin=SimpleNamespace(
                id=UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"), token_version=3
            ),
            db=MagicMock(),
        )

    assert exc_info.value.status_code == 410
    assert "không hợp lệ hoặc đã hết hạn" in exc_info.value.detail


@pytest.mark.asyncio
async def test_oauth_complete_wrong_admin_does_not_consume_owner_flow(monkeypatch):
    import app.api.integrations as api
    from app.schemas.integrations import FacebookOAuthCompleteRequest

    owner_id = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
    other_id = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
    owner_key = f"fb_oauth_flow:{owner_id}:owned-flow"
    store = {
        owner_key: _oauth_flow_capsule(admin_id=owner_id, token_version=3)
    }

    class _FakeRedis:
        async def getdel(self, key):
            return store.pop(key, None)

    monkeypatch.setattr(api, "_redis", AsyncMock(return_value=_FakeRedis()))

    with pytest.raises(api.GoneError) as exc_info:
        await api.complete_facebook_oauth(
            payload=FacebookOAuthCompleteRequest(
                flow_id="owned-flow", page_id="page-1"
            ),
            admin=SimpleNamespace(id=other_id, token_version=3),
            db=MagicMock(),
        )

    assert exc_info.value.status_code == 410
    assert owner_key in store


@pytest.mark.asyncio
async def test_oauth_complete_changed_session_consumes_and_rejects_flow(monkeypatch):
    import app.api.integrations as api
    from app.schemas.integrations import FacebookOAuthCompleteRequest

    admin_id = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
    flow_key = f"fb_oauth_flow:{admin_id}:stale-flow"
    store = {
        flow_key: _oauth_flow_capsule(admin_id=admin_id, token_version=3)
    }

    class _FakeRedis:
        async def getdel(self, key):
            return store.pop(key, None)

    monkeypatch.setattr(api, "_redis", AsyncMock(return_value=_FakeRedis()))

    with pytest.raises(api.GoneError) as exc_info:
        await api.complete_facebook_oauth(
            payload=FacebookOAuthCompleteRequest(
                flow_id="stale-flow", page_id="page-1"
            ),
            admin=SimpleNamespace(id=admin_id, token_version=4),
            db=MagicMock(),
        )

    assert exc_info.value.status_code == 410
    assert flow_key not in store


@pytest.mark.asyncio
async def test_oauth_complete_atomically_consumes_before_side_effects(monkeypatch):
    import app.api.integrations as api
    from app.channels.accounts import ChannelAccountStatus
    from app.schemas.integrations import FacebookOAuthCompleteRequest

    admin_id = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
    flow_id = "single-use-flow"
    flow_key = f"fb_oauth_flow:{admin_id}:{flow_id}"
    store = {
        flow_key: _oauth_flow_capsule(admin_id=admin_id, token_version=3)
    }

    class _FakeRedis:
        async def getdel(self, key):
            return store.pop(key, None)

    get_page_token = AsyncMock(return_value="secret-page-token")
    subscribe = AsyncMock(return_value=None)
    activate = AsyncMock(
        return_value=SimpleNamespace(status=ChannelAccountStatus.ACTIVE)
    )
    monkeypatch.setattr(api, "_redis", AsyncMock(return_value=_FakeRedis()))
    monkeypatch.setattr(
        "app.channels.providers.facebook_oauth.get_page_access_token", get_page_token
    )
    monkeypatch.setattr(
        "app.channels.providers.facebook_oauth.subscribe_app_to_page", subscribe
    )
    monkeypatch.setattr(
        "app.channels.providers.facebook_account.FacebookPageLifecycle.activate_or_reactivate",
        activate,
    )
    request = FacebookOAuthCompleteRequest(flow_id=flow_id, page_id="page-1")
    admin = SimpleNamespace(id=admin_id, token_version=3)

    result = await api.complete_facebook_oauth(
        payload=request, admin=admin, db=MagicMock()
    )
    assert result.status == ChannelAccountStatus.ACTIVE

    with pytest.raises(api.GoneError) as exc_info:
        await api.complete_facebook_oauth(
            payload=request, admin=admin, db=MagicMock()
        )

    assert exc_info.value.status_code == 410
    get_page_token.assert_awaited_once()
    subscribe.assert_awaited_once()
    activate.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "provider_error",
    [
        httpx.ReadTimeout("provider transport exposed secret-page-token"),
        ValueError("malformed provider JSON exposed secret-page-token"),
    ],
)
async def test_oauth_complete_maps_expected_provider_failures_to_generic_502(
    monkeypatch, provider_error
):
    import app.api.integrations as api
    from app.schemas.integrations import FacebookOAuthCompleteRequest

    admin_id = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
    flow_id = "provider-failure"
    flow_key = f"fb_oauth_flow:{admin_id}:{flow_id}"
    store = {
        flow_key: _oauth_flow_capsule(admin_id=admin_id, token_version=3)
    }

    class _FakeRedis:
        async def getdel(self, key):
            return store.pop(key, None)

    activate = AsyncMock()
    monkeypatch.setattr(api, "_redis", AsyncMock(return_value=_FakeRedis()))
    monkeypatch.setattr(
        "app.channels.providers.facebook_oauth.get_page_access_token",
        AsyncMock(side_effect=provider_error),
    )
    monkeypatch.setattr(
        "app.channels.providers.facebook_account.FacebookPageLifecycle.activate_or_reactivate",
        activate,
    )

    with pytest.raises(api.UpstreamError) as exc_info:
        await api.complete_facebook_oauth(
            payload=FacebookOAuthCompleteRequest(
                flow_id=flow_id, page_id="page-1"
            ),
            admin=SimpleNamespace(id=admin_id, token_version=3),
            db=MagicMock(),
        )

    assert exc_info.value.status_code == 502
    assert exc_info.value.detail == (
        "Kích hoạt Trang thất bại. Vui lòng kết nối lại."
    )
    assert "secret-page-token" not in exc_info.value.detail
    assert flow_key not in store
    activate.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {},
        {
            "admin_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            "token_version": 3,
            "user_token": "",
            "pages": [{"id": "page-1", "name": "Trang Một"}],
        },
        {
            "admin_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            "token_version": 3,
            "user_token": "token",
            "pages": [],
        },
        {
            "admin_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            "token_version": 3,
            "user_token": "token",
            "pages": [{"id": "", "name": "Trang Một"}],
        },
        {
            "admin_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            "token_version": 3,
            "user_token": "token",
            "pages": [{"id": "page-1", "name": ""}],
        },
        {
            "admin_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            "token_version": 3,
            "user_token": "token",
            "pages": ["not-a-page"],
        },
    ],
)
async def test_oauth_pages_rejects_malformed_decrypted_capsules(monkeypatch, payload):
    import app.api.integrations as api

    capsule = _encrypted_oauth_payload(payload)

    class _FakeRedis:
        async def get(self, key):
            return capsule

    monkeypatch.setattr(api, "_redis", AsyncMock(return_value=_FakeRedis()))

    with pytest.raises(api.GoneError) as exc_info:
        await api.list_facebook_pages(
            flow_id="malformed",
            admin=SimpleNamespace(
                id=UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"), token_version=3
            ),
            db=MagicMock(),
        )

    assert exc_info.value.status_code == 410


def test_oauth_redirect_uses_first_allowlisted_origin(monkeypatch):
    import app.api.integrations as api

    monkeypatch.setattr(
        "app.integrations.admin_runtime.get_settings",
        lambda: SimpleNamespace(
            facebook_callback_allowlist=[
                "https://admin.example.com/",
                "https://unused.example.com",
            ]
        ),
    )

    assert api._fb_callback_url() == (
        "https://admin.example.com/api/v1/admin/integrations/facebook/oauth/callback"
    )
    assert api._fb_frontend_redirect_url(
        status="error", error="invalid_state"
    ) == (
        "https://admin.example.com/#/settings?"
        "facebook_oauth_status=error&facebook_oauth_error=invalid_state"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "provider_error",
    [
        httpx.ReadTimeout("health probe exposed secret-page-token"),
        ValueError("malformed health JSON exposed secret-page-token"),
    ],
)
async def test_facebook_health_maps_expected_provider_failures_to_unhealthy(
    monkeypatch, provider_error
):
    import app.api.integrations as api
    from app.channels.accounts import ChannelAccountStatus
    from app.channels.types import ChannelAccountRef

    active = ChannelAccountRef(
        id="account-1",
        provider="facebook_messenger",
        account_key="full-page-id-9876",
        label="Trang Một",
        status=ChannelAccountStatus.ACTIVE,
        generation=1,
    )

    class _SettingsService:
        def __init__(self, db):
            pass

        async def resolve_facebook(self, page_id):
            assert page_id == "full-page-id-9876"
            return SimpleNamespace(
                page_access_token="secret-page-token", app_id="app-123"
            )

    monkeypatch.setattr(
        "app.services.integration_settings.IntegrationSettingsService",
        _SettingsService,
    )
    monkeypatch.setattr(
        "app.channels.providers.facebook_account.FacebookAccountResolver.active_facebook_page",
        AsyncMock(return_value=active),
    )
    # The subscription lookup is the call made with the Page token, so it is
    # what surfaces a revoked token or a provider transport failure.
    monkeypatch.setattr(
        "app.channels.providers.facebook_oauth.page_is_app_subscribed",
        AsyncMock(side_effect=provider_error),
    )

    result = await api.test_facebook_connection(
        _admin=SimpleNamespace(id="admin-id"), db=MagicMock()
    )

    assert result.healthy is False
    assert result.error == (
        "Không kiểm tra được đăng ký webhook của ứng dụng trên Trang."
    )
    assert "secret-page-token" not in result.error


async def _health_probe_mocks(monkeypatch, *, subscribed) -> None:
    """Shared wiring for test_facebook_connection happy-path variants.

    Stubs the resolver, settings service, identity probe, and subscription
    lookup so the endpoint runs without Postgres or external HTTP. The
    settings service is patched on its source module because the endpoint
    re-imports it inside the handler.
    """
    from app.channels.accounts import ChannelAccountStatus
    from app.channels.types import ChannelAccountRef

    active = ChannelAccountRef(
        id="account-1",
        provider="facebook_messenger",
        account_key="full-page-id-9876",
        label="Trang Một",
        status=ChannelAccountStatus.ACTIVE,
        generation=1,
    )

    class _SettingsService:
        def __init__(self, db):
            pass

        async def resolve_facebook(self, page_id):
            assert page_id == "full-page-id-9876"
            return SimpleNamespace(
                page_access_token="secret-page-token", app_id="app-123"
            )

    monkeypatch.setattr(
        "app.services.integration_settings.IntegrationSettingsService",
        _SettingsService,
    )
    monkeypatch.setattr(
        "app.channels.providers.facebook_account.FacebookAccountResolver.active_facebook_page",
        AsyncMock(return_value=active),
    )
    monkeypatch.setattr(
        "app.channels.providers.facebook_oauth.probe_page_identity",
        AsyncMock(return_value="full-page-id-9876"),
    )
    monkeypatch.setattr(
        "app.channels.providers.facebook_oauth.page_is_app_subscribed",
        AsyncMock(return_value=subscribed),
    )


@pytest.mark.asyncio
async def test_facebook_health_healthy_when_app_subscribed(monkeypatch):
    """A valid token AND a present webhook subscription report healthy with
    the subscription confirmed, so the operator can trust the pre-cutover
    probe."""
    import app.api.integrations as api

    await _health_probe_mocks(monkeypatch, subscribed=True)

    result = await api.test_facebook_connection(
        _admin=SimpleNamespace(id="admin-id"), db=MagicMock()
    )

    assert result.healthy is True
    assert result.app_subscribed is True
    assert result.error is None


@pytest.mark.asyncio
async def test_facebook_health_unhealthy_when_app_not_subscribed(monkeypatch):
    """A valid Page token alone is not healthy: if the app is missing from the
    Page's subscribed_apps edge the probe fails so the operator re-connects
    before cutover (e.g. a competing platform altered the Page's integrations)."""
    import app.api.integrations as api

    await _health_probe_mocks(monkeypatch, subscribed=False)

    result = await api.test_facebook_connection(
        _admin=SimpleNamespace(id="admin-id"), db=MagicMock()
    )

    assert result.healthy is False
    assert result.app_subscribed is False
    assert "webhook" in (result.error or "")
    assert "secret-page-token" not in (result.error or "")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "lookup_error",
    [
        httpx.ReadTimeout("provider transport exposed secret-page-token"),
        ValueError("malformed subscription JSON exposed secret-page-token"),
    ],
)
async def test_facebook_health_subscription_lookup_failure_is_unhealthy(
    monkeypatch, lookup_error
):
    """A transport/parse failure of the subscription lookup is inconclusive:
    report unhealthy with app_subscribed=None and a generic Vietnamese error."""
    import app.api.integrations as api

    await _health_probe_mocks(monkeypatch, subscribed=True)
    monkeypatch.setattr(
        "app.channels.providers.facebook_oauth.page_is_app_subscribed",
        AsyncMock(side_effect=lookup_error),
    )

    result = await api.test_facebook_connection(
        _admin=SimpleNamespace(id="admin-id"), db=MagicMock()
    )

    assert result.healthy is False
    assert result.app_subscribed is None
    assert result.error == (
        "Không kiểm tra được đăng ký webhook của ứng dụng trên Trang."
    )
    assert "secret-page-token" not in result.error


@pytest.mark.asyncio
async def test_disconnect_resolves_active_page_server_side(monkeypatch):
    import app.api.integrations as api
    from app.channels.accounts import ChannelAccountStatus
    from app.channels.types import ChannelAccountRef

    active = ChannelAccountRef(
        id="account-1",
        provider="facebook_messenger",
        account_key="full-page-id-9876",
        label="Trang Một",
        status=ChannelAccountStatus.ACTIVE,
        generation=1,
    )
    events: list[str] = []

    async def _disconnect(**kwargs):
        events.append("local_disconnect")
        return SimpleNamespace(
            label="Trang Một", status=ChannelAccountStatus.INACTIVE
        )

    async def _unsubscribe(page_id, page_token):
        events.append("meta_unsubscribe")

    disconnect = AsyncMock(side_effect=_disconnect)
    unsubscribe = AsyncMock(side_effect=_unsubscribe)

    class _SettingsService:
        def __init__(self, db):
            pass

        async def resolve_facebook(self, page_id):
            assert page_id == "full-page-id-9876"
            return SimpleNamespace(page_access_token="secret-page-token")

    monkeypatch.setattr(api, "IntegrationSettingsService", _SettingsService)
    monkeypatch.setattr(
        "app.channels.providers.facebook_account.FacebookAccountResolver.list_facebook_accounts",
        AsyncMock(return_value=[active]),
    )
    monkeypatch.setattr(
        "app.channels.providers.facebook_account.FacebookPageLifecycle.disconnect",
        disconnect,
    )
    monkeypatch.setattr(
        "app.channels.providers.facebook_oauth.unsubscribe_app_from_page",
        unsubscribe,
    )

    admin = SimpleNamespace(id="admin-id")
    result = await api.disconnect_facebook(admin=admin, db=MagicMock())

    disconnect.assert_awaited_once_with(
        page_id="full-page-id-9876", admin_id="admin-id"
    )
    unsubscribe.assert_awaited_once_with(
        "full-page-id-9876", "secret-page-token"
    )
    assert events == ["meta_unsubscribe", "local_disconnect"]
    assert result.page_id_suffix == "9876"


@pytest.mark.asyncio
async def test_disconnect_deactivates_locally_when_meta_unsubscribe_fails(monkeypatch):
    import app.api.integrations as api
    from app.channels.accounts import ChannelAccountStatus
    from app.channels.types import ChannelAccountRef

    active = ChannelAccountRef(
        id="account-1",
        provider="facebook_messenger",
        account_key="full-page-id-9876",
        label="Trang Một",
        status=ChannelAccountStatus.ACTIVE,
        generation=1,
    )
    disconnect = AsyncMock(
        return_value=SimpleNamespace(
            label="Trang Một", status=ChannelAccountStatus.INACTIVE
        )
    )

    class _SettingsService:
        def __init__(self, db):
            pass

        async def resolve_facebook(self, page_id):
            return SimpleNamespace(page_access_token="secret-page-token")

    monkeypatch.setattr(api, "IntegrationSettingsService", _SettingsService)
    monkeypatch.setattr(
        "app.channels.providers.facebook_account.FacebookAccountResolver.list_facebook_accounts",
        AsyncMock(return_value=[active]),
    )
    monkeypatch.setattr(
        "app.channels.providers.facebook_account.FacebookPageLifecycle.disconnect",
        disconnect,
    )
    monkeypatch.setattr(
        "app.channels.providers.facebook_oauth.unsubscribe_app_from_page",
        AsyncMock(
            side_effect=httpx.ReadTimeout(
                "unsubscribe exposed secret-page-token"
            )
        ),
    )

    result = await api.disconnect_facebook(
        admin=SimpleNamespace(id="admin-id"), db=MagicMock()
    )

    disconnect.assert_awaited_once_with(
        page_id="full-page-id-9876", admin_id="admin-id"
    )
    assert result.status == ChannelAccountStatus.INACTIVE
    assert "secret-page-token" not in result.model_dump_json()


@pytest.mark.asyncio
async def test_disconnect_returns_404_when_no_active_page(monkeypatch):
    import app.api.integrations as api

    monkeypatch.setattr(
        "app.channels.providers.facebook_account.FacebookAccountResolver.list_facebook_accounts",
        AsyncMock(return_value=[]),
    )

    with pytest.raises(api.NotFoundError) as exc_info:
        await api.disconnect_facebook(
            admin=SimpleNamespace(id="admin-id"), db=MagicMock()
        )

    assert exc_info.value.status_code == 404


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

    db = MagicMock()
    admin = SimpleNamespace(id="admin", role="admin")
    response = await api.get_facebook_status(_admin=admin, db=db)
    # `enabled` is derived from whether an active Page account exists — NOT from
    # a deploy-time env toggle. Mirrors Zalo "configured" semantics.
    assert response.enabled is True
    # Multi-Page contract (additive): the full Page id is exposed in the
    # dedicated `page_id` field (per-Page route key); the masked suffix and
    # safe label stay. No token-like fields anywhere.
    dumped = response.model_dump()
    assert dumped["accounts"][0]["page_id"] == "page-1234567890"
    assert dumped["accounts"][0]["page_id_suffix"] == "7890"
    assert dumped["accounts"][0]["label"] == "Công ty ABC"
    dumped_json = response.model_dump_json()
    assert "token" not in dumped_json.lower()
    assert "secret" not in dumped_json.lower()
