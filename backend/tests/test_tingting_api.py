"""Deployment-wide TingTing integration: key storage, egress, prompt, tool.

Pure-unit coverage (no DB, no network): the integration setting row is a fake
session, the HTTP client is a stub, and Redis admission is monkeypatched. The
point of these tests is the *shape* the agent depends on — one key, one fixed
origin, one call path, an embedded guide, and truthful outcomes.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import httpx
import pytest

from app.graph.tingting_guide import (
    TINGTING_API_BLOCK_HEADER,
    TINGTING_API_GUIDE,
    tingting_api_prompt_block,
)
from app.graph.tools.tingting_api import call_tingting_api
from app.services import tingting_api as mod
from app.services.integration_settings.cipher import IntegrationSettingsCipher
from app.services.tingting_api import (
    TINGTING_API_BASE_DEFAULT,
    TINGTING_API_KEY_SETTING,
    TingtingApiRuntime,
    TingtingApiService,
    resolve_base_url,
)

_KEY = "ttk_live_test_key"


class _FakeSession:
    """Minimal AsyncSession stand-in holding the one integration row."""

    def __init__(self, row: SimpleNamespace | None = None) -> None:
        self.row = row
        self.commits = 0
        self.added: list[object] = []

    async def get(self, _model, key):  # noqa: ANN001
        if self.row is not None and key == TINGTING_API_KEY_SETTING:
            return self.row
        return None

    def add(self, obj) -> None:  # noqa: ANN001
        self.added.append(obj)
        if getattr(obj, "key", None) == TINGTING_API_KEY_SETTING:
            self.row = obj

    async def flush(self) -> None:
        return None

    async def commit(self) -> None:
        self.commits += 1


def _stored_row(secret: str = _KEY) -> SimpleNamespace:
    return SimpleNamespace(
        key=TINGTING_API_KEY_SETTING,
        encrypted_value=IntegrationSettingsCipher().encrypt(secret),
        is_secret=True,
        updated_by=None,
    )


class _FakeHttp:
    """Records the outbound call and answers with a canned response."""

    def __init__(self, status: int = 200, text: str = '{"status":"success"}') -> None:
        self.status = status
        self.text = text
        self.calls: list[dict] = []

    async def request(self, method, url, **kwargs):  # noqa: ANN001
        self.calls.append({"method": method, "url": url, **kwargs})
        return httpx.Response(
            self.status, text=self.text, request=httpx.Request(method, url)
        )


@pytest.fixture(autouse=True)
def _no_redis(monkeypatch: pytest.MonkeyPatch) -> None:
    """Admission checks pass without Redis (the service fails open by design)."""

    async def _allow(_scope: str, _params: dict) -> bool:
        return True

    monkeypatch.setattr(mod, "consume_write_quota", _allow)


def _service(db=None, settings=None, *, http: _FakeHttp | None = None, use_http=True):
    service = TingtingApiService(db or _FakeSession(), settings=settings)
    if use_http and http is not None:
        async def _client(_name, timeout=None):  # noqa: ANN001, ARG001
            return http

        monkeypatch_target = mod.get_http_client
        service._test_client = _client  # type: ignore[attr-defined]
        return service, monkeypatch_target
    return service, None


# ── configuration ───────────────────────────────────────────────────────────


def test_resolve_base_url_defaults_to_the_tingting_origin() -> None:
    assert resolve_base_url(None) == TINGTING_API_BASE_DEFAULT
    assert resolve_base_url(SimpleNamespace()) == TINGTING_API_BASE_DEFAULT


def test_resolve_base_url_rejects_a_plain_http_override() -> None:
    """A bad operator override falls back to the reviewed origin, never http."""
    assert resolve_base_url(SimpleNamespace(tingting_api_base="http://evil.example")) == (
        TINGTING_API_BASE_DEFAULT
    )
    assert resolve_base_url(SimpleNamespace(tingting_api_base="https://dev.example/api/")) == (
        "https://dev.example/api"
    )


@pytest.mark.asyncio
async def test_runtime_is_none_without_a_key() -> None:
    assert await TingtingApiService(_FakeSession()).runtime() is None
    assert await TingtingApiService(_FakeSession()).configured() is False


@pytest.mark.asyncio
async def test_runtime_decrypts_the_stored_key() -> None:
    service = TingtingApiService(_FakeSession(_stored_row()))
    runtime = await service.runtime()
    assert runtime == TingtingApiRuntime(base_url=TINGTING_API_BASE_DEFAULT, api_key=_KEY)
    assert await service.configured() is True


@pytest.mark.asyncio
async def test_admin_view_reports_status_only() -> None:
    view = await TingtingApiService(_FakeSession(_stored_row())).admin_view()
    assert view["api_key"] == {"configured": True, "preview": f"{len(_KEY)} ký tự"}
    assert view["configured"] is True
    assert view["base_url"] == TINGTING_API_BASE_DEFAULT
    assert view["auth_header"] == "X-API-Key"
    assert _KEY not in str(view)


@pytest.mark.asyncio
async def test_replace_key_stores_and_clears() -> None:
    db = _FakeSession()
    service = TingtingApiService(db)

    stored = await service.replace_key(_KEY, actor_id=uuid.uuid4())
    assert stored["configured"] is True
    assert db.commits == 1
    assert _KEY not in str(db.row.encrypted_value)

    cleared = await service.replace_key("", actor_id=None)
    assert cleared["configured"] is False
    assert db.row.encrypted_value == ""


@pytest.mark.asyncio
async def test_replace_key_keeps_the_stored_value_when_absent() -> None:
    db = _FakeSession(_stored_row())
    before = db.row.encrypted_value

    view = await TingtingApiService(db).replace_key(None)

    assert db.row.encrypted_value == before
    assert view["configured"] is True


# ── the call path ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_invoke_posts_to_the_fixed_origin_with_the_api_key(monkeypatch) -> None:
    http = _FakeHttp()
    service = TingtingApiService(_FakeSession(_stored_row()))

    async def _client(_name, timeout=None):  # noqa: ANN001, ARG001
        return http

    monkeypatch.setattr(mod, "get_http_client", _client)
    runtime = await service.runtime()
    outcome = await service.invoke(
        runtime,
        method="POST",
        path="/api/v1/integration/password-reset/otp",
        params={"phone": "0987654321"},
    )

    assert outcome.state == "ok"
    assert outcome.text == '{"status":"success"}'
    call = http.calls[0]
    assert call["url"] == f"{TINGTING_API_BASE_DEFAULT}/api/v1/integration/password-reset/otp"
    assert call["headers"] == {"X-API-Key": _KEY}
    assert call["json"] == {"phone": "0987654321"}
    # The key is never sent as a query parameter (logs/URLs stay clean).
    assert call["params"] is None


@pytest.mark.asyncio
async def test_invoke_without_a_runtime_is_not_configured(monkeypatch) -> None:
    http = _FakeHttp()
    service = TingtingApiService(_FakeSession())

    async def _client(_name, timeout=None):  # noqa: ANN001, ARG001
        return http

    monkeypatch.setattr(mod, "get_http_client", _client)
    outcome = await service.invoke(
        await service.runtime(), method="POST", path="/x", params={}
    )

    assert outcome.state == "not_configured"
    assert http.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "path", "params", "detail"),
    [
        ("DELETE", "/api/v1/x", {}, "method_not_allowed"),
        ("POST", "https://evil.example/x", {}, "path_invalid"),
        ("POST", "/api/v1/../../admin", {}, "path_invalid"),
        ("POST", "/api/v1/x", {"nested": ["a"]}, "invalid_params"),
    ],
)
async def test_invoke_rejects_a_request_the_model_should_not_make(
    monkeypatch, method, path, params, detail
) -> None:
    http = _FakeHttp()
    service = TingtingApiService(_FakeSession(_stored_row()))

    async def _client(_name, timeout=None):  # noqa: ANN001, ARG001
        return http

    monkeypatch.setattr(mod, "get_http_client", _client)
    runtime = await service.runtime()
    outcome = await service.invoke(runtime, method=method, path=path, params=params)

    assert outcome.state == "invalid_request"
    assert outcome.detail == detail
    assert http.calls == []


@pytest.mark.asyncio
async def test_invoke_never_repeats_an_error_body(monkeypatch) -> None:
    http = _FakeHttp(status=401, text="key ttk_live_test_key rejected")
    service = TingtingApiService(_FakeSession(_stored_row()))

    async def _client(_name, timeout=None):  # noqa: ANN001, ARG001
        return http

    monkeypatch.setattr(mod, "get_http_client", _client)
    outcome = await service.invoke(
        await service.runtime(), method="POST", path="/api/v1/x", params={}
    )

    assert outcome.state == "error"
    assert outcome.status_code == 401
    assert outcome.text == ""


@pytest.mark.asyncio
async def test_invoke_returns_rate_limited_when_admission_refuses(monkeypatch) -> None:
    http = _FakeHttp()
    service = TingtingApiService(_FakeSession(_stored_row()))

    async def _client(_name, timeout=None):  # noqa: ANN001, ARG001
        return http

    async def _refuse(_scope: str, _params: dict) -> bool:
        return False

    monkeypatch.setattr(mod, "get_http_client", _client)
    monkeypatch.setattr(mod, "consume_write_quota", _refuse)
    outcome = await service.invoke(
        await service.runtime(), method="POST", path="/api/v1/x", params={}
    )

    assert outcome.state == "rate_limited"
    assert http.calls == []


# ── the embedded guide ──────────────────────────────────────────────────────


def test_guide_documents_every_reset_endpoint_in_order() -> None:
    guide = TINGTING_API_GUIDE
    positions = [
        guide.index("/api/v1/integration/employee/lookup"),
        guide.index("/api/v1/integration/password-reset/otp"),
        guide.index("/api/v1/integration/password-reset/verify"),
        guide.index("/api/v1/integration/password-reset/reset"),
    ]
    assert positions == sorted(positions)


def test_guide_requires_identity_verification_before_the_otp() -> None:
    """The three-field check is a hard precondition, not a suggestion."""
    guide = TINGTING_API_GUIDE
    assert "CCCD" in guide
    assert "XÁC MINH DANH TÍNH" in guide
    assert guide.index("XÁC MINH DANH TÍNH") < guide.index("3. GỬI OTP")


def test_guide_forbids_inventing_contact_channels() -> None:
    assert "không tự nghĩ ra hotline" in TINGTING_API_GUIDE
    assert TINGTING_API_BLOCK_HEADER in tingting_api_prompt_block()


# ── the tool rendering ──────────────────────────────────────────────────────


class _StubRetrieval:
    def __init__(self, outcome) -> None:  # noqa: ANN001
        self.outcome = outcome
        self.calls: list[dict] = []

    async def call_tingting_api(self, *, method, path, params):  # noqa: ANN001
        self.calls.append({"method": method, "path": path, "params": params})
        return self.outcome


def _outcome(state: str, **kwargs):
    from app.services.external_api_core import ExternalApiOutcome

    return ExternalApiOutcome(state, kwargs.get("label"), kwargs.get("path", "/x"), kwargs.get("status"), kwargs.get("text", ""), kwargs.get("detail", ""))


@pytest.mark.asyncio
async def test_tool_hands_back_the_real_body_for_ok() -> None:
    retrieval = _StubRetrieval(
        _outcome("ok", label="TingTing", text='{"data":{"otp_sent":true}}')
    )
    result = await call_tingting_api(
        retrieval, method="POST", path="/api/v1/integration/password-reset/otp", params={}
    )
    assert '{"data":{"otp_sent":true}}' in result
    assert "session_id" in result  # the confidentiality instruction rides along
    assert retrieval.calls[0]["path"] == "/api/v1/integration/password-reset/otp"


@pytest.mark.asyncio
async def test_tool_tells_the_model_to_stay_honest_on_errors() -> None:
    not_configured = await call_tingting_api(
        _StubRetrieval(_outcome("not_configured")), method="POST", path="/x", params={}
    )
    assert "chưa được cấu hình" in not_configured

    errored = await call_tingting_api(
        _StubRetrieval(_outcome("error", status=500, detail="status_500")),
        method="POST",
        path="/x",
        params={},
    )
    assert "HTTP 500" in errored
    assert "chưa thực hiện được" in errored


@pytest.mark.asyncio
async def test_tool_requires_a_path_before_calling_the_port() -> None:
    retrieval = _StubRetrieval(_outcome("ok", text="body"))
    result = await call_tingting_api(retrieval, method="POST", path="   ", params={})
    assert "Thiếu đường dẫn" in result
    assert retrieval.calls == []
