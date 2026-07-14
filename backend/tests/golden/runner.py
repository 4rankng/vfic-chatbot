"""Golden dataset runner (Tech-Lead Directive §2.8 + §16 P3).

Loads ``dataset.yaml`` and exposes it for the runner. The runner itself
(drives each turn through the bot, evaluates assertions) is exercised in CI
in a follow-up — this module ships the loader + assertion-evaluator primitives.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

try:
    import yaml
except ImportError:  # pragma: no cover — yaml is a backend dep
    yaml = None  # type: ignore[assignment]

AssertionKind = Literal[
    "intent",
    "route",
    "no_hallucination",
    "says_dont_know",
    "latency_p95_below_ms",
    "tool_called",
]


@dataclass(frozen=True)
class GoldenTurn:
    """One golden-dataset turn + its expected assertions."""

    id: str
    category: str
    input: str
    assertions: list[dict]


@dataclass(frozen=True)
class AssertionResult:
    """The outcome of evaluating one assertion against a turn's actual result."""

    kind: str
    passed: bool
    detail: str = ""


def load_dataset(path: Path | str) -> list[GoldenTurn]:
    """Load ``dataset.yaml`` → list of GoldenTurn. Raises on malformed YAML."""
    if yaml is None:
        raise RuntimeError("PyYAML not installed; cannot load golden dataset")
    text = Path(path).read_text(encoding="utf-8")
    data = yaml.safe_load(text)
    if not isinstance(data, dict) or "turns" not in data:
        raise ValueError(f"invalid golden dataset: missing 'turns' key in {path}")
    turns: list[GoldenTurn] = []
    for t in data["turns"]:
        turns.append(
            GoldenTurn(
                id=str(t["id"]),
                category=str(t["category"]),
                input=str(t["input"]),
                assertions=list(t.get("assertions", [])),
            )
        )
    return turns


def evaluate_assertion(assertion: dict, actual: dict) -> AssertionResult:
    """Evaluate one assertion against the actual turn result.

    ``actual`` is a dict the runner produces: {intent, route, reply, latency_ms,
    said_dont_know, hallucinated, tool_called}. Each assertion kind reads the
    relevant field.
    """
    kind = assertion.get("kind")
    expected = assertion.get("value")
    if kind == "intent":
        actual_intent = actual.get("intent")
        passed = actual_intent == expected
        return AssertionResult(kind, passed, f"expected={expected} actual={actual_intent}")
    if kind == "route":
        actual_route = actual.get("route")
        passed = actual_route == expected
        return AssertionResult(kind, passed, f"expected={expected} actual={actual_route}")
    if kind == "no_hallucination":
        passed = not actual.get("hallucinated", False)
        return AssertionResult(kind, passed, f"hallucinated={actual.get('hallucinated')}")
    if kind == "says_dont_know":
        passed = bool(actual.get("said_dont_know"))
        return AssertionResult(kind, passed, f"said_dont_know={actual.get('said_dont_know')}")
    if kind == "latency_p95_below_ms":
        actual_ms = actual.get("latency_ms")
        passed = actual_ms is not None and actual_ms <= expected
        return AssertionResult(kind, passed, f"expected≤{expected}ms actual={actual_ms}ms")
    if kind == "tool_called":
        passed = actual.get("tool_called") == expected
        return AssertionResult(kind, passed, f"expected={expected} actual={actual.get('tool_called')}")
    return AssertionResult(kind or "unknown", False, f"unknown assertion kind: {kind}")
