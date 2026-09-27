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
from app.graph.tools.tingting_api import (
    call_tingting_api,
    confirm_tingting_otp,
    reset_tingting_password,
    send_tingting_otp,
)
from app.services import tingting_api as mod
from app.services.external_api_core import QuotaDecision
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

    async def _allow(_scope: str, _params: dict, **_kwargs: object) -> QuotaDecision:
        return QuotaDecision(True)

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
    # The origin must not also carry the guide's ``/api/v1`` prefix, or every
    # call requests ``/api/v1/api/v1/...`` and the whole reset flow 404s.
    assert call["url"] == "https://tingting.vip/api/v1/integration/password-reset/otp"
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
@pytest.mark.parametrize(
    ("reason", "expected_state"),
    [("duplicate", "duplicate_request"), ("ceiling", "rate_limited")],
)
async def test_invoke_surfaces_the_bucket_that_refused(
    monkeypatch, reason, expected_state
) -> None:
    http = _FakeHttp()
    service = TingtingApiService(_FakeSession(_stored_row()))

    async def _client(_name, timeout=None):  # noqa: ANN001, ARG001
        return http

    async def _refuse(_scope: str, _params: dict, **_kwargs: object) -> QuotaDecision:
        return QuotaDecision(False, reason)

    monkeypatch.setattr(mod, "get_http_client", _client)
    monkeypatch.setattr(mod, "consume_write_quota", _refuse)
    outcome = await service.invoke(
        await service.runtime(),
        method="POST",
        path="/api/v1/integration/password-reset/otp",
        params={"phone": "0987654321"},
    )

    assert outcome.state == expected_state
    assert http.calls == []


@pytest.mark.asyncio
async def test_invoke_exempts_the_read_only_lookup_from_dedupe(monkeypatch) -> None:
    """A repeated lookup is a legitimate retry; only the ceiling still applies."""
    http = _FakeHttp()
    service = TingtingApiService(_FakeSession(_stored_row()))
    seen_dedupe: list[bool] = []

    async def _quota(_scope: str, _params: dict, *, dedupe: bool = True) -> QuotaDecision:
        seen_dedupe.append(dedupe)
        return QuotaDecision(True)

    async def _client(_name, timeout=None):  # noqa: ANN001, ARG001
        return http

    monkeypatch.setattr(mod, "get_http_client", _client)
    monkeypatch.setattr(mod, "consume_write_quota", _quota)
    outcome = await service.invoke(
        await service.runtime(),
        method="POST",
        path="/api/v1/integration/employee/lookup",
        params={"phone": "0987654321"},
    )

    assert outcome.state == "ok"
    assert seen_dedupe == [False]
    assert len(http.calls) == 1


@pytest.mark.asyncio
async def test_repeated_lookup_succeeds_while_repeated_otp_is_a_duplicate(monkeypatch) -> None:
    """Regression for the production report: two identical lookups must both reach
    the API, and the dedupe bucket still refuses a repeated OTP send."""
    from app.services import external_api_core

    class _Redis:
        def __init__(self) -> None:
            self.counts: dict[str, int] = {}

        async def incr(self, key: str) -> int:
            self.counts[key] = self.counts.get(key, 0) + 1
            return self.counts[key]

        async def expire(self, key: str, window: int) -> None:
            return None

    redis = _Redis()
    monkeypatch.setattr(external_api_core, "get_redis", lambda: redis)
    monkeypatch.setattr(mod, "consume_write_quota", external_api_core.consume_write_quota)

    http = _FakeHttp()
    service = TingtingApiService(_FakeSession(_stored_row()))

    async def _client(_name, timeout=None):  # noqa: ANN001, ARG001
        return http

    monkeypatch.setattr(mod, "get_http_client", _client)
    runtime = await service.runtime()

    async def _call(path: str):
        return await service.invoke(
            runtime, method="POST", path=path, params={"phone": "0987654321"}
        )

    first_lookup = await _call("/api/v1/integration/employee/lookup")
    second_lookup = await _call("/api/v1/integration/employee/lookup")
    first_otp = await _call("/api/v1/integration/password-reset/otp")
    second_otp = await _call("/api/v1/integration/password-reset/otp")

    assert [first_lookup.state, second_lookup.state] == ["ok", "ok"]
    assert first_otp.state == "ok"
    assert second_otp.state == "duplicate_request"
    assert len(http.calls) == 3


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
    """The identity check is a hard precondition and it is the tool's call."""
    guide = TINGTING_API_GUIDE
    assert "CCCD" in guide
    assert "XÁC MINH DANH TÍNH" in guide
    assert guide.index("1. TRA CỨU + XÁC MINH DANH TÍNH") < guide.index("2. GỬI OTP")
    assert guide.index("verify_tingting_identity") < guide.index("send_tingting_otp")
    assert "ĐÃ XÁC MINH" in guide
    # The session/token is server state: the model is told never to pass it.
    assert "KHÔNG truyền" in guide


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
async def test_lookup_tool_hands_back_the_real_body() -> None:
    retrieval = _StubRetrieval(
        _outcome("ok", label="TingTing", text='{"data":{"found":true}}')
    )
    result = await call_tingting_api(
        retrieval,
        method="POST",
        path="/api/v1/integration/employee/lookup",
        params={"phone": "0987654321"},
    )
    assert '{"data":{"found":true}}' in result
    assert retrieval.calls[0]["path"] == "/api/v1/integration/employee/lookup"


