"""Retrieval tools the agent may call (domain-split package).

  * compare_income       -> typed cross-project income evidence; the authority
                            contract lives in ``app.graph.income_contract``
  * search_user_memory   -> match_memories top-5 filtered by chat_id
  * search_knowledge     -> project-scoped semantic retrieval
  * list_active_projects -> project matching over the active catalog
  * get_project_distance -> distance from the candidate's stated place to one
                            project ("từ địa chỉ của em tới dự án X")
  * search_bus_timetable / get_product_features -> per-project structured reads

Each tool takes an injected embedder + retrieval port, so they are testable
without an LLM. STRICT rule (from the agent prompt): advise only from returned
data.

All SQL lives in ``app.services.retrieval.RetrievalRepository``; these modules
own the embedding (a graph-layer concern) + the Vietnamese formatting only.
``__init__`` re-exports the previous module-level import surface so external
callers keep using ``from app.graph.tools import X`` unchanged.
"""

from __future__ import annotations

from app.graph.embed_cache import cached_embed
from app.graph.tools._shared import _cache_digest
from app.graph.tools.catalog import (
    format_salary_range,
    get_project_distance,
    get_product_features,
    list_active_projects,
    search_bus_timetable,
)
from app.graph.tools.tingting_api import (
    confirm_tingting_otp,
    reset_tingting_password,
    send_tingting_otp,
)
from app.graph.tools.tingting_identity import verify_tingting_identity
from app.graph.tools.tingting_selfcheckin import (
    confirm_self_checkin_otp,
    send_self_checkin_otp,
    update_self_checkin,
)
from app.graph.tools.income import compare_income
from app.graph.tools.knowledge import (
    _format_knowledge_row,
    load_project_knowledge,
    search_knowledge,
)
from app.graph.tools.memory import search_user_memory

# The tool contract the router/dispatcher may call by name. No tool may
# silently disappear or rename during a refactor (F-CRIT-2 guard).
TOOLS_REGISTRY = {
    "compare_income": compare_income,
    "search_user_memory": search_user_memory,
    "search_knowledge": search_knowledge,
    "load_project_knowledge": load_project_knowledge,
    "list_active_projects": list_active_projects,
    "get_project_distance": get_project_distance,
    "search_bus_timetable": search_bus_timetable,
    "get_product_features": get_product_features,
    "verify_tingting_identity": verify_tingting_identity,
    "send_tingting_otp": send_tingting_otp,
    "confirm_tingting_otp": confirm_tingting_otp,
    "reset_tingting_password": reset_tingting_password,
    "send_self_checkin_otp": send_self_checkin_otp,
    "confirm_self_checkin_otp": confirm_self_checkin_otp,
    "update_self_checkin": update_self_checkin,
}

__all__ = [
    "TOOLS_REGISTRY",
    "compare_income",
    "format_salary_range",
    "get_product_features",
    "get_project_distance",
    "list_active_projects",
    "search_bus_timetable",
    "search_knowledge",
    "load_project_knowledge",
    "search_user_memory",
    "verify_tingting_identity",
    "send_tingting_otp",
    "confirm_tingting_otp",
    "reset_tingting_password",
    "send_self_checkin_otp",
    "confirm_self_checkin_otp",
    "update_self_checkin",
    "_cache_digest",
    "cached_embed",
    "_format_knowledge_row",
]
