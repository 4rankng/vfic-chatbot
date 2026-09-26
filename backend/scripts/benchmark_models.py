#!/usr/bin/env python3
"""Speed benchmark for VFIC chatbot LLM model selection.

Compares candidate models on LATENCY and throughput (tok/s) using the real
production workload: ~3k-token Vietnamese persona system prompt, 5 bound tool
schemas, representative Vietnamese user messages, non-streaming ChatOpenAI.ainvoke.

MiniMax-M2.7-highspeed is the baseline; every other model is reported as a
speed ratio vs it.

Usage:
    cd backend
    .venv/bin/python -m scripts.benchmark_models
    .venv/bin/python -m scripts.benchmark_models --add nvidia/nemotron-3-nano-30b-a3b --runs 2 --warmup 0
    .venv/bin/python -m scripts.benchmark_models --models deepseek-v4-flash,nemotron-nano-30b
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import re
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# USER KNOBS — edit these, or use CLI flags
# ---------------------------------------------------------------------------
WARMUP_RUNS: int = 1
RUNS_PER_PROMPT: int = 5
BIND_TOOLS: bool = True
TEMPERATURE: float = 0.3
TIMEOUT_S: int = 60

# Provider -> (settings field for base_url, settings field for api_key)
PROVIDER_RESOLVE: dict[str, tuple[str, str]] = {
    "minimax": ("minimax_base_url", "minimax_api_key"),
    "openrouter": ("openrouter_base_url", "openrouter_api_key"),
}

# ---------------------------------------------------------------------------
# MODELS UNDER TEST — add / edit / remove entries here
# ---------------------------------------------------------------------------
# provider: "minimax" or "openrouter"
# baseline: True marks the reference model (speed ratios computed vs this)
MODEL_ENTRIES: list[dict] = [
    {
        "label": "minimax-m2.7-highspeed",
        "provider": "minimax",
        "model": "MiniMax-M2.7-highspeed",
        "baseline": True,
    },
    {
        "label": "minimax-m2.5-highspeed",
        "provider": "minimax",
        "model": "MiniMax-M2.5-highspeed",
    },
    {
        "label": "deepseek-v3.2",
        "provider": "openrouter",
        "model": "deepseek/deepseek-v3.2",
    },
    {
        "label": "deepseek-v4-flash",
        "provider": "openrouter",
        "model": "deepseek/deepseek-v4-flash",
    },
    {
        "label": "nemotron-nano-30b",
        "provider": "openrouter",
        "model": "nvidia/nemotron-3-nano-30b-a3b",
    },
    # >>> To test a new model, add one line: <<<
    # {"label": "gpt-4o-mini", "provider": "openrouter", "model": "openai/gpt-4o-mini"},
    # {"label": "claude-3.5-haiku", "provider": "openrouter", "model": "anthropic/claude-3.5-haiku"},
]

# Representative Vietnamese prompts (mix of greeting/lead + tool-triggering)
PROMPTS: list[str] = [
    "Xin chào, tôi đang muốn tìm việc làm ở Hải Phòng, có giới thiệu gì không?",
    "Cho tôi hỏi lịch xe đưa đón công nhân LG Display ca đêm ở Kiến An có những tuyến nào?",
    "Thu nhập của công nhân LG Display bao nhiêu, có KTX không?",
    "Tôi muốn làm công nhân, lương 8 triệu là được",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def strip_think(raw: str) -> str:
    """Remove MiniMax M2.x reasoning wrap (force-think tags).

    Re-implements the core of ``strip_think_reasoning`` (app/graph/safety.py)
    so the benchmark stays decoupled from the app package.
    """
    if not raw:
        return ""
    if re.search(r"</think\s*>", raw, flags=re.IGNORECASE):
        raw = re.split(r"</think\s*>", raw, flags=re.IGNORECASE)[-1]
    raw = re.sub(r"<think\b[^>]*>", "", raw, flags=re.IGNORECASE)
    return raw.strip()


def extract_usage(msg) -> dict:
    """Normalise token usage from langchain AIMessage.

    Tries usage_metadata first, falls back to response_metadata["token_usage"].
    Returns {prompt_tokens, completion_tokens, total_tokens, reasoning_tokens}.
    """
    usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "reasoning_tokens": 0}

    # Try langchain-normalised usage_metadata
    meta = getattr(msg, "usage_metadata", None)
    if isinstance(meta, dict):
        usage["prompt_tokens"] = meta.get("input_tokens", 0) or meta.get("prompt_tokens", 0)
        usage["completion_tokens"] = meta.get("output_tokens", 0) or meta.get(
            "completion_tokens", 0
        )
        usage["total_tokens"] = meta.get("total_tokens", 0)
        details = meta.get("output_token_details", {}) or meta.get("completion_tokens_details", {})
        usage["reasoning_tokens"] = details.get("reasoning_tokens", 0)
        if usage["prompt_tokens"]:
            return usage

    # Fallback: response_metadata["token_usage"]
    resp_meta = getattr(msg, "response_metadata", None)
    if isinstance(resp_meta, dict):
        tu = resp_meta.get("token_usage", {})
        if isinstance(tu, dict):
            usage["prompt_tokens"] = tu.get("prompt_tokens", 0)
            usage["completion_tokens"] = tu.get("completion_tokens", 0)
            usage["total_tokens"] = tu.get("total_tokens", 0)
            details = tu.get("completion_tokens_details", {})
            if isinstance(details, dict):
                usage["reasoning_tokens"] = details.get("reasoning_tokens", 0)

    return usage


def resolve_provider(provider: str, settings) -> tuple[str, str] | None:
    """Return (base_url, api_key) for a provider, or None if key missing."""
    if provider not in PROVIDER_RESOLVE:
        return None
    url_field, key_field = PROVIDER_RESOLVE[provider]
    base_url = getattr(settings, url_field, "")
    api_key = getattr(settings, key_field, "")
    if not api_key:
        return None
    return base_url, api_key


def build_client(entry: dict, settings):
    """Build a ChatOpenAI client mirroring the app's _minimax_chat/_openrouter_chat."""
    from langchain_openai import ChatOpenAI

    resolved = resolve_provider(entry["provider"], settings)
    if resolved is None:
        raise RuntimeError(f"missing api_key for provider '{entry['provider']}'")
    base_url, api_key = resolved

    client = ChatOpenAI(
        model=entry["model"],
        api_key=api_key,
        base_url=base_url,
        timeout=TIMEOUT_S,
        temperature=entry.get("temperature") or TEMPERATURE,
        max_retries=0,
    )
    return client