@pytest.mark.asyncio
async def test_lookup_tool_refuses_every_mutating_path() -> None:
    """The reset steps carry flow state; the raw tool must not run them."""
    retrieval = _StubRetrieval(_outcome("ok", text="body"))
    for path in (
        "/api/v1/integration/password-reset/otp",
        "/api/v1/integration/password-reset/verify",
        "/api/v1/integration/password-reset/reset",
    ):
        result = await call_tingting_api(
            retrieval, method="POST", path=path, params={"phone": "0987654321"}
        )
        assert "send_tingting_otp" in result
    assert retrieval.calls == []


@pytest.mark.asyncio
async def test_lookup_tool_tells_the_model_to_stay_honest_on_errors() -> None:
    not_configured = await call_tingting_api(
        _StubRetrieval(_outcome("not_configured")),
        method="POST",
        path="/api/v1/integration/employee/lookup",
        params={},
    )
    assert "chưa được cấu hình" in not_configured

    errored = await call_tingting_api(
        _StubRetrieval(_outcome("error", status=500, detail="status_500")),
        method="POST",
        path="/api/v1/integration/employee/lookup",
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

# ── the reset flow: state lives server-side ─────────────────────────────────


class _FlowRetrieval:
    """Retrieval stub with the flow-state seam and a scripted API answer."""

    def __init__(self, outcome=None, *, state=None, outcomes=None) -> None:
        self.outcome = outcome
        self.state = dict(state or {})
        self.outcomes = list(outcomes or [])
        self.calls: list[dict] = []
        self.saved: list[dict] = []
        self.cleared = 0

    async def call_tingting_api(self, *, method, path, params):  # noqa: ANN001
        self.calls.append({"method": method, "path": path, "params": params})
        if self.outcomes:
            return self.outcomes.pop(0)
        return self.outcome

    async def tingting_flow_state(self, _phone: str) -> dict:
        return dict(self.state)

    async def save_tingting_flow_state(self, _phone: str, state: dict) -> dict:
        self.saved.append(dict(state))
        self.state.update(state)
        return dict(self.state)

    async def clear_tingting_flow_state(self, _phone: str) -> None:
        self.cleared += 1
        self.state = {}


def _otp_ok(session_id: str = "sess-1"):
    return _outcome(
        "ok", label="TingTing", text=f'{{"data":{{"otp_sent":true,"session_id":"{session_id}"}}}}'
    )


def _verify_ok(reset_token: str = "tok-1"):
    return _outcome("ok", label="TingTing", text=f'{{"data":{{"reset_token":"{reset_token}"}}}}')


def _reset_ok():
    return _outcome(
        "ok",
        label="TingTing",
        text='{"data":{"username":"nv.dung","new_password":"Abc12345","employee_name":"Nguyễn Việt Dũng"}}',
    )


@pytest.mark.asyncio
async def test_otp_is_refused_until_the_phone_is_verified() -> None:
    retrieval = _FlowRetrieval(_otp_ok())
    result = await send_tingting_otp(retrieval, phone="0987654321")
    assert "chưa được xác minh" in result
    assert retrieval.calls == []


@pytest.mark.asyncio
async def test_otp_send_stores_the_session_and_never_returns_it() -> None:
    retrieval = _FlowRetrieval(_otp_ok("sess-42"), state={"verified": True})
    result = await send_tingting_otp(retrieval, phone="0987654321")
    assert retrieval.saved[-1] == {"session_id": "sess-42"}
    assert "sess-42" not in result
    assert "confirm_tingting_otp" in result


@pytest.mark.asyncio
async def test_confirm_uses_the_stored_session_not_the_model() -> None:
    """Regression: the code turn must reuse the session the send turn stored."""
    retrieval = _FlowRetrieval(_verify_ok("tok-9"), state={"session_id": "sess-42"})
    result = await confirm_tingting_otp(retrieval, phone="0987654321", code="123456")
    assert retrieval.calls == [
        {
            "method": "POST",
            "path": "/api/v1/integration/password-reset/verify",
            "params": {"session_id": "sess-42", "code": "123456"},
        }
    ]
    assert retrieval.saved[-1] == {"reset_token": "tok-9", "otp_verified": True}
    assert "reset_tingting_password" in result


@pytest.mark.asyncio
async def test_confirm_without_a_session_asks_for_a_fresh_otp() -> None:
    retrieval = _FlowRetrieval(_verify_ok())
    result = await confirm_tingting_otp(retrieval, phone="0987654321", code="123456")
    assert "Chưa có phiên OTP" in result
    assert retrieval.calls == []


@pytest.mark.asyncio
async def test_confirm_rejects_a_code_that_is_not_six_digits() -> None:
    retrieval = _FlowRetrieval(_verify_ok(), state={"session_id": "sess-42"})
    result = await confirm_tingting_otp(retrieval, phone="0987654321", code="12ab")
    assert "6 chữ số" in result
    assert retrieval.calls == []


@pytest.mark.asyncio
async def test_confirm_keeps_the_session_when_the_code_is_wrong() -> None:
    """A 401 means wrong/expired code: retry the same session, don't ask for the phone."""
    retrieval = _FlowRetrieval(
        _outcome("error", status=401, detail="status_401"), state={"session_id": "sess-42"}
    )
    result = await confirm_tingting_otp(retrieval, phone="0987654321", code="000000")
    assert "không đúng hoặc đã hết hạn" in result
    assert "send_tingting_otp" in result
    assert retrieval.saved == []


@pytest.mark.asyncio
async def test_reset_uses_the_stored_token_and_clears_the_flow() -> None:
    retrieval = _FlowRetrieval(_reset_ok(), state={"reset_token": "tok-9"})
    result = await reset_tingting_password(retrieval, phone="0987654321")
    assert retrieval.calls[0]["params"] == {"reset_token": "tok-9"}
    assert retrieval.cleared == 1
    assert "nv.dung" in result and "Abc12345" in result


@pytest.mark.asyncio
async def test_reset_without_a_verified_code_restarts_the_flow() -> None:
    retrieval = _FlowRetrieval(_reset_ok())
    result = await reset_tingting_password(retrieval, phone="0987654321")
    assert "Chưa xác thực được mã OTP" in result
    assert retrieval.calls == []


@pytest.mark.asyncio
async def test_otp_failure_reasons_map_to_the_next_step() -> None:
    delivery = _FlowRetrieval(
        _outcome(
            "ok",
            text='{"data":{"otp_sent":false,"failure_reason":"delivery_failed","delivery_error_code":-118}}',
        ),
        state={"verified": True},
    )
    result = await send_tingting_otp(delivery, phone="0987654321")
    assert "chưa liên kết Zalo" in result
    assert delivery.saved == []


@pytest.mark.asyncio
async def test_a_resend_within_the_dedupe_window_does_not_claim_a_new_session() -> None:
    retrieval = _FlowRetrieval(_outcome("duplicate_request"), state={"verified": True})
    result = await send_tingting_otp(retrieval, phone="0987654321")
    assert "vừa được gửi" in result
    assert retrieval.saved == []


@pytest.mark.asyncio
async def test_a_repeated_code_check_explains_the_dedupe() -> None:
    retrieval = _FlowRetrieval(_outcome("duplicate_request"), state={"session_id": "sess-1"})
    result = await confirm_tingting_otp(retrieval, phone="0987654321", code="123456")
    assert "vừa được kiểm tra" in result
    assert "send_tingting_otp" in result
