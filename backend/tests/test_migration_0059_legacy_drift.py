"""Migration 0059's legacy-source drift check (OPS-32).

A legacy YAML source that happens to start with a YAML document-start marker
(``---``) used to skip the category-match check entirely, converting silently
under the wrong category. Only real markdown front-matter (``---`` +
``schema_version``) may short-circuit the check.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

_MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "alembic"
    / "versions"
    / "0059_category_markdown_source.py"
)


def _load_migration():
    spec = importlib.util.spec_from_file_location("migration_0059", _MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_doc_marker_legacy_yaml_still_goes_through_the_drift_check():
    migration = _load_migration()
    drifted = '---\ncategory: faq\nquestion: "X"\nanswer: "Y"\n'

    try:
        migration._legacy_category_matches("jobs", drifted)
    except RuntimeError as exc:
        assert "drifts" in str(exc)
    else:
        raise AssertionError("drifted doc-marker legacy YAML was accepted")


def test_doc_marker_legacy_yaml_matching_the_row_passes():
    migration = _load_migration()
    matching = '---\ncategory: jobs\ntitle: "X"\n'

    migration._legacy_category_matches("jobs", matching)


def test_converted_markdown_front_matter_short_circuits():
    migration = _load_migration()
    converted = (
        '---\nschema_version: "1.0"\ncategory: jobs\n---\n\n'
        "## jobs\n\n### record: a\ntitle: \"X\"\n"
    )

    migration._legacy_category_matches("jobs", converted)


def test_plain_legacy_yaml_drift_still_fails():
    migration = _load_migration()
    drifted = "category: faq\nquestion: X\n"

    try:
        migration._legacy_category_matches("jobs", drifted)
    except RuntimeError as exc:
        assert "drifts" in str(exc)
    else:
        raise AssertionError("drifted plain legacy YAML was accepted")