def build_bound_client(entry: dict, settings, tool_schemas):
    """Build client + optionally bind tool schemas."""
    client = build_client(entry, settings)
    if BIND_TOOLS and tool_schemas:
        client = client.bind_tools(tool_schemas)
    return client


def percentile(values: list[float], p: float) -> float:
    """Compute p-th percentile (0-100) without numpy."""
    if not values:
        return 0.0
    s = sorted(values)
    n = len(s)
    k = (n - 1) * p / 100.0
    lo = int(math.floor(k))
    hi = min(lo + 1, n - 1)
    frac = k - lo
    return s[lo] + (s[hi] - s[lo]) * frac


# ---------------------------------------------------------------------------
# Core benchmark loop
# ---------------------------------------------------------------------------


async def one_call(client, system_prompt: str, user_msg: str) -> dict:
    """Single ainvoke with timing. Returns sample dict; never raises."""
    from langchain_core.messages import HumanMessage, SystemMessage

    sample = {
        "latency_s": 0.0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "reasoning_tokens": 0,
        "reply_chars": 0,
        "had_tool_calls": False,
        "success": False,
        "error": None,
    }
    try:
        t0 = time.perf_counter()
        msg = await client.ainvoke(
            [SystemMessage(content=system_prompt), HumanMessage(content=user_msg)]
        )
        elapsed = time.perf_counter() - t0

        usage = extract_usage(msg)
        reply = strip_think(getattr(msg, "content", "") or "")

        sample.update(
            latency_s=round(elapsed, 3),
            prompt_tokens=usage["prompt_tokens"],
            completion_tokens=usage["completion_tokens"],
            total_tokens=usage["total_tokens"],
            reasoning_tokens=usage["reasoning_tokens"],
            reply_chars=len(reply),
            had_tool_calls=bool(getattr(msg, "tool_calls", None)),
            success=True,
        )
    except Exception as exc:
        sample["error"] = type(exc).__name__ + ": " + str(exc)[:120]
    return sample


