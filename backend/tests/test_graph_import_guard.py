"""Regression guard: graph runtime modules must not import persistence adapters.

The designated compatibility composition root is ``graph/factories.py``.
Every other graph module must consume inward Protocol/value contracts and
graph-local policy only; imports nested in functions are violations too.
"""

from __future__ import annotations

import ast
import pathlib

_GRAPH_DIR = pathlib.Path(__file__).resolve().parent.parent / "app" / "graph"


def _concrete_imports(path: pathlib.Path) -> list[str]:
    tree = ast.parse(path.read_text())
    offenders: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith(
            ("app.models", "app.services")
        ):
            names = ", ".join(alias.name for alias in node.names)
            offenders.append(f"from {node.module} import {names}")
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith(("app.models", "app.services")):
                    offenders.append(f"import {alias.name}")
    return offenders


def test_graph_runtime_modules_have_no_concrete_imports() -> None:
    offenders: dict[str, list[str]] = {}
    for path in sorted(_GRAPH_DIR.glob("*.py")):
        if path.name == "factories.py":
            continue
        bad = _concrete_imports(path)
        if bad:
            offenders[path.name] = bad

    assert not offenders, (
        "graph runtime modules must depend on ports/values; concrete model or "
        f"service imports belong in the designated composition root: {offenders}"
    )


def test_guard_detects_nested_model_and_service_imports(tmp_path) -> None:
    candidate = tmp_path / "candidate.py"
    candidate.write_text(
        "def load():\n"
        "    from app.models.conversation import Message\n"
        "    from app.services.lead import LeadService\n"
        "    return Message, LeadService\n"
    )

    assert _concrete_imports(candidate) == [
        "from app.models.conversation import Message",
        "from app.services.lead import LeadService",
    ]
