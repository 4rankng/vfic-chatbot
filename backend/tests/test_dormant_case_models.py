"""Dormancy record for the case-management model tables.

``models/case.py`` (Case, CaseNote, CaseFollowup, CaseTagAssignment) and most
of ``models/case_workflow.py`` (CaseTagDefinition, CaseWorkflowTransition)
have no runtime reader or writer: they exist because the shipped Alembic
baseline created the tables and ``CaseWorkflowVersion`` — which IS live,
validated by the installation service and FK-targeted by revisions — shares
the module. They therefore must not be dropped in a routine cleanup.

This test records the dormancy instead of leaving it to be rediscovered: the
dormant classes may be imported by the models package itself (registration)
but by nothing else. An import appearing here means either the feature went
live (update the dormancy record) or an accidental dependency crept in.
"""

from __future__ import annotations

import ast
from pathlib import Path

APP_DIR = Path(__file__).parents[1] / "app"

# CaseWorkflowVersion is deliberately absent: it is live installation surface.
DORMANT_CASE_CLASSES = frozenset(
    {
        "Case",
        "CaseNote",
        "CaseFollowup",
        "CaseTagAssignment",
        "CaseTagDefinition",
        "CaseWorkflowTransition",
    }
)
DORMANT_MODULES = ("app.models.case", "app.models.case_workflow")


def test_dormant_case_model_classes_have_no_importer() -> None:
    offenders: list[str] = []
    for path in sorted(APP_DIR.rglob("*.py")):
        rel = path.relative_to(APP_DIR.parent)
        if str(path.relative_to(APP_DIR)).startswith(
            "models/"
        ):  # models/__init__.py registers them; the modules define them
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom):
                continue
            module = node.module or ""
            imported = {alias.name for alias in node.names}
            if module in DORMANT_MODULES and imported & DORMANT_CASE_CLASSES:
                offenders.append(f"{rel}: from {module} import {sorted(imported)}")
            elif module == "app.models" and imported & DORMANT_CASE_CLASSES:
                offenders.append(f"{rel}: from app.models import {sorted(imported)}")

    assert offenders == [], (
        "The case-management model classes are recorded as dormant (no runtime "
        "reader or writer; see models/case.py). If one just went live, move its "
        f"name out of DORMANT_CASE_CLASSES: {offenders}"
    )
