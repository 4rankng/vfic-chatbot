"""Probe result interpretation for an operator-supplied OpenAI-compatible endpoint.

A probe exists to answer "will this work as a provider?". Reporting a healthy
reasoning model as broken sends the operator hunting for a wrong model name.
"""

from __future__ import annotations

import pytest

from app.services.llm_probe import _extract_reply, _finish_reason, probe_openai_compatible_chat


def test_plain_content_is_extracted():
    payload = {"choices": [{"message": {"content": "pong"}}]}
    assert _extract_reply(payload) == "pong"


def test_reasoning_model_content_is_extracted():
    """MiMo / R1-style servers leave content empty and fill reasoning_content."""
    payload = {"choices": [{"message": {"content": "", "reasoning_content": "suy nghĩ..."}}]}
    assert _extract_reply(payload) == "suy nghĩ..."


def test_legacy_text_field_is_extracted():
    assert _extract_reply({"choices": [{"text": "pong"}]}) == "pong"


def test_content_wins_over_reasoning():
    payload = {"choices": [{"message": {"content": "pong", "reasoning_content": "..."}}]}
    assert _extract_reply(payload) == "pong"


@pytest.mark.parametrize("payload", [{}, {"choices": []}, {"choices": [{"message": {}}]}])
def test_missing_text_yields_empty(payload):
    assert _extract_reply(payload) == ""


def test_finish_reason_is_read():
    assert _finish_reason({"choices": [{"finish_reason": "length"}]}) == "length"
    assert _finish_reason({}) == ""


class _Response:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.text = str(payload)

    def json(self):
        return self._payload


def _patch_post(monkeypatch, response):
    """Patch the probe's HTTP client; returns the recorded (url, payload) calls.

    ``response`` may be one response or a list consumed in order, so a test can
    script a retry sequence (e.g. 404 then success on the /v1 spelling).
    """
    responses = iter(response if isinstance(response, list) else [response])
    calls: list[tuple[str, dict]] = []

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, *a, **k):
            calls.append((url, k.get("json")))
            return next(responses)

    monkeypatch.setattr("app.services.llm_probe.httpx.AsyncClient", _Client)
    return calls


async def test_reasoning_truncated_by_token_cap_is_reported_as_working(monkeypatch):
    """finish_reason=length means the cap cut it off, not that the provider is broken."""
    _patch_post(
        monkeypatch,
        _Response({"choices": [{"message": {"content": ""}, "finish_reason": "length"}]}),
    )

    result = await probe_openai_compatible_chat(api_key="k", base_url="https://x/v1", model="m")

    assert result.ok is True
    assert "endpoint hoạt động" in result.sample


async def test_empty_without_length_reports_the_providers_own_reason(monkeypatch):
    """The old message blamed the model name, which was misleading."""
    _patch_post(
        monkeypatch,
        _Response(
            {
                "choices": [{"message": {"content": ""}, "finish_reason": "content_filter"}],
                "usage": {"total_tokens": 9},
            }
        ),
    )

    result = await probe_openai_compatible_chat(api_key="k", base_url="https://x/v1", model="m")

    assert result.ok is False
    assert "content_filter" in result.error
    assert "kiểm tra lại tên model" not in (result.error or "")


async def test_non_openai_shape_is_called_out(monkeypatch):
    _patch_post(monkeypatch, _Response({"result": "hello"}))

    result = await probe_openai_compatible_chat(api_key="k", base_url="https://x/v1", model="m")

    assert result.ok is False
    assert "choices" in result.error


async def test_api_key_never_appears_in_an_error(monkeypatch):
    secret = "sk-super-secret-value"
    _patch_post(monkeypatch, _Response({"error": secret}, status_code=401))

    result = await probe_openai_compatible_chat(
        api_key=secret, base_url="https://x/v1", model="m"
    )

    assert result.ok is False
    assert secret not in (result.error or "")
    assert "[redacted]" in result.error


async def test_missing_v1_is_retried_and_succeeds(monkeypatch):
    """A 404 on a version-less base is retried once with /v1 inserted.

    This is the Xiaomi MiMo Token Plan setup: the host is right, but the chat
    contract lives under /v1 and the gateway 404s every other path with an
    opaque proxy page.
    """
    calls = _patch_post(
        monkeypatch,
        [
            _Response("<html>404 Not Found</html>", status_code=404),
            _Response({"choices": [{"message": {"content": "pong"}}]}),
        ],
    )

    result = await probe_openai_compatible_chat(
        api_key="tp-key", base_url="https://token-plan-sgp.xiaomimimo.com", model="mimo-v2.5-pro"
    )

    assert result.ok is True
    assert result.sample == "pong"
    assert calls[0][0] == "https://token-plan-sgp.xiaomimimo.com/chat/completions"
    assert calls[1][0] == "https://token-plan-sgp.xiaomimimo.com/v1/chat/completions"


async def test_probe_sends_no_token_cap(monkeypatch):
    """Providers split on max_tokens vs max_completion_tokens; send neither."""
    calls = _patch_post(
        monkeypatch, _Response({"choices": [{"message": {"content": "pong"}}]})
    )

    await probe_openai_compatible_chat(api_key="k", base_url="https://x/v1", model="m")

    assert "max_tokens" not in calls[0][1]
    assert "max_completion_tokens" not in calls[0][1]


async def test_persistent_404_names_the_base_url_fix(monkeypatch):
    """Both spellings 404 → say what to check instead of dumping proxy HTML."""
    _patch_post(
        monkeypatch,
        [
            _Response("<html>404</html>", status_code=404),
            _Response("<html>404</html>", status_code=404),
        ],
    )

    result = await probe_openai_compatible_chat(
        api_key="k", base_url="https://token-plan-sgp.xiaomimimo.com", model="m"
    )

    assert result.ok is False
    assert "Base URL" in result.error
    assert "/v1" in result.error
    assert "<html>" not in result.error


async def test_versioned_base_404_is_not_retried(monkeypatch):
    """The operator already included a version; retrying /v1/v1 cannot help."""
    calls = _patch_post(
        monkeypatch,
        [
            _Response("<html>404</html>", status_code=404),
            _Response({"unexpected": "second call should not happen"}, status_code=500),
        ],
    )

    result = await probe_openai_compatible_chat(
        api_key="k", base_url="https://token-plan-sgp.xiaomimimo.com/v1", model="m"
    )

    assert result.ok is False
    assert len(calls) == 1
    assert "Base URL" in result.error


async def test_html_error_body_is_compressed(monkeypatch):
    """A gateway HTML page carries no diagnostic value; keep it out of the line."""
    _patch_post(monkeypatch, _Response("<html>502 Bad Gateway</html>", status_code=502))

    result = await probe_openai_compatible_chat(api_key="k", base_url="https://x/v1", model="m")

    assert result.ok is False
    assert "trang HTML lỗi" in result.error
    assert "<html>" not in result.error
    assert "502" in result.error