async def bench_one_model(entry: dict, system_prompt: str, settings, tool_schemas) -> dict:
    """Run warmup + measured calls for one model. Returns aggregate dict."""
    # Check api_key availability
    resolved = resolve_provider(entry["provider"], settings)
    if resolved is None:
        return {
            "entry": entry,
            "success_rate": 0.0,
            "n_ok": 0,
            "n_fail": 1,
            "errors": {f"missing_api_key:{entry['provider']}": 1},
            "samples": [],
            "skipped": True,
        }

    client = build_bound_client(entry, settings, tool_schemas)
    samples: list[dict] = []

    # Warmup (discarded)
    for p in PROMPTS[:1]:  # warmup on first prompt only
        await one_call(client, system_prompt, p)

    # Measured runs — sequential
    for pi, prompt in enumerate(PROMPTS):
        for _ in range(RUNS_PER_PROMPT):
            sample = await one_call(client, system_prompt, prompt)
            sample["prompt_idx"] = pi
            samples.append(sample)

    ok = [s for s in samples if s["success"]]
    fail = [s for s in samples if not s["success"]]
    errors: dict[str, int] = {}
    for s in fail:
        err_key = s["error"] or "unknown"
        errors[err_key] = errors.get(err_key, 0) + 1

    return {
        "entry": entry,
        "success_rate": len(ok) / max(len(samples), 1),
        "n_ok": len(ok),
        "n_fail": len(fail),
        "errors": errors,
        "samples": samples,
        "skipped": False,
    }


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------


def aggregate(results: list[dict]) -> list[dict]:
    """Compute per-model aggregate stats from raw samples."""
    agg_list = []
    for r in results:
        entry = r["entry"]
        if r.get("skipped"):
            agg_list.append({**r})
            continue

        ok = [s for s in r["samples"] if s["success"]]
        if not ok:
            agg_list.append({**r})
            continue

        latencies = [s["latency_s"] for s in ok]
        tps_list = [s["completion_tokens"] / s["latency_s"] for s in ok if s["latency_s"] > 0]

        agg_list.append(
            {
                "entry": entry,
                "success_rate": r["success_rate"],
                "n_ok": r["n_ok"],
                "n_fail": r["n_fail"],
                "errors": r["errors"],
                "latency_mean": round(statistics.mean(latencies), 3),
                "latency_p50": round(percentile(latencies, 50), 3),
                "latency_p95": round(percentile(latencies, 95), 3),
                "latency_max": round(max(latencies), 3),
                "tps_mean": round(statistics.mean(tps_list), 1) if tps_list else 0,
                "prompt_tokens_mean": round(statistics.mean([s["prompt_tokens"] for s in ok]), 0),
                "completion_tokens_mean": round(
                    statistics.mean([s["completion_tokens"] for s in ok]), 0
                ),
                "reasoning_tokens_mean": round(
                    statistics.mean([s["reasoning_tokens"] for s in ok]), 0
                ),
                "reply_chars_mean": round(statistics.mean([s["reply_chars"] for s in ok]), 0),
                "tool_call_rate": round(sum(1 for s in ok if s["had_tool_calls"]) / len(ok), 2),
            }
        )
    return agg_list


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------


