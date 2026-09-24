"""Drop dead schema objects (unused since the rewrite / a later refactor).

Removes four objects a full audit (live columns vs ORM models vs code references) confirmed
are unreferenced:

  * ``documents`` VIEW — a compat shim created in 0001 so the verbatim
    ``rebuild_bus_timetable_from_documents()`` PL/pgSQL could read a unified document row.
    That function was dropped in 0008 (superseded by the pure-Python parser in
    ``app.services.knowledge.bus_timetable``); nothing reads the view anymore.
  * ``system_settings`` — legacy key/value seed table; no app code, API, or frontend reads it.
  * ``outbound_messages`` — table + its ORM model ``OutboundMessage``. The model is defined
    and exported but never imported/queried by any service, repository, or worker. Outbound
    sends are persisted on ``messages`` (``delivery_status``), not here.
  * ``bus_stops_route_idx`` — duplicates the ``UNIQUE bus_stops_route_id_stop_order_key``
    index on the same ``(route_id, stop_order)`` columns.

Forward-only (precedent: 0008). The system is pre-launch, so there is no live data to
preserve. The ORM model + conftest TRUNCATE entry are removed in the same change.

Revision ID: 0010_drop_dead_schema_objects
Revises: 0009_feature_catalog_active
Create Date: 2026-06-28
"""
from alembic import op

# revision identifiers, used by Alembic.
revision = "0010_drop_dead_schema_objects"
down_revision = "0009_feature_catalog_active"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # View first — it depends on knowledge_documents. Then tables (index on
    # outbound_messages drops with the table via CASCADE); the standalone duplicate
    # index on the live bus_stops table needs an explicit DROP INDEX.
    op.execute("DROP VIEW IF EXISTS public.documents")
    op.execute("DROP TABLE IF EXISTS public.system_settings")
    op.execute("DROP TABLE IF EXISTS public.outbound_messages")
    op.execute("DROP INDEX IF EXISTS public.bus_stops_route_idx")


def downgrade() -> None:
    # downgrade: FORWARD_ONLY — the objects were confirmed dead by a full
    # audit (live columns vs ORM vs code references) and intentionally removed;
    # to restore any of them, recover the DDL from git history
    # (0001_baseline.py created the tables/view/index).
    pass
