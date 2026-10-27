"""search_bus_timetable: resolve companies by project name, find time-less
stops, and match route names by question tokens.

Revision ID: 0079_bus_search_project_name
Revises: 0078_job_physical_attributes
Create Date: 2026-10-27

WHY (CHAT-13)
-------------
"cho hỏi dự án Lear có đưa đón không" returned 0 rows even though the project's
KB route ("Xe đưa đón") carried the four fixed stops plus the Ghi chú, so the
bot answered "tin tuyển dụng chưa ghi rõ". Three independent function-level
causes:

1. Company resolution only compared ``companies.name``/``companies.aliases``.
   The Lear company row is named "Dự án mới" (import placeholder) while the
   candidate-facing project is "Lear Cát Hải" — every agent query ("Lear",
   "Lear Cát Hải") missed. The project's own name/aliases are now matched too.
2. ``base`` required ``bs.scheduled_time is not null``. KB-imported routes
   (``category_markdown`` source) legitimately have stops without times — those
   routes were invisible to every query. The tool formatter already renders a
   missing time as "chưa có giờ trong nguồn", so the filter only hid data the
   presentation layer knows how to show.
3. ``route_match`` required the question to contain the full normalized route
   name ("xe dua don"). "có đưa đón không" contains only "dua don" — the route
   never became a direct match and its trigram similarity stays under the
   0.16 broad-match floor. Route-name tokens (length >= 3) contained in the
   question now count as a route match; the function stays bus-scoped because
   only the timetable tool calls it.

FIX (query-side only, same style as 0011)
-----------------------------------------
The canonical body lives in 0001's ``_SEARCH_BUS_TIMETABLE_SQL``; this migration
replays 0011's NULL-slug replace and then applies three exact ``.replace``
operations. Every needle is asserted so a drifted baseline fails loudly instead
of shipping a stale function.

The repository's complete-route fetch and the timetable tool formatter now also
carry ``bus_routes.notes`` (the Ghi chú) so a matched route surfaces its
conditions (see app/services/retrieval/timetable_repository.py and
app/graph/tools/catalog.py).
"""
from __future__ import annotations

from pathlib import Path

from alembic import op


revision = "0079_bus_search_project_name"
down_revision = "0078_job_physical_attributes"
branch_labels = None
depends_on = None


_BASELINE = Path(__file__).parent / "0001_baseline.py"
_MARKER = '_SEARCH_BUS_TIMETABLE_SQL = r"""'

# 0011's transformation, replayed first so the needles below match the body the
# running database actually has (baseline + NULL-tolerant slug).
_SLUG_NEEDLE = "p.slug = p_project_slug"
_SLUG_REPLACEMENT = "(p_project_slug is null or p.slug = p_project_slug)"

_COMPANY_NEEDLE = """        or exists (
          select 1
          from unnest(c.aliases) a
          where public.normalize_search_text(a) like '%' || public.normalize_search_text(p_company_query) || '%'
        )"""
_COMPANY_REPLACEMENT = """        or exists (
          select 1
          from unnest(c.aliases) a
          where public.normalize_search_text(a) like '%' || public.normalize_search_text(p_company_query) || '%'
        )
        or exists (
          select 1
          from public.projects mp
          where mp.id = c.project_id
            and (
              public.normalize_search_text(mp.name) like '%' || public.normalize_search_text(p_company_query) || '%'
              or exists (
                select 1
                from unnest(mp.aliases) mp_alias
                where public.normalize_search_text(mp_alias) like '%' || public.normalize_search_text(p_company_query) || '%'
              )
            )
        )"""

_TIME_NEEDLE = "\n      and bs.scheduled_time is not null"

_ROUTE_MATCH_NEEDLE = """      (
        base.q like '%' || public.normalize_search_text(base.route_name) || '%'
        or base.q like '%' || base.route_group_key || '%'
        or (base.loc <> '' and base.route_group_key like '%' || base.loc || '%')
      ) as route_match,"""
_ROUTE_MATCH_REPLACEMENT = """      (
        base.q like '%' || public.normalize_search_text(base.route_name) || '%'
        or base.q like '%' || base.route_group_key || '%'
        or (base.loc <> '' and base.route_group_key like '%' || base.loc || '%')
        or exists (
          select 1
          from unnest(string_to_array(public.normalize_search_text(base.route_name), ' ')) route_token
          where length(route_token) >= 3
            and position(' ' || route_token || ' ' in ' ' || base.q || ' ') > 0
        )
      ) as route_match,"""


def _baseline_search_sql() -> str:
    src = _BASELINE.read_text(encoding="utf-8")
    start = src.index(_MARKER) + len(_MARKER)
    end = src.index('"""', start)
    return src[start:end]


def _patched_search_sql() -> str:
    body = _baseline_search_sql()
    assert _SLUG_NEEDLE in body, "0011 needle missing from 0001 baseline body"
    body = body.replace(_SLUG_NEEDLE, _SLUG_REPLACEMENT)
    # The baseline body already carries this migration's transforms (fresh
    # installs run the patched constant directly); a no-op replace must not
    # double-append the project-name clause.
    assert _COMPANY_NEEDLE in body, "company-filter needle missing from baseline body"
    assert _TIME_NEEDLE in body, "scheduled_time needle missing from baseline body"
    assert _ROUTE_MATCH_NEEDLE in body, "route_match needle missing from baseline body"
    body = body.replace(_COMPANY_NEEDLE, _COMPANY_REPLACEMENT)
    body = body.replace(_TIME_NEEDLE, "")
    body = body.replace(_ROUTE_MATCH_NEEDLE, _ROUTE_MATCH_REPLACEMENT)
    return body


def upgrade() -> None:
    op.execute(_patched_search_sql())


def downgrade() -> None:
    # Restore the 0011-era body verbatim (NULL-tolerant slug, pre-CHAT-13).
    body = _baseline_search_sql()
    assert _SLUG_NEEDLE in body
    op.execute(body.replace(_SLUG_NEEDLE, _SLUG_REPLACEMENT))