def render_leaderboard(aggs: list[dict], baseline_label: str, sort_key: str = "latency") -> str:
    """Render a speed-leaderboard table as a string."""

    def sort_val(a: dict):
        if a.get("skipped") or a["n_ok"] == 0:
            return float("inf")  # failed models sort last
        if sort_key == "tps":
            return -a.get("tps_mean", 0)
        return a.get("latency_p50", float("inf"))

    baseline_p50 = None
    for a in aggs:
        if a["entry"].get("label") == baseline_label:
            baseline_p50 = a.get("latency_p50")
            break

    sorted_aggs = sorted(aggs, key=sort_val)

    # Header
    hdr = (
        f"{'Model':<28} {'OK%':>5} {'n':>3} "
        f"{'Lat mean':>9} {'Lat p50':>9} {'Lat p95':>9} "
        f"{'Tok/s':>7} {'In tok':>7} {'Out tok':>7} {'Reas':>5} "
        f"{'Reply':>5} {'Tool%':>5}  {'vs base'}"
    )
    sep = "─" * len(hdr)

    rows = [sep, hdr, sep]

    for a in sorted_aggs:
        label = a["entry"]["label"]
        is_baseline = label == baseline_label

        if a.get("skipped") or a["n_ok"] == 0:
            err_msg = next(iter(a.get("errors", {})), "unknown")
            mark = " ◄" if is_baseline else ""
            rows.append(
                f"{label:<28} {'  0%':>5} {a['n_fail']:>3} "
                f"{'—':>9} {'—':>9} {'—':>9} "
                f"{'—':>7} {'—':>7} {'—':>7} {'—':>5} "
                f"{'—':>5} {'—':>5}  "
                f"ALL RUNS FAILED ({err_msg[:50]}){mark}"
            )
            continue

        ok_pct = f"{a['success_rate'] * 100:.0f}%"
        n = a["n_ok"]
        lat_mean = f"{a['latency_mean']:.2f}s"
        lat_p50 = f"{a['latency_p50']:.2f}s"
        lat_p95 = f"{a['latency_p95']:.2f}s"
        tps = f"{a['tps_mean']:.0f}" if a["tps_mean"] else "—"
        in_tok = f"{a['prompt_tokens_mean']:.0f}"
        out_tok = f"{a['completion_tokens_mean']:.0f}"
        reas = f"{a['reasoning_tokens_mean']:.0f}"
        reply = f"{a['reply_chars_mean']:.0f}"
        tool = f"{a['tool_call_rate'] * 100:.0f}%"

        # vs baseline ratio
        if is_baseline or baseline_p50 is None or baseline_p50 == 0:
            vs = "baseline" if is_baseline else "—"
        else:
            ratio = a["latency_p50"] / baseline_p50
            if ratio < 0.98:
                vs = f"{ratio:.2f}× faster"
            elif ratio > 1.02:
                vs = f"{ratio:.2f}× slower"
            else:
                vs = f"{ratio:.2f}× ~same"

        mark = " ◄" if is_baseline else ""
        rows.append(
            f"{label:<28} {ok_pct:>5} {n:>3} "
            f"{lat_mean:>9} {lat_p50:>9} {lat_p95:>9} "
            f"{tps:>7} {in_tok:>7} {out_tok:>7} {reas:>5} "
            f"{reply:>5} {tool:>5}  {vs}{mark}"
        )

    rows.append(sep)
    return "\n".join(rows)


