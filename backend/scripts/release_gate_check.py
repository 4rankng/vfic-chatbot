#!/usr/bin/env python3
"""Run the release gate against local SLOs and a checked golden-results artifact."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import get_settings  # noqa: E402
from app.core.db import async_session  # noqa: E402
from app.services.release_gate import GoldenResultsError, extract_golden_pass_rate, evaluate_release_gate  # noqa: E402


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--golden-results",
        type=Path,
        help="Path to the golden-results JSON payload with a pass rate.",
    )
    parser.add_argument(
        "--window-hours",
        type=int,
        default=24,
        help="SLO aggregation window in hours.",
    )
    return parser


def _load_golden_pass_rate(path: Path) -> float:
    if not path.is_file():
        raise GoldenResultsError(f"golden results file not found: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise GoldenResultsError(f"golden results JSON is invalid: {exc}") from exc
    if not isinstance(payload, dict):
        raise GoldenResultsError("golden results JSON must be an object")
    return extract_golden_pass_rate(payload)


class _NullAsyncSession:
    async def __aenter__(self):
        return None

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None


async def _run(args: argparse.Namespace) -> int:
    settings = get_settings()
    if args.window_hours <= 0:
        print("release gate blocked: window_hours must be greater than zero", file=sys.stderr)
        return 1

    golden_pass_rate: float | None = None
    if settings.release_gate_correctness_enabled:
        if args.golden_results is None:
            print(
                "release gate blocked: --golden-results is required when correctness is enabled",
                file=sys.stderr,
            )
            return 1
        try:
            golden_pass_rate = _load_golden_pass_rate(args.golden_results)
        except (GoldenResultsError, OSError) as exc:
            print(f"release gate blocked: {exc}", file=sys.stderr)
            return 1

    session_factory = async_session if settings.release_gate_latency_slo_enabled else _NullAsyncSession
    try:
        async with session_factory() as db:
            result = await evaluate_release_gate(
                db,
                settings=settings,
                golden_pass_rate=golden_pass_rate,
                window_hours=args.window_hours,
            )
    except Exception as exc:  # noqa: BLE001 - the gate must fail closed.
        print(f"release gate blocked: unable to evaluate release metrics: {exc}", file=sys.stderr)
        return 1

    if result.passed:
        parts = ["release gate passed:"]
        if result.golden_pass_rate is not None:
            parts.append(f"golden_pass_rate_pct={result.golden_pass_rate:.1f}%")
        parts.append(f"window_hours={args.window_hours}")
        print(" ".join(parts))
        if result.not_evaluated:
            print("not evaluated:")
            for gate in result.not_evaluated:
                print(f" - {gate}: disabled by settings")
        return 0

    print("release gate blocked:")
    for failure in result.failures:
        print(f" - {failure.gate}: {failure.detail}")
    if result.not_evaluated:
        print("not evaluated:")
        for gate in result.not_evaluated:
            print(f" - {gate}: disabled by settings")
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
