"""Deployment-wide TingTing integration: key storage, egress, prompt, tool.

Pure-unit coverage (no DB, no network): the integration setting row is a fake
session, the HTTP client is a stub, and Redis admission is monkeypatched. The
point of these tests is the *shape* the agent depends on — one key, one fixed
origin, one call path, an embedded guide, and truthful outcomes.
"""

from __future__ import annotations

import re
import uuid
from types import SimpleNamespace

import httpx
import pytest

from app.graph.tingting_guide import (
    TINGTING_API_BLOCK_HEADER,
    TINGTING_CONFIRM_REPLY,
    TINGTING_FIELDS_ASK,
    TINGTING_INTENT_REDIRECT_REPLY,
    TINGTING_RESOLVED_CLOSER_REPLY,
    TINGTING_SELF_CHECKIN_IMAGE_URL,
    TINGTING_SELF_CHECKIN_REPLY,
    TINGTING_WAGE_WAIT_REPLY,
    tingting_api_guide,
    tingting_api_prompt_block,
    tingting_hotline_reply,
    tingting_support_persona,
    tingting_support_system_prompt,
)
from app.graph.tools.tingting_api import (
    confirm_tingting_otp,
    generate_simple_password,
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

# The persona, the guide, and the escalation replies are built around the
# stored hotline setting; tests build them with the owner-approved number (the
# value Alembic 0058 seeds) under the names the assertions already use.
_TINGTING_HOTLINE = "+84 914 827 988"
TINGTING_SUPPORT_PERSONA = tingting_support_persona(_TINGTING_HOTLINE)
TINGTING_API_GUIDE = tingting_api_guide(_TINGTING_HOTLINE)
TINGTING_HOTLINE_REPLY = tingting_hotline_reply(_TINGTING_HOTLINE)

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
    assert guide.index("1. THU THẬP + XÁC MINH DANH TÍNH") < guide.index("2. GỬI OTP")
    assert guide.index("verify_tingting_identity") < guide.index("send_tingting_otp")
    assert "ĐÃ XÁC MINH" in guide
    # The session/token is server state: the model is told never to pass it.
    assert "KHÔNG truyền" in guide


def test_guide_forbids_inventing_contact_channels() -> None:
    assert "không tự nghĩ ra hotline" in TINGTING_API_GUIDE
    assert TINGTING_API_BLOCK_HEADER in tingting_api_prompt_block(_TINGTING_HOTLINE)


def test_guide_asks_for_all_three_fields_before_the_lookup() -> None:
    """The three identity fields are one ask, and it precedes the tool call.

    The flow used to leave the model free to collect them one at a time; the ask
    is now a fixed sentence the guide quotes verbatim, so the employee answers
    once and the identity tool gets all three on the first call.
    """
    guide = TINGTING_API_GUIDE
    assert TINGTING_FIELDS_ASK in guide
    assert "CẢ BA" in guide
    assert guide.index(TINGTING_FIELDS_ASK) < guide.index("verify_tingting_identity")


def test_guide_asks_the_fixed_confirm_question_and_never_lists_problems() -> None:
    """An unclear intent gets the one confirm question, not a problem menu.

    Production returned a menu that included "cần tra cứu thông tin nhân viên" —
    a capability with no tool behind it — so the menu wording must not survive
    anywhere in the prompt.
    """
    assert TINGTING_CONFIRM_REPLY in TINGTING_API_GUIDE
    assert TINGTING_CONFIRM_REPLY in TINGTING_SUPPORT_PERSONA
    assert "tra cứu thông tin nhân viên" not in TINGTING_API_GUIDE
    assert "tra cứu thông tin nhân viên" not in TINGTING_SUPPORT_PERSONA


def test_small_talk_gets_a_redirect_budget_before_any_handoff() -> None:
    """BOT-01: small talk ("trời đẹp đấy") must be redirected, not escalated.

    Production (2026-09-28, TingTing support OA): a weather reply after the
    confirm question was answered with the then-consultant handoff line on the
    SAME turn. The prompt must (a) classify small talk as unclear intent, not an
    out-of-scope topic, (b) cap the redirect at 3 asks before the hotline reply,
    and (c) keep the immediate hotline reply only for explicit out-of-scope
    requests. The hotline reply itself is the escalation (operator rule
    2026-09-29 — no consultant promise exists anymore), so the wording guards
    the same boundaries against it.
    """
    for prompt in (TINGTING_SUPPORT_PERSONA, TINGTING_API_GUIDE):
        # small talk is explicitly excluded from the immediate escalation
        assert "KHÔNG được trả lời dòng hotline" in prompt
        assert "tối đa 3 LẦN" in prompt
        # the redirect ask is quoted verbatim in both sections
        assert TINGTING_INTENT_REDIRECT_REPLY in prompt
        # the confirm question stays quoted verbatim (existing contract)
        assert TINGTING_CONFIRM_REPLY in prompt
        # operator rule 2026-09-29: the consultant promise is gone for good —
        # the hotline reply is the only escalation and never implies a human
        # waiting in this chat.
        assert "chuyên viên tư vấn liên hệ" not in prompt
    assert TINGTING_HOTLINE_REPLY in TINGTING_SUPPORT_PERSONA
    # the escalation reply is reserved for the can't-help cases: a redirect
    # reply carrying it verbatim would end the bot conversation on the first
    # small-talk turn, so it must never appear in the redirect wording.
    assert TINGTING_HOTLINE_REPLY not in TINGTING_INTENT_REDIRECT_REPLY


def test_resolved_conversation_gets_the_closer_not_another_pitch() -> None:
    """After resolution, closers and gibberish get the warm close, never a re-pitch.

    Production (2026-09-28, TingTing support OA): the employee confirmed the
    login worked, then sent a casual closer twice — and both times got the
    unclear-intent redirect pitching the reset flow. Both prompt sections must
    quote the fixed closer verbatim, forbid re-pitching in the resolved state,
    and let the once-asked confirm question die after a non-engaging reply
    instead of being asked a second time.
    """
    for prompt in (TINGTING_SUPPORT_PERSONA, TINGTING_API_GUIDE):
        assert TINGTING_RESOLVED_CLOSER_REPLY in prompt
        assert "ĐÃ GIẢI QUYẾT XONG" in prompt
        assert "KHÔNG hỏi lại lần thứ hai" in prompt
        assert "TỰ nhắc lại rắc rối đăng nhập" in prompt
    # the escalation reply is reserved for the can't-help cases: a closer
    # carrying it verbatim would read as an escalation on a polite goodbye.
    assert TINGTING_HOTLINE_REPLY not in TINGTING_RESOLVED_CLOSER_REPLY


def test_payday_question_gets_the_wage_wait_reply_not_the_handoff() -> None:
    """Operator rule (2026-10-05/06): a payday-status question gets the waiting line.

    Payday questions used to fall into the out-of-scope catch-all and be
    answered with the hotline escalation. The operator approved one fixed
    waiting-for-VFIC-data reply instead: both prompt sections must quote it
    verbatim. The rule classifies the intent (payday status), not example
    phrasings — Jev's ``wage_wait`` judgment is the primary trigger and this
    is its degraded fallback; "ứng lương được chưa" and "có lương chưa" are
    one intent and must get one answer. The rule sits before the catch-all so
    the question is answered in-chat, not handed off.
    """
    for prompt in (TINGTING_SUPPORT_PERSONA, TINGTING_API_GUIDE):
        assert TINGTING_WAGE_WAIT_REPLY in prompt
        assert "hỏi tình trạng nhận tiền" in prompt
        assert "ứng lương đã về hay chưa" in prompt
        assert "phán theo ý định, không theo từ khóa" in prompt
        assert "KHÔNG trả lời dòng hotline" in prompt
        assert "không hẹn ai sẽ nhắn lại" in prompt
    # the escalation reply is reserved for the can't-help cases: a fixed payday
    # reply carrying it verbatim would read as an escalation on a real answer.
    assert TINGTING_HOTLINE_REPLY not in TINGTING_WAGE_WAIT_REPLY
    # precedence: in the persona the payday rule sits before the out-of-scope
    # catch-all so the wage answer wins over the hotline handoff.
    assert TINGTING_SUPPORT_PERSONA.index(TINGTING_WAGE_WAIT_REPLY) < TINGTING_SUPPORT_PERSONA.index(
        "MỌI việc khác"
    )
    # a *mức lương* (salary-level) question stays out of scope — only the payday
    # question is answered in-chat.
    assert "mức lương/phúc lợi" in TINGTING_SUPPORT_PERSONA
    # the owner narrowed the trigger (2026-10-05): payday-timing and benefits
    # questions stay out of scope — only the pay-status question is answered.
    assert "bao giờ nhận lương" not in TINGTING_SUPPORT_PERSONA
    assert "bao giờ nhận lương" not in TINGTING_API_GUIDE
    # the TingTing OA never answers benefits questions (owner, 2026-10-05):
    # both sections route them to the hotline reply and forbid reusing the
    # waiting line for them.
    for prompt in (TINGTING_SUPPORT_PERSONA, TINGTING_API_GUIDE):
        assert "Hỏi về phúc lợi" in prompt
        assert "KHÔNG dùng câu trả lời chờ dữ liệu tiền công" in prompt


def test_self_checkin_question_gets_the_fixed_media_caption() -> None:
    """Operator rules (2026-10-05/06): a self-check-in intent gets caption + image.

    Both prompt sections quote the fixed caption verbatim; the send layer
    attaches the repo-hosted app-home screenshot when a TingTing OA reply
    matches it exactly, so the prompt owns only the words. The rule classifies
    the intent, not example phrasings — Jev's ``self_checkin`` judgment is the
    primary trigger (the old phrase list missed "đăng ký tự chấm công") and
    this is its degraded fallback. Like the payday rule, the media rule sits
    before the out-of-scope catch-all.
    """
    for prompt in (TINGTING_SUPPORT_PERSONA, TINGTING_API_GUIDE):
        assert TINGTING_SELF_CHECKIN_REPLY in prompt
        assert "TỰ CHẤM CÔNG trên ứng dụng TingTing" in prompt
        assert "không theo từ khóa" in prompt
        assert "ảnh màn hình chính" in prompt
        assert "KHÔNG trả lời dòng hotline" in prompt
    # the guide image is repo-hosted at the production frontend root — the
    # send layer's asset, never a third-party host.
    assert TINGTING_SELF_CHECKIN_IMAGE_URL == "https://bot.tingting.vip/tingting/tu-cham-cong.png"
    # the escalation reply is reserved for the can't-help cases; the media
    # caption is a real answer and never carries it.
    assert TINGTING_HOTLINE_REPLY not in TINGTING_SELF_CHECKIN_REPLY
    # precedence: the media rule sits before the out-of-scope catch-all.
    assert TINGTING_SUPPORT_PERSONA.index(TINGTING_SELF_CHECKIN_REPLY) < TINGTING_SUPPORT_PERSONA.index(
        "MỌI việc khác"
    )


def test_login_trouble_after_resolution_re_engages_the_reset_flow() -> None:
    """Naming login trouble again restarts the reset flow after the closer.

    The resolved-state rule must not swallow a genuine reset request: the
    re-engagement condition in both sections has to sit alongside the untouched
    login-trouble entry that runs the flow straight to the three-field ask.
    """
    for prompt in (TINGTING_SUPPORT_PERSONA, TINGTING_API_GUIDE):
        assert "TỰ nhắc lại rắc rối đăng nhập" in prompt
        assert "RẮC RỐI ĐĂNG NHẬP" in prompt
        assert TINGTING_FIELDS_ASK in prompt


def test_login_trouble_is_reset_intent_not_a_handoff() -> None:
    """BOT-01 follow-up: "Ứng dụng đăng nhập kiểu gì" must enter the reset flow.

    Production (2026-09-28 15:36, TingTing support OA): after the confirm
    question, a login-trouble reply was answered with the consultant handoff
    line on the same turn. Login trouble IS the reset flow's customer: both
    prompt sections must route it straight to the three-field ask instead of
    escalating.
    """
    for prompt in (TINGTING_SUPPORT_PERSONA, TINGTING_API_GUIDE):
        assert "RẮC RỐI ĐĂNG NHẬP" in prompt
        assert "đăng nhập kiểu gì" in prompt
        assert TINGTING_FIELDS_ASK in prompt
    # routed INTO the flow, never out to the escalation reply
    assert "KHÔNG trả lời dòng hotline" in TINGTING_SUPPORT_PERSONA
    assert "không trả lời dòng hotline" in TINGTING_API_GUIDE


def test_support_persona_forbids_other_employee_data_and_the_recruitment_role() -> None:
    """The OA persona is the code-defined password-reset assistant, nothing else."""
    assert "KHÔNG tra cứu" in TINGTING_SUPPORT_PERSONA
    assert "KHÔNG phải trợ lý tuyển dụng VFIC" in TINGTING_SUPPORT_PERSONA

    with_guide = tingting_support_system_prompt(include_guide=True, hotline=_TINGTING_HOTLINE)
    assert TINGTING_SUPPORT_PERSONA in with_guide
    assert TINGTING_API_BLOCK_HEADER in with_guide

    without_guide = tingting_support_system_prompt(include_guide=False, hotline=_TINGTING_HOTLINE)
    assert TINGTING_SUPPORT_PERSONA in without_guide
    assert TINGTING_API_BLOCK_HEADER not in without_guide


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
async def test_no_agent_tool_returns_the_employee_record() -> None:
    """The employee is the party being verified, so the record is an answer key.

    The lookup answers only through ``verify_tingting_identity`` verdict booleans;
    a tool that hands the model the record body would let anyone holding the
    phone number have it read back to them.
    """
    from app.graph.runtime_policy import TINGTING_TOOL_NAMES
    from app.graph.schemas import TOOL_SCHEMAS
    from app.graph.tools import TOOLS_REGISTRY
    from app.graph import tools as tool_package

    assert "call_tingting_api" not in TINGTING_TOOL_NAMES
    assert "call_tingting_api" not in TOOLS_REGISTRY
    assert not hasattr(tool_package, "call_tingting_api")
    assert all(
        schema["function"]["name"] != "call_tingting_api" for schema in TOOL_SCHEMAS
    )

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
    assert retrieval.saved[-1] == {
        "reset_token": "tok-9",
        "otp_verified": True,
        "otp_code": "123456",
    }
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
    first = retrieval.calls[0]["params"]
    assert first["reset_token"] == "tok-9"
    assert re.fullmatch(r"Vfic@[0-9]{6}", first["new_password"])
    assert retrieval.cleared == 1
    assert "Abc12345" in result
    # The login name the employee is told is the registered mobile/CCCD, and the
    # record's own username/name never reach the reply.
    assert "số điện thoại hoặc CCCD/CMND đã đăng ký với công ty" in result
    assert "nv.dung" not in result
    assert "Nguyễn Việt Dũng" not in result


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


def test_the_flow_key_folds_the_country_code() -> None:
    """The same employee must keep one flow whether they type 0… or +84…."""
    from app.services.tingting_api import _flow_key

    assert _flow_key("0987654321") == _flow_key("+84 987 654 321")
    assert _flow_key("0987654321") == _flow_key("0987 654 321")
    assert _flow_key("0987654321") != _flow_key("0123456789")
    assert "0987654321" not in _flow_key("0987654321")  # never the number itself


# ── the one-time password the employee has to type ──────────────────────────


def test_generated_password_uses_the_verified_otp() -> None:
    """The operator's format: Vfic@<otp>, so the digits are the code just typed."""
    assert generate_simple_password("123980") == "Vfic@123980"
    assert generate_simple_password(" 321456 ") == "Vfic@321456"
    # No usable code (an expired session, a flow started before this format):
    # keep the shape with random digits rather than failing the reset.
    fallback = generate_simple_password("")
    assert re.fullmatch(r"Vfic@[0-9]{6}", fallback)
    assert generate_simple_password("12ab") != "Vfic@12ab"


@pytest.mark.asyncio
async def test_reset_sets_the_otp_shaped_password_not_the_provider_one() -> None:
    """The provider minted `PN&&mf6P73x4`; the employee could not type it."""
    retrieval = _FlowRetrieval(
        _reset_ok(), state={"reset_token": "tok-9", "otp_code": "123980"}
    )
    result = await reset_tingting_password(retrieval, phone="0987654321")
    sent = retrieval.calls[0]["params"]
    assert sent == {"reset_token": "tok-9", "new_password": "Vfic@123980"}
    # The app echoes the password it stored; that echo is what the model reads out.
    assert "Abc12345" in result


@pytest.mark.asyncio
async def test_confirm_keeps_the_code_for_the_password_shape() -> None:
    retrieval = _FlowRetrieval(_verify_ok("tok-9"), state={"session_id": "sess-42"})
    await confirm_tingting_otp(retrieval, phone="0987654321", code="123980")
    assert retrieval.saved[-1]["otp_code"] == "123980"


@pytest.mark.asyncio
async def test_reset_falls_back_when_the_policy_rejects_the_simple_password() -> None:
    """An app-side policy our style misses must not fail the employee's reset."""
    retrieval = _FlowRetrieval(
        outcomes=[
            _outcome("error", status=400, detail="status_400"),
            _reset_ok(),
        ],
        state={"reset_token": "tok-9"},
    )
    result = await reset_tingting_password(retrieval, phone="0987654321")
    assert len(retrieval.calls) == 2
    assert "new_password" in retrieval.calls[0]["params"]
    assert retrieval.calls[1]["params"] == {"reset_token": "tok-9"}  # app-generated
    assert "Abc12345" in result
    assert "hệ thống tự sinh" in result
    assert "nv.dung" not in result
    assert "Nguyễn Việt Dũng" not in result


# ── the channel scope: the flow belongs to the TingTing Zalo OA ─────────────


def _conversation(provider: str, account_key: str):
    from types import SimpleNamespace

    return SimpleNamespace(
        channel_identity=SimpleNamespace(provider=provider, account_key=account_key)
    )


class _ScopeDeps:
    def __init__(self, pin: str = "") -> None:
        from types import SimpleNamespace

        async def _pin() -> str:
            return pin

        self.retrieval = SimpleNamespace(tingting_reset_oa_id=_pin, tingting_api_configured=lambda: None)


@pytest.mark.asyncio
async def test_reset_flow_runs_only_on_the_linked_support_oa() -> None:
    """The original OA, the recruitment Bot and Messenger must never reach it."""
    from app.graph.runner import _tingting_reset_allowed
    from app.services.tingting_oa import TINGTING_OA_ACCOUNT_KEY

    deps = _ScopeDeps(TINGTING_OA_ACCOUNT_KEY)
    assert (
        await _tingting_reset_allowed(deps, _conversation("zalo_oa", TINGTING_OA_ACCOUNT_KEY))
        is True
    )
    # The original recruitment OA keeps its own conversations — and no reset flow.
    assert await _tingting_reset_allowed(deps, _conversation("zalo_oa", "default:zalo_oa")) is False
    assert await _tingting_reset_allowed(deps, _conversation("zalo_bot", "default:zalo_bot")) is False
    assert (
        await _tingting_reset_allowed(deps, _conversation("facebook_messenger", "486833177846024"))
        is False
    )


@pytest.mark.asyncio
async def test_an_unlinked_or_mismatched_binding_turns_the_flow_off() -> None:
    from app.graph.runner import _tingting_reset_allowed
    from app.services.tingting_oa import TINGTING_OA_ACCOUNT_KEY

    # Never linked: the pin is empty, so even a support-OA-shaped identity is refused.
    unlinked = _ScopeDeps("")
    assert (
        await _tingting_reset_allowed(
            unlinked, _conversation("zalo_oa", TINGTING_OA_ACCOUNT_KEY)
        )
        is False
    )
    # A stale pin pointing somewhere else (e.g. an account key typed in before the
    # link replaced it) is refused too: only the verified support account counts.
    stale = _ScopeDeps("default:zalo_oa")
    assert (
        await _tingting_reset_allowed(
            stale, _conversation("zalo_oa", TINGTING_OA_ACCOUNT_KEY)
        )
        is False
    )


@pytest.mark.asyncio
async def test_a_scope_read_error_fails_closed() -> None:
    from types import SimpleNamespace

    from app.graph.runner import _tingting_reset_allowed

    async def _boom() -> str:
        raise RuntimeError("db down")

    deps = SimpleNamespace(retrieval=SimpleNamespace(tingting_reset_oa_id=_boom))
    assert await _tingting_reset_allowed(deps, _conversation("zalo_oa", "any")) is False


@pytest.mark.asyncio
async def test_a_conversation_without_an_identity_is_refused() -> None:
    from types import SimpleNamespace

    from app.graph.runner import _tingting_reset_allowed

    deps = _ScopeDeps()
    assert await _tingting_reset_allowed(deps, SimpleNamespace(channel_identity=None)) is False


# ── the OA pin (admin surface) ──────────────────────────────────────────────


class _MultiRowSession:
    """Session double keyed by integration-setting key (api key + OA pin)."""

    def __init__(self) -> None:
        self.rows: dict[str, SimpleNamespace] = {}

    async def get(self, _model, key):  # noqa: ANN001
        return self.rows.get(key)

    def add(self, obj) -> None:  # noqa: ANN001
        key = getattr(obj, "key", None)
        if key is not None:
            self.rows[key] = obj

    async def flush(self) -> None:
        return None

    async def commit(self) -> None:
        return None


@pytest.mark.asyncio
async def test_the_reset_oa_pin_round_trips_and_clears() -> None:
    from app.services.tingting_api import TINGTING_RESET_OA_ID_SETTING

    db = _MultiRowSession()
    service = TingtingApiService(db)
    assert await service.reset_oa_id() == ""

    view = await service.replace_reset_oa_id("tingting-oa-key", actor_id=None)
    assert view["reset_oa_id"] == "tingting-oa-key"
    assert await service.reset_oa_id() == "tingting-oa-key"
    assert db.rows[TINGTING_RESET_OA_ID_SETTING].is_secret is False

    cleared = await service.replace_reset_oa_id("", actor_id=None)
    assert cleared["reset_oa_id"] == ""
    assert await service.reset_oa_id() == ""

    kept = await service.replace_reset_oa_id(None, actor_id=None)
    assert kept["reset_oa_id"] == ""  # None keeps the stored value


@pytest.mark.asyncio
async def test_the_hotline_round_trips_and_reads_the_plaintext_seed() -> None:
    """The hotline setting round-trips, and the plaintext seed reads back verbatim.

    Alembic 0058 stores the owner-approved number WITHOUT the ``v1:`` prefix;
    the cipher fails soft on unprefixed rows, so the seeded value and a later
    admin-encrypted edit both read through the same getter — and a cleared row
    reads empty, which the reply builder degrades on (no code fallback).
    """
    from app.services.tingting_api import TINGTING_HOTLINE_SETTING

    db = _MultiRowSession()
    service = TingtingApiService(db)
    assert await service.hotline() == ""

    # The seeded row (plaintext, is_secret=False) reads back verbatim.
    db.rows[TINGTING_HOTLINE_SETTING] = SimpleNamespace(
        key=TINGTING_HOTLINE_SETTING,
        encrypted_value="+84 914 827 988",
        is_secret=False,
        updated_by=None,
    )
    assert await service.hotline() == "+84 914 827 988"
    assert (await service.admin_view())["hotline"] == "+84 914 827 988"

    # An admin edit encrypts, still reads back, and clearing empties it.
    edited = await service.replace_hotline("0914 827 988", actor_id=None)
    assert edited["hotline"] == "0914 827 988"
    assert db.rows[TINGTING_HOTLINE_SETTING].encrypted_value.startswith("v1:")
    assert await service.hotline() == "0914 827 988"

    cleared = await service.replace_hotline("", actor_id=None)
    assert cleared["hotline"] == ""
    assert await service.hotline() == ""

    kept = await service.replace_hotline(None, actor_id=None)
    assert kept["hotline"] == ""  # None keeps the stored value


def test_the_seed_migration_pins_the_owner_approved_hotline() -> None:
    """The digits are pinned at the SEED, never in runtime copy (owner ruling).

    Runtime replies are built from the stored setting, so the only place
    the owner-approved number may live in source is Alembic 0058. This pins
    the seed value plus the two guards that keep operator edits
    authoritative: upgrade inserts only when the row is absent, downgrade
    deletes only the exact seed value.
    """
    import importlib.util
    from pathlib import Path

    migration_path = (
        Path(__file__).resolve().parents[1]
        / "alembic"
        / "versions"
        / "0058_tingting_hotline_setting.py"
    )
    spec = importlib.util.spec_from_file_location("seed_0058", migration_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert module.SEED_VALUE == "+84 914 827 988"

    captured: list[str] = []
    real_execute = module.op.execute
    module.op.execute = lambda sql: captured.append(str(sql))
    try:
        module.upgrade()
        module.downgrade()
    finally:
        module.op.execute = real_execute
    upgrade_sql = captured[0]
    downgrade_sql = captured[1]
    assert "914827988" in upgrade_sql.replace(" ", "")
    assert "WHERE NOT EXISTS" in upgrade_sql  # operator edits win over the seed
    # Downgrade is value-guarded: an admin-edited (re-sealed) row survives.
    assert "DELETE FROM public.integration_settings" in downgrade_sql
    assert "'+84 914 827 988'" in downgrade_sql


def test_the_hotline_correction_migration_carries_the_owner_value_forward() -> None:
    """Alembic 0058's seed is history; 0072 carries the owner's current number.

    0058 must not be edited — it has already been applied everywhere, and its
    value records what was approved then. So the correction is a separate,
    reversible data migration that keeps 0058's central contract: an operator
    edit (an admin-encrypted ``v1:`` row, which matches neither guard) always
    wins over the seeded value.
    """
    import importlib.util
    from pathlib import Path

    migration_path = (
        Path(__file__).resolve().parents[1]
        / "alembic"
        / "versions"
        / "0072_tingting_hotline_number.py"
    )
    spec = importlib.util.spec_from_file_location("correction_0072", migration_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert module.HOTLINE_VALUE == "02256548788"
    assert module.PREVIOUS_VALUE == "+84 914 827 988"
    assert module.down_revision == "0071_lead_project_id"

    captured: list[str] = []
    real_execute = module.op.execute
    module.op.execute = lambda sql: captured.append(str(sql))
    try:
        module.upgrade()
        module.downgrade()
    finally:
        module.op.execute = real_execute

    update, insert, restore = captured

    # Upgrade rewrites only the superseded seed, never an operator edit.
    assert "UPDATE public.integration_settings" in update
    assert "'02256548788'" in update
    assert "AND encrypted_value = '+84 914 827 988'" in update
    # A deployment that never seeded gets the current number rather than none.
    assert "WHERE NOT EXISTS" in insert
    assert "'02256548788'" in insert
    # Downgrade is value-guarded in the other direction.
    assert "UPDATE public.integration_settings" in restore
    assert "'+84 914 827 988'" in restore
    assert "AND encrypted_value = '02256548788'" in restore


def test_the_number_lives_in_a_migration_and_never_in_runtime_copy() -> None:
    """The owner-approved number may appear in a migration and nowhere else.

    The runtime reads only the stored setting, so a number written into the
    persona, the guide or an escalation reply would silently drift from the
    admin-edited value — the exact failure 0058 was written to avoid. The
    builder is passed the value, so it must not carry one of its own either.
    """
    from pathlib import Path

    from app.graph import tingting_guide

    runtime_dir = Path(__file__).resolve().parents[1] / "app"
    sources = [
        path
        for path in runtime_dir.rglob("*.py")
        if "alembic" not in path.parts
    ]
    for digits in ("02256548788", "914827988"):
        offenders = [
            str(path.relative_to(runtime_dir))
            for path in sources
            if digits in path.read_text(encoding="utf-8").replace(" ", "")
        ]
        assert offenders == [], f"{digits} is hardcoded in runtime source: {offenders}"

    # The builder quotes whatever it is given, verbatim, with no fallback of its
    # own — an empty setting degrades to the honest no-number sentence.
    assert "02256548788" in tingting_guide.tingting_hotline_reply(
        "02256548788"
    ).replace(" ", "")
    assert "02256548788" not in tingting_guide.tingting_hotline_reply("")