def write_artifact(aggs: list[dict], meta: dict, outdir: Path) -> Path:
    """Write JSON artifact with all raw samples + aggregates."""
    outdir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = outdir / f"bench_{ts}.json"

    payload = {"meta": meta, "models": []}
    for a in aggs:
        model_payload = {
            "entry": a["entry"],
            "success_rate": a["success_rate"],
            "n_ok": a["n_ok"],
            "n_fail": a["n_fail"],
            "errors": a["errors"],
        }
        if a.get("skipped") or a["n_ok"] == 0:
            model_payload["skipped"] = True
        else:
            model_payload.update(
                {
                    "latency": {
                        "mean_s": a["latency_mean"],
                        "p50_s": a["latency_p50"],
                        "p95_s": a["latency_p95"],
                        "max_s": a["latency_max"],
                    },
                    "prompt_tokens_mean": a["prompt_tokens_mean"],
                    "completion_tokens_mean": a["completion_tokens_mean"],
                    "reasoning_tokens_mean": a["reasoning_tokens_mean"],
                    "tps_mean": a["tps_mean"],
                    "reply_chars_mean": a["reply_chars_mean"],
                    "tool_call_rate": a["tool_call_rate"],
                }
            )
        # Include raw samples
        if "samples" in a:
            model_payload["samples"] = [
                {
                    k: v
                    for k, v in s.items()
                    if k
                    in (
                        "prompt_idx",
                        "latency_s",
                        "prompt_tokens",
                        "completion_tokens",
                        "total_tokens",
                        "reasoning_tokens",
                        "reply_chars",
                        "had_tool_calls",
                        "success",
                        "error",
                    )
                }
                for s in a["samples"]
            ]
        payload["models"].append(model_payload)

    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Speed benchmark: LLM models for VFIC chatbot")
    p.add_argument(
        "--models", type=str, default="", help="Comma-separated labels to test (default: all)"
    )
    p.add_argument(
        "--add",
        type=str,
        action="append",
        default=[],
        dest="adds",
        help="Quick-add a model: nvidia/nemotron-3-nano-30b-a3b (auto-detect provider by '/' → openrouter)",
    )
    p.add_argument(
        "--runs", type=int, default=None, help=f"Override RUNS_PER_PROMPT ({RUNS_PER_PROMPT})"
    )
    p.add_argument("--warmup", type=int, default=None, help=f"Override WARMUP_RUNS ({WARMUP_RUNS})")
    p.add_argument("--no-tools", action="store_true", help="Skip binding tool schemas")
    p.add_argument(
        "--sort",
        choices=["latency", "tps"],
        default="latency",
        help="Table sort key (default: latency)",
    )
    p.add_argument("--no-json", action="store_true", help="Skip writing JSON artifact")
    return p.parse_args(argv)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def main() -> None:
    global WARMUP_RUNS, RUNS_PER_PROMPT, BIND_TOOLS

    args = parse_args()

    # Apply CLI overrides
    if args.runs is not None:
        RUNS_PER_PROMPT = args.runs
    if args.warmup is not None:
        WARMUP_RUNS = args.warmup
    if args.no_tools:
        BIND_TOOLS = False

    # Build model list from array + --add entries
    entries = list(MODEL_ENTRIES)
    for add_spec in args.adds:
        if "/" in add_spec:
            provider = "openrouter"
        else:
            provider = "minimax"
        label = add_spec.rsplit("/", 1)[-1]
        entries.append({"label": label, "provider": provider, "model": add_spec})

    # Filter by --models
    if args.models:
        want = set(args.models.split(","))
        entries = [e for e in entries if e["label"] in want]

    if not entries:
        print("No models to benchmark. Edit MODEL_ENTRIES or use --add.")
        sys.exit(1)

    # Find baseline
    baseline_label = None
    for e in entries:
        if e.get("baseline"):
            baseline_label = e["label"]
            break
    if baseline_label is None and entries:
        baseline_label = entries[0]["label"]

    # Load settings (pydantic reads backend/.env automatically)
    from app.core.config import get_settings

    settings = get_settings()

    # Load real production workload
    from app.graph.prompts import AGENT_SYSTEM_PROMPT

    tool_schemas = None
    if BIND_TOOLS:
        from app.graph.schemas import TOOL_SCHEMAS

        tool_schemas = TOOL_SCHEMAS

    print(f"{'=' * 90}")
    print("  VFIC Chatbot — Speed Benchmark")
    print(f"{'=' * 90}")
    print(f"  Baseline     : {baseline_label}")
    print(f"  Models       : {[e['label'] for e in entries]}")
    print(f"  Prompts      : {len(PROMPTS)}")
    print(f"  Runs/prompt  : {RUNS_PER_PROMPT} (+ {WARMUP_RUNS} warmup)")
    print(f"  Bind tools   : {BIND_TOOLS}")
    print(f"  Temperature  : {TEMPERATURE}")
    print(f"  Timeout      : {TIMEOUT_S}s")
    print(f"  Total calls  : ~{len(entries) * (WARMUP_RUNS + RUNS_PER_PROMPT * len(PROMPTS))}")
    print(f"{'=' * 90}")
    print()

    t_total_start = time.monotonic()

    # Run sequentially per model
    results: list[dict] = []
    for entry in entries:
        label = entry["label"]
        print(f"  [{label}] benchmarking", end="", flush=True)
        try:
            r = await bench_one_model(entry, AGENT_SYSTEM_PROMPT, settings, tool_schemas)
            ok = r["n_ok"]
            fail = r["n_fail"]
            total = ok + fail
            print(f" ... {ok}/{total} OK", flush=True)
            results.append(r)
        except Exception as exc:
            print(f" ... FAILED ({type(exc).__name__}: {exc})", flush=True)
            results.append(
                {
                    "entry": entry,
                    "success_rate": 0.0,
                    "n_ok": 0,
                    "n_fail": 0,
                    "errors": {str(exc): 1},
                    "samples": [],
                    "skipped": True,
                }
            )

    total_elapsed = time.monotonic() - t_total_start

    # Aggregate
    aggs = aggregate(results)

    # Print leaderboard
    print()
    print(render_leaderboard(aggs, baseline_label, sort_key=args.sort))
    print()

    # Write JSON artifact
    if not args.no_json:
        outdir = Path(__file__).resolve().parent / "bench_out"
        artifact = write_artifact(
            aggs,
            {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "bind_tools": BIND_TOOLS,
                "warmup_runs": WARMUP_RUNS,
                "runs_per_prompt": RUNS_PER_PROMPT,
                "temperature": TEMPERATURE,
                "timeout_s": TIMEOUT_S,
                "n_prompts": len(PROMPTS),
                "baseline_label": baseline_label,
                "sort_key": args.sort,
            },
            outdir,
        )
        print(f"  Artifact : {artifact}")

    print(f"  Wall time: {total_elapsed:.1f}s")
    print()


if __name__ == "__main__":
    asyncio.run(main())
