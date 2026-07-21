"""Collection-time guard: no real PII in the committed sync fixtures.

The FAQ sheet fixtures are hand-authored stand-ins for the live LG Display
sheet — they must contain zero customer phone numbers, names, or tokens. If a
real sheet is ever curled into the repo by accident, this test fails before CI
logs can surface the leak.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "external_source_sync"

# Vietnamese mobile/landline shapes. Deliberately broad so a leaked number in
# any common formatting is caught.
_PATTERNS = [
    re.compile(r"\+84[\s-]?\d{8,10}"),
    re.compile(r"\b0\d{1,2}[\s-]?\d{3}[\s-]?\d{3,5}\b"),
    re.compile(r"\baccess_token=[A-Za-z0-9._-]+\b"),
]

# Only scan hand-authored text fixtures — never compiled Python or caches.
_TEXT_SUFFIXES = {".csv", ".html", ".htm", ".txt", ".md", ".yaml", ".yml"}


def _fixture_files() -> list[Path]:
    if not FIXTURE_DIR.exists():
        return []
    return [
        p
        for p in FIXTURE_DIR.rglob("*")
        if p.is_file()
        and p.suffix.lower() in _TEXT_SUFFIXES
        and "__pycache__" not in p.parts
    ]


def test_fixture_directory_has_files() -> None:
    """Guard against the fixture dir silently going empty (which would pass PII)."""
    assert _fixture_files(), f"expected text fixtures under {FIXTURE_DIR}"


@pytest.mark.parametrize("fixture", _fixture_files(), ids=lambda p: p.name)
def test_fixture_contains_no_pii(fixture: Path) -> None:
    content = fixture.read_text(encoding="utf-8")
    matches = [pattern.pattern for pattern in _PATTERNS if pattern.search(content)]
    assert not matches, (
        f"{fixture.name} matched PII patterns {matches}; replace any real data "
        "with synthetic placeholders (0900 000 000, Ms A, etc.)"
    )
