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


def test_recruitment_proactive_domain_has_no_framework_or_adapter_imports():
    modules = _imported_modules(ROOT / "app/recruitment/domain/proactive.py")
    assert not any(module.startswith(FORBIDDEN_PREFIXES) for module in modules)


def test_recruitment_recommendation_domain_has_no_framework_or_adapter_imports():
    modules = _imported_modules(ROOT / "app/recruitment/domain/recommendation.py")
    assert not any(module.startswith(FORBIDDEN_PREFIXES) for module in modules)
