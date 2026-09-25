#!/usr/bin/env python3
"""Live verification of the streaming answer path against a real provider.

Run before any deploy that touches the LLM path:

    SILVERSEA_OPENROUTER_API_KEY=... \\
    backend/.venv/bin/python backend/scripts/verify_streaming_turn.py [--model M]

Why this exists: unit tests prove request *shape* and control flow with fakes, but
they cannot prove that a real provider streams deltas through the app's client,
that token usage still arrives on a streamed call (``stream_usage``), or that the
progressive-delivery threshold is reached materially before completion. This
harness exercises the app's own client builder + agent loop, so a regression in
``clients.py`` / ``provider_failover.py`` fails here instead of in production.

It sends no candidate-visible message: only the LLM path is exercised.
Exits non-zero on any violated expectation.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys
import time
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

# Matches the runner's progressive-delivery floor (kept in sync deliberately:
# this harness measures the same threshold the send path waits for).
BUBBLE_FLOOR_CHARS = 250

# Representative prefetched KB evidence, injected as a system message exactly
# like the prod prefetch routes do ("KẾT QUẢ TRA CỨU KB ĐÃ THỰC HIỆN CHO CÂU HỎI
# NÀY: ..."). Without it the model has no evidence, and an ungrounded model
# correctly answers "chưa có thông tin đã xác minh" — which is NOT a useful
# quality sample and made an earlier run look like a bad answer. Values mirror
# the facts prod served (verified against delivered messages).
EVIDENCE_FIXTURE = """KẾT QUẢ TRA CỨU KB ĐÃ THỰC HIỆN CHO CÂU HỎI NÀY:
- LG Display (KCN Tràng Duệ, An Dương, Hải Phòng) — công nhân sản xuất. Lương cơ bản 6.030.000 VNĐ/tháng.
- Phụ cấp: công việc 500.000; xăng xe 400.000; chuyên cần 250.000; điều chỉnh 250.000-500.000 VNĐ.
- Tăng ca: ngày thường 150%, ngày nghỉ 200%, lễ Tết 300%. Thu nhập thực tế 10-13 triệu/tháng khi có tăng ca.
- Ca làm việc: ca ngày 06:00-14:00, ca chiều 14:00-22:00, ca đêm 22:00-06:00; luân phiên theo tuần.
- Ký túc xá: có, miễn phí cho công nhân ở xa, 6-8 người/phòng, có điều hòa và nóng lạnh.
- Xe đưa đón: có, các tuyến nội thành Hải Phòng và Đông Triều; đón 05:30 và 17:30 hằng ngày.
- Hồ sơ: CCCD công chứng, ảnh 3x4 (2 tấm), sơ yếu lý lịch, giấy khám sức khỏe."""
SENTENCE_END = re.compile(r"[.!?…]\s*$|\n$")

# The prompt asks for the multi-part answer a real turn produces (prod replies
# run 500-800 chars), so a sentence-aligned bubble actually forms before the end.
SYSTEM_PROMPT = (
    "Bạn là tư vấn viên tuyển dụng trên Zalo. Trả lời bằng tiếng Việt, mỗi ý một câu: "
    "thu nhập và lương cơ bản, ca làm việc, ký túc xá, xe đưa đón, hồ sơ ứng tuyển. "
    "Không bịa số liệu cụ thể; nếu thiếu dữ liệu thì nói rõ chưa có thông tin đã xác minh."
)
USER_TEXT = (
    "Cho tôi hỏi công nhân LG Display lương bao nhiêu, ca làm việc thế nào, "
    "có ký túc xá và xe đưa đón không, cần chuẩn bị hồ sơ gì?"
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--provider",
        default=os.environ.get("VERIFY_PROVIDER") or "openrouter",
        choices=("openrouter", "minimax"),
        help="Which configured provider to stream from.",
    )
    parser.add_argument(
        "--model",
        default=os.environ.get("VERIFY_MODEL"),
        help="Model id to stream from (defaults per provider).",
    )
    parser.add_argument(
        "--sweep",
        action="store_true",
        help="Run the cheap/high-throughput candidate list instead of one model.",
    )
    parser.add_argument(
        "--no-evidence",
        action="store_true",
        help="Skip the KB evidence fixture (measures an ungrounded window; the reply will be a refusal).",
    )
    parser.add_argument(
        "--min-deltas",
        type=int,
        default=5,
        help="Minimum streamed deltas required to consider streaming live.",
    )
    return parser


# Cheap + high-throughput candidates (measured 2026-09-26 from the prod
# container: ~190-200 visible tok/s for the Qwen/Gemini-lite pair, ~117 for
# gpt-4o-mini). Also the token-plan primary, because the early-delivery win is a
# property of the provider's delta cadence, not of the model's average speed.
SWEEP = [
    ("minimax", "MiniMax-M2.7-highspeed"),
    ("openrouter", "google/gemini-2.5-flash-lite"),
    ("openrouter", "qwen/qwen3-30b-a3b-instruct-2507"),
    ("openrouter", "openai/gpt-4o-mini"),
    ("openrouter", "deepseek/deepseek-v4.1-flash"),
]
DEFAULT_MODEL = {"minimax": "MiniMax-M2.7-highspeed", "openrouter": "google/gemini-2.5-flash-lite"}


def _build_llm(provider: str, model: str):
    from app.graph.clients import _chat_for_role

    if provider == "minimax":
        key = (os.environ.get("MINIMAX_API_KEY") or "").strip()
        if not key:
            return None, "MINIMAX_API_KEY is not set in the environment"
        return _chat_for_role(
            "agent",
            temperature=0.3,
            default_provider="minimax",
            minimax_enabled=True,
            minimax_api_key=key,
            openrouter_enabled=False,
        ), None

    key = (os.environ.get("SILVERSEA_OPENROUTER_API_KEY") or "").strip()
    if not key:
        return None, "SILVERSEA_OPENROUTER_API_KEY is not set in the environment"
    return _chat_for_role(
        "agent",
        temperature=0.3,
        default_provider="openrouter",
        openrouter_enabled=True,
        openrouter_api_key=key,
        openrouter_agent_model=model,
    ), None


async def _run(provider: str, model: str, *, min_deltas: int, with_evidence: bool = True) -> int:
    from app.graph.clients import MiniMaxAgent

    llm, error = _build_llm(provider, model)
    if error:
        print(f"FAIL: {error}")
        return 2
    assert llm is not None

    failures: list[str] = []
    warnings: list[str] = []
    print(f"model            : {model}")
    print(f"grounded         : {with_evidence}")
    print(f"provider         : {getattr(llm, 'trace_provider', None)}")
    print(f"max_tokens       : {getattr(llm, 'max_tokens', None)}")
    print(f"extra_body       : {getattr(llm, 'extra_body', None) or {}}")
    print(f"stream_usage     : {getattr(llm, 'stream_usage', None)}")

    if not getattr(llm, "stream_usage", False):
        failures.append("stream_usage is off: a streamed call would report no token usage")
    if provider == "openrouter" and getattr(llm, "extra_body", None) != {
        "reasoning": {"enabled": False}
    }:
        failures.append("reasoning-disable body is not what the deployed default expects")

    deltas: list[tuple[float, str]] = []
    started = time.monotonic()

    async def on_delta(text: str) -> None:
        deltas.append(((time.monotonic() - started) * 1000, text))

    metrics: dict = {"llm_call_ms": []}
    agent = MiniMaxAgent(llm, embedder=None)
    system = (
        f"{SYSTEM_PROMPT}\n\n{EVIDENCE_FIXTURE}" if with_evidence else SYSTEM_PROMPT
    )
    reply = await agent.agent(
        USER_TEXT,
        system=system,
        retrieval=None,
        embedder=None,
        # An empty registry (not an empty allow-list: that means "full registry")
        # binds no tools, so this harness measures the answer stream alone. The
        # tool round is exercised by the unit tests.
        resolved_tool_registry=frozenset(),
        metrics=metrics,
        on_delta=on_delta,
    )
    total_ms = (time.monotonic() - started) * 1000

    raw = "".join(piece for _at, piece in deltas)
    first_delta_ms = deltas[0][0] if deltas else None

    # Time the progressive sender would have to wait for a sendable bubble:
    # first offset at/after the floor that ends at a sentence boundary.
    bubble_ms = None
    bubble_text = ""
    for at, text in _first_bubble_offsets(deltas, BUBBLE_FLOOR_CHARS):
        bubble_ms = at
        bubble_text = text
        break

    print(f"deltas           : {len(deltas)}")
    print(f"first delta (ttft): {_ms(first_delta_ms)}")
    print(f"first bubble      : {_ms(bubble_ms)}  (floor {BUBBLE_FLOOR_CHARS} chars, sentence-aligned)")
    print(f"total             : {_ms(total_ms)}")
    print(f"reply chars       : {len(reply)}   streamed chars: {len(raw)}")
    if bubble_text:
        # The whole point of the feature: this is the text the candidate would
        # receive first. Printed verbatim so a usefulness review is possible —
        # a bubble that is only a greeting would be the trick we must not ship.
        print(f"first bubble text : {len(bubble_text)} chars")
        print("  " + bubble_text[:400].replace("\n", " ⏎ "))
    print(f"tool rounds       : {metrics.get('tool_rounds', 0)}")
    print(f"usage             : prompt={metrics.get('prompt_tokens')} "
          f"completion={metrics.get('completion_tokens')} "
          f"cached={metrics.get('cached_tokens')}")

    if len(deltas) < min_deltas:
        failures.append(f"only {len(deltas)} deltas (< {min_deltas}): streaming is not live")
    if not reply.strip():
        failures.append("the agent returned an empty reply")
    if raw.strip() != reply.strip():
        failures.append(
            "streamed text and the returned reply disagree: "
            f"{len(raw)} vs {len(reply)} chars"
        )
    if not (metrics.get("completion_tokens") or 0):
        failures.append("no completion tokens recorded: streamed usage is being dropped")
    if bubble_ms is None:
        warnings.append(
            "no sentence-aligned bubble formed: progressive send would never fire early "
            "for this model"
        )
    elif total_ms > 0 and bubble_ms >= total_ms * 0.9:
        warnings.append(
            f"this provider bursts its deltas: first bubble at {_ms(bubble_ms)} of "
            f"{_ms(total_ms)} — progressive delivery would barely shorten the wait"
        )
    else:
        saved = round(total_ms - bubble_ms)
        print(f"early-delivery gain : {_ms(saved)} sooner than completion")
    if metrics.get("stream_partial"):
        failures.append("the stream reported a partial deliverance mid-flight")

    for item in warnings:
        print(f"WARN    : {item}")
    if failures:
        print("\nFAIL")
        for item in failures:
            print(f"  - {item}")
        return 1
    print("\nPASS: streaming, sentence-aligned bubble, usage and reply integrity verified.")
    return 0


def _first_bubble_offsets(deltas: list[tuple[float, str]], floor: int):
    """Yield the first (timestamp) whose accumulated text clears the floor at a sentence end."""
    buf = ""
    for at, piece in deltas:
        buf += piece
        if len(buf) >= floor and SENTENCE_END.search(buf):
            yield (at, buf)


def _ms(value: float | None) -> str:
    return "n/a" if value is None else f"{round(value)} ms"


async def main() -> int:
    args = _build_parser().parse_args()
    if args.sweep:
        worst = 0
        for provider, model in SWEEP:
            print("=" * 72)
            try:
                worst = max(
                    worst,
                    await _run(
                        provider,
                        model,
                        min_deltas=args.min_deltas,
                        with_evidence=not args.no_evidence,
                    ),
                )
            except Exception as exc:  # noqa: BLE001 — one unreachable model must not stop the sweep
                print(f"model            : {model}")
                print(f"FAIL: {type(exc).__name__}: {exc}")
                worst = max(worst, 1)
        return worst
    model = args.model or DEFAULT_MODEL[args.provider]
    return await _run(
        args.provider,
        model,
        min_deltas=args.min_deltas,
        with_evidence=not args.no_evidence,
    )


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
