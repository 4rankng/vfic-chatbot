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
import time
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)

# Bounded so a hung endpoint cannot hold an admin request open indefinitely.
_PROBE_TIMEOUT_SECONDS = 20


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


def _extract_reply(payload: dict) -> str:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    if not isinstance(message, dict):
        return ""
    return str(message.get("content") or "").strip()


async def probe_openai_compatible_chat(
    *,
    api_key: str,
    base_url: str,
    model: str,
) -> LlmProbeResult:
    """Send one tiny completion and report whether the provider answered."""
    started = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=_PROBE_TIMEOUT_SECONDS) as client:
            response = await client.post(
                _completions_url(base_url),
                headers={"Authorization": f"Bearer {api_key}"},
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": "ping"}],
                    "max_tokens": 16,
                },
            )
    except Exception as exc:  # noqa: BLE001 — a probe reports failure, never raises
        logger.warning("custom LLM probe transport failure for model=%s", model, exc_info=True)
        return LlmProbeResult(
            ok=False,
            latency_ms=int((time.monotonic() - started) * 1000),
            error=_redact(f"Không kết nối được: {exc}", [api_key]),
        )

    latency_ms = int((time.monotonic() - started) * 1000)
    if response.status_code >= 400:
        # The provider's own message is the useful part (wrong key, unknown
        # model, no quota) — surfaced to the admin, never to a candidate.
        return LlmProbeResult(
            ok=False,
            latency_ms=latency_ms,
            error=_redact(f"HTTP {response.status_code}: {response.text}", [api_key]),
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
    if not reply:
        return LlmProbeResult(
            ok=False,
            latency_ms=latency_ms,
            error="Endpoint trả lời nhưng không có nội dung — kiểm tra lại tên model.",
        )
    return LlmProbeResult(ok=True, latency_ms=latency_ms, sample=reply[:160])
