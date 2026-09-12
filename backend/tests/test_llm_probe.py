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
    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, *a, **k):
            return response

    monkeypatch.setattr("app.services.llm_probe.httpx.AsyncClient", _Client)


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
