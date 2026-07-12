"""Regression guard: the graph brain must not import concrete service modules.

The graph <-> services cycle was broken by depending on Protocol ports
(:mod:`app.graph.ports`) wired through :class:`GraphDeps`, with
:func:`app.graph.factories.build_deps` as the single composition root. The
concrete services are constructed there with **function-level** (lazy) imports.

A future *top-level* ``from app.services...`` added to any graph module would
re-introduce a boot-time ``ImportError`` (services import graph utilities, so the
edge must stay lazy / absent). This guard parses each graph module's source and
fails fast if a top-level services import appears — function-level imports are
still allowed, so the composition root keeps working.
"""

from __future__ import annotations

import ast
import pathlib

_GRAPH_DIR = pathlib.Path(__file__).resolve().parent.parent / "app" / "graph"


def _top_level_services_imports(path: pathlib.Path) -> list[str]:
    tree = ast.parse(path.read_text())
    offenders: list[str] = []
    # `tree.body` is module-top-level only; imports nested inside functions live
    # in their own FunctionDef bodies and are intentionally not flagged here.
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("app.services"):
            names = ", ".join(alias.name for alias in node.names)
            offenders.append(f"from {node.module} import {names}")
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("app.services"):
                    offenders.append(f"import {alias.name}")
    return offenders


def test_graph_modules_have_no_top_level_service_imports() -> None:
    offenders: dict[str, list[str]] = {}
    for path in sorted(_GRAPH_DIR.glob("*.py")):
        bad = _top_level_services_imports(path)
        if bad:
            offenders[path.name] = bad

    assert not offenders, (
        "graph modules must depend on ports, not concrete services — a top-level "
        f"app.services import re-introduces the graph<->services cycle: {offenders}"
    )
