"""search_bus_timetable: make the project-slug filter NULL-tolerant.

Revision ID: 0011_bus_search_null_slug
Revises: 0010_drop_dead_schema_objects
Create Date: 2026-06-28

WHY
---
Canonical VFIC Knowledge Markdown v1 documents are persisted by
``_persist_canonical_bus_timetable`` under ``projects.slug`` = the frontmatter
``project_slug`` (the shipped LG Display template uses ``lg-display``). But the
``search_bus_timetable`` SQL function filtered ``WHERE p.slug = p_project_slug``
and ``RetrievalRepository`` hardcoded the first arg to ``'vfic'`` -- so a
canonical-uploaded timetable (slug ``lg-display``) was unreachable: the agent's
bus query returned 0 rows. The deployment is single-tenant and the ``company``
argument already scopes the rows, so the project-slug filter is redundant.

FIX (query-side only)
---------------------
Make every ``p.slug = p_project_slug`` filter NULL-tolerant
(``(p_project_slug IS NULL OR p.slug = p_project_slug)``); the repo then passes
NULL. Three filter sites in the original body: 0001_baseline.py ~line 1195
(``base`` CTE WHERE) and ~1276 / ~1341 (``unavailable_candidates`` /
``missing_detail_candidates`` JOIN ... ON).

SOURCE OF TRUTH
---------------
The full ~440-line function body is intentionally NOT transcribed here
(transcription risk + two copies drifting apart). Instead this migration reads
the canonical body from 0001's own ``_SEARCH_BUS_TIMETABLE_SQL`` module constant
and applies a single exact ``.replace`` on the substring ``p.slug =
p_project_slug`` (all three sites share it). If 0001 ever drops that substring,
the assertion below fails loudly instead of silently shipping a stale function.
"""
from __future__ import annotations

from pathlib import Path

from alembic import op


# revision identifiers, used by Alembic.
revision = "0011_bus_search_null_slug"
down_revision = "0010_drop_dead_schema_objects"
branch_labels = None
depends_on = None


_BASELINE = Path(__file__).parent / "0001_baseline.py"
_MARKER = '_SEARCH_BUS_TIMETABLE_SQL = r"""'
_NEEDLE = "p.slug = p_project_slug"
_REPLACEMENT = "(p_project_slug is null or p.slug = p_project_slug)"


def _load_baseline_search_sql() -> str:
    """Return the verbatim ``search_bus_timetable`` DDL from 0001_baseline.py."""
    src = _BASELINE.read_text(encoding="utf-8")
    start = src.index(_MARKER) + len(_MARKER)
    end = src.index('"""', start)
    return src[start:end]


def upgrade() -> None:
    original = _load_baseline_search_sql()
    assert _NEEDLE in original, (
        "0001_baseline.py _SEARCH_BUS_TIMETABLE_SQL no longer contains "
        f"{_NEEDLE!r}; this migration's .replace is stale and must be updated."
    )
    op.execute(original.replace(_NEEDLE, _REPLACEMENT))


def downgrade() -> None:
    # Restore the original (slug-required) function body verbatim.
    op.execute(_load_baseline_search_sql())
