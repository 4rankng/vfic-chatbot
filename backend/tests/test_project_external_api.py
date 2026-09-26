"""Unit tests for the per-project external API integration.

Hermetic: pure validators, a fake DB session, a fake Redis counter and a
registry-injected fake HTTP client. Nothing here opens a socket — the real-HTTP
proof lives in a throwaway smoke script.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import httpx
import pytest

from app.core.http import register_test_client
from app.schemas.projects import ProjectExternalApiUpdate
from app.services.integration_settings.cipher import IntegrationSettingsCipher
from app.services.project import external_api as mod
from app.services.project.external_api import (
    EXTERNAL_API_CLIENT_NAME,
    EXTERNAL_API_MAX_RESPONSE_CHARS,
    ExternalApiConfig,
    ExternalApiOutcome,
    ProjectExternalApiService,
    api_key_status,
    normalize_base_url,
    normalize_endpoint_path,
    normalize_method,
    sanitize_params,
)
from app.shared.domain.errors import BadRequestError

GUIDE = (
    "# Hướng dẫn tích hợp API\n\n"
    "POST /api/v1/integration/password-reset/otp — gửi OTP qua Zalo.\n"
    "POST /api/v1/integration/password-reset/verify — xác thực mã.\n"
)
OTP_PATH = "/api/v1/integration/password-reset/otp"


class _FakeSession:
    """Minimal AsyncSession double: one project row, an audit sink, a commit flag."""

    def __init__(self, project) -> None:
        self.project = project
        self.added: list[object] = []
        self.commits = 0

    async def get(self, _model, _pk):
        return self.project

    async def commit(self) -> None:
        self.commits += 1

    async def flush(self) -> None:
        return None

    def add(self, obj) -> None:
        self.added.append(obj)


class _CountingRedis:
    """Fixed-window counter matching the INCR + EXPIRE-first-increment contract."""

    def __init__(self) -> None:
        self.counts: dict[str, int] = {}
        self.expires: dict[str, int] = {}
        self.raises = False

    async def incr(self, key: str) -> int:
        if self.raises:
            raise ConnectionError("redis down")
        self.counts[key] = self.counts.get(key, 0) + 1
        return self.counts[key]

    async def expire(self, key: str, window: int) -> bool:
        self.expires[key] = window
        return True


class _FakeResponse:
    def __init__(self, status_code: int, text: str = "") -> None:
        self.status_code = status_code
        self.text = text


class _FakeHttp:
    def __init__(self, *, response: _FakeResponse | None = None, exc: Exception | None = None):
        self.response = response
        self.exc = exc
        self.calls: list[tuple[str, str, dict]] = []

    async def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        if self.exc is not None:
            raise self.exc
        return self.response


@pytest.fixture(autouse=True)
def _fake_redis(monkeypatch: pytest.MonkeyPatch) -> _CountingRedis:
    """Replace the service module's own ``get_redis`` binding with a counter.

    The shared conftest pins ``app.core.redis.get_redis``, but this module
    imported the name directly, so the binding that matters is its own.
    """
    redis = _CountingRedis()
    monkeypatch.setattr(mod, "get_redis", lambda: redis)
    return redis


def _project(project_id: uuid.UUID, config: dict | None):
    return SimpleNamespace(id=project_id, external_api=config)


def _config(**overrides) -> dict:
    payload = {
        "enabled": True,
        "base_url": "http://127.0.0.1:8799",
        "auth_header": "X-API-Key",
        "auth_scheme": "",
        "api_key_encrypted": "",
        "guide": GUIDE,
    }
    payload.update(overrides)
    return payload


def _sealed(project_id: uuid.UUID, secret: str = "ttk_test") -> str:
    return IntegrationSettingsCipher().encrypt_with_context(
        secret, f"project-external-api:{project_id}"
    )


# --------------------------------------------------------------------------- #
# Pure validators
# --------------------------------------------------------------------------- #


def test_normalize_base_url_rejects_plain_http_off_loopback() -> None:
    with pytest.raises(ValueError) as exc:
        normalize_base_url("http://api.example.com")
    assert str(exc.value) == "base_url_scheme"
    assert normalize_base_url("http://127.0.0.1:8799") == "http://127.0.0.1:8799"
    assert normalize_base_url("https://api.example.com/") == "https://api.example.com"


@pytest.mark.parametrize(
    ("value", "code"),
    [
        ("", "base_url_required"),
        ("api.example.com", "base_url_scheme"),
        ("https://user:pass@api.example.com", "base_url_credentials"),
        ("https://api.example.com?a=1", "base_url_invalid"),
        ("https://api.example.com#frag", "base_url_invalid"),
    ],
)
def test_normalize_base_url_machine_codes(value: str, code: str) -> None:
    with pytest.raises(ValueError) as exc:
        normalize_base_url(value)
    assert str(exc.value) == code


@pytest.mark.parametrize(
    "value",
    [
        "v1/otp",
        "",
        "/a//b",
        "/a/../b",
        "/a?b=1",
        "//x",
        # The model supplies the path, so an absolute URL must never pass: it
        # would move the request off the admin's configured origin.
        "https://evil.example.com/v1/otp",
        "http://evil.example.com/",
    ],
)
def test_normalize_endpoint_path_rejects(value: str) -> None:
    with pytest.raises(ValueError) as exc:
        normalize_endpoint_path(value)
    assert str(exc.value) == "path_invalid"
    assert normalize_endpoint_path(OTP_PATH) == OTP_PATH


def test_normalize_method_folds_case_and_rejects_others() -> None:
    assert normalize_method("post") == "POST"
    assert normalize_method(" GET ") == "GET"
    with pytest.raises(ValueError) as exc:
        normalize_method("DELETE")
    assert str(exc.value) == "method_not_allowed"


def test_api_key_status_is_status_only() -> None:
    assert api_key_status("") == {"configured": False, "preview": None}
    assert api_key_status("ttk_abcd") == {"configured": True, "preview": "8 ký tự"}


@pytest.mark.parametrize(
    ("params", "expected"),
    [
        (None, {}),
        ({"phone": "0987654321", "code": None}, {"phone": "0987654321"}),
        ({"code": 123456}, {"code": "123456"}),
    ],
)
def test_sanitize_params_accepts_scalars(params, expected) -> None:
    assert sanitize_params(params) == expected


@pytest.mark.parametrize(
    "params",
    [
        {"a": {"nested": 1}},
        {"a": ["x"]},
        {"a": "x" * 201},
        {f"k{index}": "v" for index in range(11)},
        "not-a-dict",
    ],
)
def test_sanitize_params_rejects(params) -> None:
    assert sanitize_params(params) is None


# --------------------------------------------------------------------------- #
# Config invariants
# --------------------------------------------------------------------------- #


def test_enabled_requires_a_base_url_and_a_guide() -> None:
    with pytest.raises(ValueError) as exc:
        ExternalApiConfig(enabled=True, guide=GUIDE)
    assert mod.config_error_code(exc.value) == "base_url_required"

    with pytest.raises(ValueError) as exc:
        ExternalApiConfig(enabled=True, base_url="https://api.example.com", guide="  ")
    assert mod.config_error_code(exc.value) == "guide_required"


def test_guide_bounds() -> None:
    with pytest.raises(ValueError) as exc:
        ExternalApiConfig(guide="x" * (mod.EXTERNAL_API_MAX_GUIDE_CHARS + 1))
    assert mod.config_error_code(exc.value) == "guide_too_long"


def test_disabled_config_may_be_empty() -> None:
    config = ExternalApiConfig()
    assert (config.enabled, config.base_url, config.guide) == (False, "", "")


def test_parse_config_collapses_an_unusable_row() -> None:
    assert mod.parse_config(None).enabled is False
    assert mod.parse_config({"enabled": True, "base_url": "nope", "guide": GUIDE}).enabled is False
    assert mod.parse_config({"unknown_key": 1}).enabled is False


# --------------------------------------------------------------------------- #
# Service: sealing, masking, scope binding
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_replace_seals_key_and_masks_it_on_read() -> None:
    project_id = uuid.uuid4()
    db = _FakeSession(_project(project_id, None))
    service = ProjectExternalApiService(db)

    view = await service.replace(
        project_id,
        ProjectExternalApiUpdate(
            enabled=True,
            base_url="https://api.example.com/",
            auth_header="X-API-Key",
            auth_scheme="",
            guide=GUIDE,
            api_key="ttk_secret",
        ),
        SimpleNamespace(id=uuid.uuid4()),
    )

    stored = db.project.external_api
    assert stored["api_key_encrypted"].startswith("v2:")
    assert "ttk_secret" not in str(stored)
    assert stored["base_url"] == "https://api.example.com"
    assert db.commits == 1
    assert len(db.added) == 1
    assert view["api_key"] == {"configured": True, "preview": "10 ký tự"}
    assert view["guide"] == GUIDE


@pytest.mark.asyncio
async def test_blank_api_key_clears_the_stored_secret() -> None:
    project_id = uuid.uuid4()
    db = _FakeSession(_project(project_id, _config(api_key_encrypted=_sealed(project_id))))
    service = ProjectExternalApiService(db)

    view = await service.replace(
        project_id,
        ProjectExternalApiUpdate(
            enabled=True,
            base_url="http://127.0.0.1:8799",
            guide=GUIDE,
            api_key="",
        ),
        SimpleNamespace(id=uuid.uuid4()),
    )

    assert db.project.external_api["api_key_encrypted"] == ""
    assert view["api_key"] == {"configured": False, "preview": None}


@pytest.mark.asyncio
async def test_omitted_api_key_keeps_the_stored_secret() -> None:
    project_id = uuid.uuid4()
    sealed = _sealed(project_id, "ttk_old")
    db = _FakeSession(_project(project_id, _config(api_key_encrypted=sealed)))
    service = ProjectExternalApiService(db)

    view = await service.replace(
        project_id,
        ProjectExternalApiUpdate(
            enabled=True,
            base_url="http://127.0.0.1:8799",
            guide=GUIDE,
        ),
        SimpleNamespace(id=uuid.uuid4()),
    )

    assert db.project.external_api["api_key_encrypted"] == sealed
    assert view["api_key"] == {"configured": True, "preview": "7 ký tự"}


@pytest.mark.asyncio
async def test_key_sealed_for_another_project_does_not_decrypt() -> None:
    project_a, project_b = uuid.uuid4(), uuid.uuid4()
    db = _FakeSession(_project(project_b, _config(api_key_encrypted=_sealed(project_a))))

    assert await ProjectExternalApiService(db).runtime(project_b) is None
    # The admin view degrades to "chưa cấu hình" instead of leaking a failure.
    assert (await ProjectExternalApiService(db).admin_view(project_b))["api_key"] == {
        "configured": False,
        "preview": None,
    }


@pytest.mark.asyncio
async def test_runtime_returns_none_when_disabled_or_missing() -> None:
    project_id = uuid.uuid4()
    disabled = _FakeSession(_project(project_id, _config(enabled=False)))
    assert await ProjectExternalApiService(disabled).runtime(project_id) is None

    missing = _FakeSession(None)
    assert await ProjectExternalApiService(missing).runtime(uuid.uuid4()) is None


@pytest.mark.asyncio
async def test_runtime_returns_config_and_plaintext_key() -> None:
    project_id = uuid.uuid4()
    db = _FakeSession(_project(project_id, _config(api_key_encrypted=_sealed(project_id))))

    runtime = await ProjectExternalApiService(db).runtime(project_id)

    assert runtime is not None
    config, api_key = runtime
    assert config.enabled is True
    assert api_key == "ttk_test"


@pytest.mark.asyncio
async def test_replace_rejects_invalid_config_with_machine_code() -> None:
    project_id = uuid.uuid4()
    db = _FakeSession(_project(project_id, None))

    with pytest.raises(BadRequestError) as exc:
        await ProjectExternalApiService(db).replace(
            project_id,
            ProjectExternalApiUpdate(
                enabled=True,
                base_url="http://api.example.com",
                guide=GUIDE,
            ),
            SimpleNamespace(id=uuid.uuid4()),
        )
    assert exc.value.detail == "base_url_scheme"


# --------------------------------------------------------------------------- #
# Service: egress
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_invoke_posts_with_auth_header_and_json_body() -> None:
    fake = _FakeHttp(response=_FakeResponse(200, '{"status":"success","data":{"otp_sent":true}}'))
    register_test_client(EXTERNAL_API_CLIENT_NAME, fake)
    service = ProjectExternalApiService(_FakeSession(None))
    config = ExternalApiConfig(**_config())

    outcome = await service.invoke(
        uuid.uuid4(),
        config,
        "ttk_test",
        method="post",
        path=OTP_PATH,
        params={"phone": "0987654321"},
    )

    method, url, kwargs = fake.calls[0]
    assert method == "POST"
    assert url == f"http://127.0.0.1:8799{OTP_PATH}"
    assert kwargs["headers"] == {"X-API-Key": "ttk_test"}
    assert kwargs["json"] == {"phone": "0987654321"}
    assert kwargs["params"] is None
    assert outcome.state == "ok"
    assert '"otp_sent":true' in outcome.text


@pytest.mark.asyncio
async def test_invoke_sends_query_params_for_get() -> None:
    fake = _FakeHttp(response=_FakeResponse(200, "{}"))
    register_test_client(EXTERNAL_API_CLIENT_NAME, fake)
    service = ProjectExternalApiService(_FakeSession(None))
    config = ExternalApiConfig(**_config())

    outcome = await service.invoke(
        uuid.uuid4(),
        config,
        "ttk_test",
        method="GET",
        path="/api/v1/integration/employee/lookup",
        params={"phone": "0987654321"},
    )

    assert outcome.state == "ok"
    assert fake.calls[0][2]["params"] == {"phone": "0987654321"}
    assert fake.calls[0][2]["json"] is None


@pytest.mark.asyncio
async def test_invoke_truncates_a_long_body() -> None:
    fake = _FakeHttp(response=_FakeResponse(200, "x" * (EXTERNAL_API_MAX_RESPONSE_CHARS + 500)))
    register_test_client(EXTERNAL_API_CLIENT_NAME, fake)
    service = ProjectExternalApiService(_FakeSession(None))
    config = ExternalApiConfig(**_config())

    outcome = await service.invoke(
        uuid.uuid4(), config, "k", method="POST", path=OTP_PATH, params={}
    )

    assert outcome.state == "ok"
    assert len(outcome.text) == EXTERNAL_API_MAX_RESPONSE_CHARS


@pytest.mark.asyncio
async def test_invoke_error_status_carries_no_body() -> None:
    fake = _FakeHttp(response=_FakeResponse(500, "internal detail: stack trace"))
    register_test_client(EXTERNAL_API_CLIENT_NAME, fake)
    service = ProjectExternalApiService(_FakeSession(None))
    config = ExternalApiConfig(**_config())

    outcome = await service.invoke(
        uuid.uuid4(), config, "k", method="POST", path=OTP_PATH, params={}
    )

    assert outcome.state == "error"
    assert outcome.status_code == 500
    assert outcome.text == ""
    assert outcome.detail == "status_500"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("exc", "detail"),
    [(httpx.ReadTimeout("slow"), "timeout"), (httpx.ConnectError("refused"), "network_error")],
)
async def test_invoke_maps_transport_failures(exc: Exception, detail: str) -> None:
    fake = _FakeHttp(exc=exc)
    register_test_client(EXTERNAL_API_CLIENT_NAME, fake)
    service = ProjectExternalApiService(_FakeSession(None))
    config = ExternalApiConfig(**_config())

    outcome = await service.invoke(
        uuid.uuid4(), config, "k", method="POST", path=OTP_PATH, params={}
    )

    assert (outcome.state, outcome.detail) == ("error", detail)


@pytest.mark.asyncio
async def test_invoke_refuses_a_write_method() -> None:
    fake = _FakeHttp(response=_FakeResponse(200, "{}"))
    register_test_client(EXTERNAL_API_CLIENT_NAME, fake)
    service = ProjectExternalApiService(_FakeSession(None))
    config = ExternalApiConfig(**_config())

    outcome = await service.invoke(
        uuid.uuid4(), config, "k", method="DELETE", path=OTP_PATH, params={}
    )

    assert (outcome.state, outcome.detail) == ("invalid_request", "method_not_allowed")
    assert fake.calls == []


@pytest.mark.asyncio
async def test_invoke_refuses_a_path_off_the_configured_origin() -> None:
    fake = _FakeHttp(response=_FakeResponse(200, "{}"))
    register_test_client(EXTERNAL_API_CLIENT_NAME, fake)
    service = ProjectExternalApiService(_FakeSession(None))
    config = ExternalApiConfig(**_config())

    outcome = await service.invoke(
        uuid.uuid4(),
        config,
        "k",
        method="POST",
        path="https://evil.example.com/steal",
        params={},
    )

    assert (outcome.state, outcome.detail) == ("invalid_request", "path_invalid")
    assert fake.calls == []


@pytest.mark.asyncio
async def test_invoke_refuses_container_params() -> None:
    fake = _FakeHttp(response=_FakeResponse(200, "{}"))
    register_test_client(EXTERNAL_API_CLIENT_NAME, fake)
    service = ProjectExternalApiService(_FakeSession(None))
    config = ExternalApiConfig(**_config())

    outcome = await service.invoke(
        uuid.uuid4(), config, "k", method="POST", path=OTP_PATH, params={"phone": {"x": 1}}
    )

    assert (outcome.state, outcome.detail) == ("invalid_request", "invalid_params")
    assert fake.calls == []


@pytest.mark.asyncio
async def test_invoke_reports_not_configured_when_disabled() -> None:
    service = ProjectExternalApiService(_FakeSession(None))
    outcome = await service.invoke(
        uuid.uuid4(), ExternalApiConfig(), "k", method="POST", path=OTP_PATH, params={}
    )
    assert outcome.state == "not_configured"


@pytest.mark.asyncio
async def test_second_identical_post_is_rate_limited() -> None:
    fake = _FakeHttp(response=_FakeResponse(200, "{}"))
    register_test_client(EXTERNAL_API_CLIENT_NAME, fake)
    service = ProjectExternalApiService(_FakeSession(None))
    config = ExternalApiConfig(**_config())
    project_id = uuid.uuid4()

    first = await service.invoke(
        project_id, config, "k", method="POST", path=OTP_PATH, params={"phone": "1"}
    )
    second = await service.invoke(
        project_id, config, "k", method="POST", path=OTP_PATH, params={"phone": "1"}
    )

    assert first.state == "ok"
    assert second.state == "rate_limited"
    assert len(fake.calls) == 1


@pytest.mark.asyncio
async def test_get_is_never_throttled(_fake_redis: _CountingRedis) -> None:
    fake = _FakeHttp(response=_FakeResponse(200, "{}"))
    register_test_client(EXTERNAL_API_CLIENT_NAME, fake)
    service = ProjectExternalApiService(_FakeSession(None))
    config = ExternalApiConfig(**_config())
    project_id = uuid.uuid4()

    for _ in range(3):
        outcome = await service.invoke(
            project_id,
            config,
            "k",
            method="GET",
            path="/api/v1/integration/employee/lookup",
            params={"phone": "0987654321"},
        )
        assert outcome.state == "ok"

    assert len(fake.calls) == 3
    assert _fake_redis.counts == {}


@pytest.mark.asyncio
async def test_throttle_fails_open_when_redis_is_unavailable(
    _fake_redis: _CountingRedis,
) -> None:
    _fake_redis.raises = True
    fake = _FakeHttp(response=_FakeResponse(200, "{}"))
    register_test_client(EXTERNAL_API_CLIENT_NAME, fake)
    service = ProjectExternalApiService(_FakeSession(None))
    config = ExternalApiConfig(**_config())
    project_id = uuid.uuid4()

    for _ in range(3):
        outcome = await service.invoke(
            project_id, config, "k", method="POST", path=OTP_PATH, params={}
        )
        assert outcome.state == "ok"


@pytest.mark.asyncio
async def test_throttle_keys_never_contain_plaintext_params(
    _fake_redis: _CountingRedis,
) -> None:
    fake = _FakeHttp(response=_FakeResponse(200, "{}"))
    register_test_client(EXTERNAL_API_CLIENT_NAME, fake)
    service = ProjectExternalApiService(_FakeSession(None))
    config = ExternalApiConfig(**_config())

    await service.invoke(
        uuid.uuid4(),
        config,
        "ttk_secret",
        method="POST",
        path=OTP_PATH,
        params={"phone": "0987654321"},
    )

    keys = list(_fake_redis.counts)
    assert keys
    assert all("0987654321" not in key and "ttk_secret" not in key for key in keys)


def test_outcome_is_a_named_tuple_with_defaults() -> None:
    outcome = ExternalApiOutcome("ok", "LG Display", OTP_PATH, 200, "body")
    assert outcome.detail == ""
