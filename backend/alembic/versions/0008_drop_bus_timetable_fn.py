"""Drop the dead rebuild_bus_timetable_from_documents() SQL function.

Revision ID: 0008_drop_bus_timetable_fn
Revises: 0007_conversation_semi_auto
Create Date: 2026-06-28
"""
from __future__ import annotations

from alembic import op

revision = "0008_drop_bus_timetable_fn"
down_revision = "0007_conversation_semi_auto"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The parser moved to pure Python (app.services.knowledge.bus_timetable); the
    # rebuild_bus_timetable(db) wrapper in repository.py no longer calls this function
    # (golden-gated to be byte-identical). Drop it so the dead 460-line PL/pgSQL cannot
    # be re-invoked. Untouched: search_bus_timetable (read path) + normalize_search_text
    # / normalize_bus_route_key (still used by search).
    op.execute("DROP FUNCTION IF EXISTS public.rebuild_bus_timetable_from_documents")


def downgrade() -> None:
    # Forward-only stack. The function is superseded by the Python port; to restore it,
    # re-run the verbatim DDL in alembic/versions/0001_baseline.py:616-1079
    # (module constant _REBUILD_BUS_TIMETABLE_SQL).
    pass
