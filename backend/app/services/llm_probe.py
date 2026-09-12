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
# Room for a reasoning model to finish thinking and still emit a visible reply.
_PROBE_MAX_TOKENS = 256


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
    try:
        async with httpx.AsyncClient(timeout=_PROBE_TIMEOUT_SECONDS) as client:
            response = await client.post(
                _completions_url(base_url),
                headers={"Authorization": f"Bearer {api_key}"},
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": "ping"}],
                    # Generous on purpose. A reasoning model spends tokens
                    # thinking before it emits any content, so a tight cap
                    # returns finish_reason="length" with an empty content
                    # field — a working provider reported as broken.
                    "max_tokens": _PROBE_MAX_TOKENS,
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
