"""Regression guard: graph runtime modules must not import persistence adapters.

The composition root is split across ``graph/factories.py`` (build_deps + LLM
builders), ``graph/adapters.py`` (port adapters), and ``graph/client_cache.py``
(process-wide LLM client cache). Those three may import concrete
``app.models`` / ``app.services`` modules, but only inside functions — an
import-time edge in any graph module is exactly the failure this guard exists
to stop. Every other graph module must consume inward Protocol/value contracts
and graph-local policy only; imports nested in functions are violations too.
"""

from __future__ import annotations

import ast
import pathlib
import sys

import pytest

_GRAPH_DIR = pathlib.Path(__file__).resolve().parent.parent / "app" / "graph"

# Modules of the composition root: the designated place where concrete
# model/service imports are wired. Listed by name so the set is deliberate.
_COMPOSITION_MODULES = ("adapters.py", "client_cache.py", "factories.py")


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


def _module_level_concrete_imports(path: pathlib.Path) -> list[str]:
    """Concrete imports executed at import time (not nested inside functions)."""
    tree = ast.parse(path.read_text())
    offenders: list[str] = []

    def import_time_nodes(node):
        # Conditional/try/class bodies execute at import time too. Only a
        # function's body is deferred until an explicit composition call.
        yield node
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            return
        for child in ast.iter_child_nodes(node):
            yield from import_time_nodes(child)

    for node in import_time_nodes(tree):
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
    for path in sorted(_GRAPH_DIR.rglob("*.py")):
        relative = path.relative_to(_GRAPH_DIR).as_posix()
        if relative in _COMPOSITION_MODULES:
            continue
        bad = _concrete_imports(path)
        if bad:
            offenders[relative] = bad

    assert not offenders, (
        "graph runtime modules must depend on ports/values; concrete model or "
        f"service imports belong in the designated composition root: {offenders}"
    )


def test_composition_modules_keep_concrete_imports_function_level() -> None:
    """The composition root may wire concrete types, but never at import time.

    ``factories.py`` used to be skipped wholesale by this guard, so nothing
    checked that its concrete imports stayed lazy. The composition modules are
    now covered with the narrower rule: function-level wiring is the design;
    a module-level import is the import-time edge the guard exists to stop.
    """
    offenders: dict[str, list[str]] = {}
    for path in sorted(_GRAPH_DIR.rglob("*.py")):
        relative = path.relative_to(_GRAPH_DIR).as_posix()
        if relative not in _COMPOSITION_MODULES:
            continue
        bad = _module_level_concrete_imports(path)
        if bad:
            offenders[relative] = bad

    assert not offenders, (
        "composition modules must import concrete models/services inside "
        f"functions, never at module level: {offenders}"
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


def test_guard_distinguishes_module_level_from_function_level(tmp_path) -> None:
    module_level = tmp_path / "module_level.py"
    module_level.write_text("from app.models.conversation import Message\n")

    function_level = tmp_path / "function_level.py"
    function_level.write_text(
        "def load():\n"
        "    from app.services.lead import LeadService\n"
        "    return LeadService\n"
    )

    assert _module_level_concrete_imports(module_level) == [
        "from app.models.conversation import Message"
    ]
    assert _module_level_concrete_imports(function_level) == []


def test_guard_covers_nested_tool_modules(tmp_path, monkeypatch) -> None:
    tools = tmp_path / "tools"
    tools.mkdir()
    (tools / "example.py").write_text("from app.services.lead import LeadService\n")
    monkeypatch.setattr(sys.modules[__name__], "_GRAPH_DIR", tmp_path)

    with pytest.raises(AssertionError, match="tools/example.py"):
        test_graph_runtime_modules_have_no_concrete_imports()


def test_guard_detects_import_time_control_flow(tmp_path) -> None:
    candidate = tmp_path / "candidate.py"
    candidate.write_text(
        "if enabled:\n"
        "    from app.models.conversation import Message\n"
        "try:\n"
        "    from app.services.lead import LeadService\n"
        "except ImportError:\n"
        "    pass\n"
        "class Adapter:\n"
        "    from app.models.lead import Lead\n"
        "    async def resolve(self):\n"
        "        from app.services.retrieval import RetrievalRepository\n"
    )

    assert _module_level_concrete_imports(candidate) == [
        "from app.models.conversation import Message",
        "from app.services.lead import LeadService",
        "from app.models.lead import Lead",
    ]
