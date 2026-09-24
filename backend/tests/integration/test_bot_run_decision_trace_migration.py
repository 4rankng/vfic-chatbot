from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration


def _load_migration():
    path = (
        Path(__file__).parents[2]
        / "alembic"
        / "versions"
        / "0051_bot_run_decision_trace.py"
    )
    spec = importlib.util.spec_from_file_location("migration_0051", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_decision_trace_migration_is_linear_and_reversible(monkeypatch) -> None:
    migration = _load_migration()
    operations: list[tuple[str, object]] = []

    monkeypatch.setattr(
        migration.op,
        "add_column",
        lambda table, column: operations.append(("add", (table, column))),
    )
    monkeypatch.setattr(
        migration.op,
        "drop_column",
        lambda table, column: operations.append(("drop", (table, column))),
    )

    migration.upgrade()
    migration.downgrade()

    assert migration.down_revision == "0050_data_ingestion_recovery"
    assert operations[0][0] == "add"
    table, column = operations[0][1]
    assert table == "bot_runs"
    assert column.name == "decision_trace"
    assert column.nullable is True
    assert operations[1] == ("drop", ("bot_runs", "decision_trace"))

