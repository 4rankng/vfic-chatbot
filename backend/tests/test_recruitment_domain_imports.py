"""Boundary checks for pure recruitment domain policies."""

from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_PREFIXES = (
    "sqlalchemy",
    "fastapi",
    "app.graph",
    "app.models",
    "app.services",
)


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            modules.add(node.module)
    return modules


def test_recruitment_opt_out_policy_domain_has_no_framework_or_adapter_imports():
    """The follow-up cadence policy went with the proactive feature.

    ``proactive_policy`` survives only for the inbound opt-out phrase list, which
    the reactive turn matches on, so it still carries the same framework-free
    guarantee the old cadence policy had.
    """
    modules = _imported_modules(ROOT / "app/recruitment/domain/proactive_policy.py")
    assert not any(module.startswith(FORBIDDEN_PREFIXES) for module in modules)


def test_the_proactive_turn_and_cadence_policy_are_gone():
    """Guards the removal: a reintroduced proactive turn must be a deliberate act.

    The cadence policy is policy-free now — the feature is gone — but a future
    "re-enable follow-up" would rebuild it here, and this test is where that has
    to show up.
    """
    assert not (ROOT / "app/recruitment/domain/proactive.py").exists()
    assert not (ROOT / "app/graph/proactive.py").exists()
    assert not (ROOT / "app/services/proactive").exists()
    assert not (ROOT / "app/workers/followup_worker.py").exists()


def test_recruitment_recommendation_domain_has_no_framework_or_adapter_imports():
    modules = _imported_modules(ROOT / "app/recruitment/domain/recommendation.py")
    assert not any(module.startswith(FORBIDDEN_PREFIXES) for module in modules)
