"""Source-level migration hygiene checks (no database required).

Guards the regression class found by the audit: a downgrade whose body is a
bare ``pass`` (or a refusing ``raise``) with no documented reason silently
reads as unfinished work, and a future engineer facing a bad deploy has to
reconstruct intent from git. Every downgrade that intentionally does nothing
must carry a greppable ``# downgrade: INTENTIONAL_NOOP`` or
``# downgrade: FORWARD_ONLY`` marker stating why, in the migration file
itself. Migrations with real inverse DDL are exempt (they explain themselves).
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

VERSIONS_DIR = Path(__file__).resolve().parents[1] / "alembic" / "versions"
MARKER_RE = re.compile(r"#\s*downgrade:\s*(INTENTIONAL_NOOP|FORWARD_ONLY)")


def _functions(module: ast.Module, name: str) -> list[ast.FunctionDef]:
    return [
        node
        for node in module.body
        if isinstance(node, ast.FunctionDef) and node.name == name
    ]


def _is_documented_noop(module: ast.Module) -> bool:
    """downgrade() whose body reduces to nothing but a docstring and ``pass``."""
    for fn in _functions(module, "downgrade"):
        body = fn.body
        if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
            body = body[1:]  # strip docstring
        if all(isinstance(stmt, ast.Pass) for stmt in body):
            return True
    return False


def _is_refusing(module: ast.Module) -> bool:
    """downgrade() whose body raises (e.g. the forward-only baseline guard)."""
    for fn in _functions(module, "downgrade"):
        if any(isinstance(stmt, ast.Raise) for stmt in fn.body):
            return True
    return False


def test_every_noop_or_refusing_downgrade_documents_its_reason() -> None:
    offenders: list[str] = []
    checked = 0
    for path in sorted(VERSIONS_DIR.glob("*.py")):
        source = path.read_text()
        module = ast.parse(source)
        if _is_documented_noop(module) or _is_refusing(module):
            checked += 1
            if not MARKER_RE.search(source):
                offenders.append(path.name)
    assert not offenders, (
        "downgrade() is a no-op or refuses, with no "
        "'# downgrade: INTENTIONAL_NOOP' / '# downgrade: FORWARD_ONLY' marker: "
        + ", ".join(offenders)
    )
    # Sanity: the rule must actually be exercised, not vacuously pass.
    assert checked >= 9, f"expected at least 9 no-op/refusing downgrades, saw {checked}"
