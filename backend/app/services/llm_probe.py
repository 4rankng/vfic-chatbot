"""Live reachability probe for an operator-supplied LLM provider.

Saving a base URL + credential without calling the provider is how an operator
discovers a typo during a real candidate conversation instead of at save time.
This performs one minimal chat completion so the settings page can refuse to
accept values that do not actually work.

The probe speaks the OpenAI ``/chat/completions`` contract over plain HTTP
rather than constructing a graph LLM client: the service layer may not import
``app.graph`` (see the architecture boundary test), and checking the raw
contract is exactly what "will this endpoint work as a provider?" means.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)

# Bounded so a hung endpoint cannot hold an admin request open indefinitely.
_PROBE_TIMEOUT_SECONDS = 20
# A base URL whose path ends in a version segment ("/v1", "/v2", ...). Only a
# version-less base gets the automatic /v1 retry on 404.
_VERSIONED_BASE_RE = re.compile(r"/v\d+$")


@dataclass(frozen=True)
class LlmProbeResult:
    ok: bool
    latency_ms: int
    sample: str | None = None
    error: str | None = None


def _redact(message: str, secrets: list[str]) -> str:
    """Never echo a credential back, even inside a provider error string."""
    for secret in secrets:
        if secret:
            message = message.replace(secret, "[redacted]")
    return message if len(message) <= 240 else f"{message[:237]}..."


def _completions_url(base_url: str) -> str:
    """Join the operator's base URL with the chat-completions path.

    Operators paste the base with or without a trailing slash, and sometimes
    already include ``/chat/completions``; accept all three spellings.
    """
    base = (base_url or "").strip().rstrip("/")
    if base.endswith("/chat/completions"):
        return base
    return f"{base}/chat/completions"


def _v1_completions_url(base_url: str) -> str:
    """The same endpoint with ``/v1`` inserted before the chat-completions path."""
    base = (base_url or "").strip().rstrip("/")
    return f"{base}/v1/chat/completions"


def _has_version_segment(base_url: str) -> bool:
    return bool(_VERSIONED_BASE_RE.search((base_url or "").strip().rstrip("/")))


def _error_body(response: httpx.Response) -> str:
    """The provider's own error text, with gateway HTML pages compressed.

    A reverse proxy's "404 Not Found" HTML page (openresty, nginx, Cloudflare)
    carries no diagnostic value for an admin and crowds out everything else in
    the truncated error line, so replace it with a short note.
    """
    body = (response.text or "").strip()
    if body.startswith("<"):
        return "(máy chủ trả về trang HTML lỗi, không có thông tin JSON)"
    return body


def _first_choice(payload: dict) -> dict | None:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return None
    return choices[0] if isinstance(choices[0], dict) else None


def _extract_reply(payload: dict) -> str:
    """Pull the assistant text out of an OpenAI-compatible response.

    Reasoning models (Xiaomi MiMo, DeepSeek-R1 and friends) leave ``content``
    empty and put the deliberation in ``reasoning_content``; some servers answer
    in the legacy top-level ``text`` field. Reading only ``content`` reports a
    perfectly healthy endpoint as broken.
    """
    choice = _first_choice(payload)
    if choice is None:
        return ""
    message = choice.get("message")
    if isinstance(message, dict):
        for key in ("content", "reasoning_content"):
            value = str(message.get(key) or "").strip()
            if value:
                return value
    return str(choice.get("text") or "").strip()


def _finish_reason(payload: dict) -> str:
    choice = _first_choice(payload)
    return str((choice or {}).get("finish_reason") or "").strip()


async def probe_openai_compatible_chat(
    *,
    api_key: str,
    base_url: str,
    model: str,
) -> LlmProbeResult:
    """Send one tiny completion and report whether the provider answered."""
    started = time.monotonic()
    headers = {"Authorization": f"Bearer {api_key}"}
    # No token cap on purpose. The runtime clients (langchain ChatOpenAI) send
    # no cap either, and providers split on the parameter name: newer
    # OpenAI-style servers renamed max_tokens → max_completion_tokens and
    # reject the legacy name with 400. Sending neither is the only spelling
    # every OpenAI-compatible endpoint accepts, and one "ping" completion
    # unbounded is still an admin-triggered, single-digit-cent call.
    payload = {"model": model, "messages": [{"role": "user", "content": "ping"}]}
    try:
        async with httpx.AsyncClient(timeout=_PROBE_TIMEOUT_SECONDS) as client:
            response = await client.post(_completions_url(base_url), headers=headers, json=payload)
            # The most common base-URL typo is a missing "/v1": the host is
            # right, but OpenAI-compatible gateways (Xiaomi MiMo's included)
            # serve the chat contract under /v1 and 404 every other path with
            # an opaque proxy page. Retry once with /v1 inserted before
            # reporting failure.
            if response.status_code == 404 and not _has_version_segment(base_url):
                response = await client.post(
                    _v1_completions_url(base_url), headers=headers, json=payload
                )
    except Exception as exc:  # noqa: BLE001 — a probe reports failure, never raises
        logger.warning("custom LLM probe transport failure for model=%s", model, exc_info=True)
        return LlmProbeResult(
            ok=False,
            latency_ms=int((time.monotonic() - started) * 1000),
            error=_redact(f"Không kết nối được: {exc}", [api_key]),
        )

    latency_ms = int((time.monotonic() - started) * 1000)
    if response.status_code == 404:
        # Both spellings (with and without /v1) were tried, or the operator's
        # base already carried a version: the host never exposed the chat
        # contract where we looked. Say what to check instead of dumping the
        # gateway's HTML error page.
        return LlmProbeResult(
            ok=False,
            latency_ms=latency_ms,
            error=(
                "HTTP 404: không tìm thấy /chat/completions trên máy chủ. "
                "Kiểm tra lại Base URL — endpoint OpenAI-compatible thường cần /v1 "
                "ở cuối (ví dụ: https://token-plan-sgp.xiaomimimo.com/v1 với "
                "Token Plan Singapore của Xiaomi)."
            ),
        )
    if response.status_code >= 400:
        # The provider's own message is the useful part (wrong key, unknown
        # model, no quota) — surfaced to the admin, never to a candidate.
        return LlmProbeResult(
            ok=False,
            latency_ms=latency_ms,
            error=_redact(
                f"HTTP {response.status_code}: {_error_body(response)}", [api_key]
            ),
        )

    try:
        payload = response.json()
    except ValueError:
        return LlmProbeResult(
            ok=False,
            latency_ms=latency_ms,
            error="Phản hồi không phải JSON — endpoint có thể không tương thích OpenAI.",
        )

    reply = _extract_reply(payload)
    if reply:
        return LlmProbeResult(ok=True, latency_ms=latency_ms, sample=reply[:160])

    # No text, but the request itself succeeded: the URL resolved, the key was
    # accepted and the model id was recognised. Whether that counts as a pass
    # depends on WHY the text is missing, so report the provider's own reason
    # instead of blaming the model name.
    finish = _finish_reason(payload)
    usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}
    logger.warning(
        "custom LLM probe returned no text: model=%s finish_reason=%s usage=%s keys=%s",
        model,
        finish or "(none)",
        usage,
        sorted(payload.keys()),
    )

    if finish == "length":
        # The token cap cut it off before any content — the provider works.
        return LlmProbeResult(
            ok=True,
            latency_ms=latency_ms,
            sample="(model suy luận hết token thử nghiệm — endpoint hoạt động bình thường)",
        )
    if _first_choice(payload) is None:
        return LlmProbeResult(
            ok=False,
            latency_ms=latency_ms,
            error="Phản hồi thiếu trường 'choices' — endpoint có thể không tương thích OpenAI.",
        )
    return LlmProbeResult(
        ok=False,
        latency_ms=latency_ms,
        error=(
            "Endpoint nhận yêu cầu nhưng không trả nội dung "
            f"(finish_reason={finish or 'không rõ'}, usage={usage or 'không có'})."
        ),
    )
