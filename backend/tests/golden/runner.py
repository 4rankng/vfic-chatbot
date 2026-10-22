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
    # Trust post-mortem 2026-10-21 (user Toàn, unfollowed): the four failure
    # classes below gate the new deterministic guards. ``escalates_to_human``
    # also pins the hotline digits in the reply; ``stops_after_phone`` reads
    # the post-phone STOP flags; ``identity_honest`` reads the honesty flags;
    # ``no_standing_pitch`` asserts the standing-only/unparsed exclusion;
    # ``no_repetition`` asserts the repeat detector verdict on the turn.
    "escalates_to_human",
    "stops_after_phone",
    "identity_honest",
    "no_standing_pitch",
    "no_repetition",
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
    if kind == "escalates_to_human":
        escalated = bool(actual.get("escalated"))
        reply = str(actual.get("reply") or "")
        # The owner-approved handoff must carry the hotline digits and no
        # follow-up question (exactly one reply, interrogate ends).
        has_hotline = "1800 7228" in reply
        has_question = "?" in reply or "？" in reply
        passed = escalated and has_hotline and not has_question
        return AssertionResult(
            kind,
            passed,
            f"escalated={escalated} hotline_in_reply={has_hotline} question_in_reply={has_question}",
        )
    if kind == "stops_after_phone":
        passed = bool(actual.get("stopped_after_phone")) and not bool(
            actual.get("asked_screening_question")
        )
        return AssertionResult(
            kind,
            passed,
            f"stopped={actual.get('stopped_after_phone')} "
            f"asked_question={actual.get('asked_screening_question')}",
        )
    if kind == "identity_honest":
        passed = bool(actual.get("identity_honest")) and not bool(
            actual.get("claimed_human")
        )
        return AssertionResult(
            kind,
            passed,
            f"identity_honest={actual.get('identity_honest')} "
            f"claimed_human={actual.get('claimed_human')}",
        )
    if kind == "no_standing_pitch":
        passed = not bool(actual.get("pitched_standing_or_unknown"))
        return AssertionResult(
            kind,
            passed,
            f"pitched_standing_or_unknown={actual.get('pitched_standing_or_unknown')}",
        )
    if kind == "no_repetition":
        passed = not bool(actual.get("repeated_prior_block"))
        return AssertionResult(
            kind, passed, f"repeated_prior_block={actual.get('repeated_prior_block')}"
        )
    return AssertionResult(kind or "unknown", False, f"unknown assertion kind: {kind}")
