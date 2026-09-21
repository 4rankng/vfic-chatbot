"""Retrieval tools the agent may call (domain-split package).

  * compare_income       -> typed cross-project income evidence; the authority
                            contract lives in ``app.graph.income_contract``
  * search_user_memory   -> match_memories top-5 filtered by chat_id
  * search_knowledge     -> project-scoped semantic retrieval
  * list_active_jobs     -> scoped ACTIVE-job evidence with explicit filters
  * list_active_projects -> the active-product catalog
  * recommend_projects / recommend_jobs -> deterministic recommendations
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

from app.graph.tools._shared import _cache_digest, _cached_embed
from app.graph.tools.catalog import (
    get_product_features,
    list_active_projects,
    recommend_projects,
    search_bus_timetable,
)
from app.graph.tools.income import compare_income
from app.graph.tools.jobs import (
    _active_job_tool_result,
    format_salary_range,
    list_active_jobs,
    recommend_jobs,
)
from app.graph.tools.knowledge import _format_knowledge_row, search_knowledge
from app.graph.tools.memory import search_user_memory

# The tool contract the router/dispatcher may call by name. No tool may
# silently disappear or rename during a refactor (F-CRIT-2 guard).
TOOLS_REGISTRY = {
    "compare_income": compare_income,
    "search_user_memory": search_user_memory,
    "search_knowledge": search_knowledge,
    "list_active_projects": list_active_projects,
    "list_active_jobs": list_active_jobs,
    "recommend_projects": recommend_projects,
    "recommend_jobs": recommend_jobs,
    "search_bus_timetable": search_bus_timetable,
    "get_product_features": get_product_features,
}

__all__ = [
    "TOOLS_REGISTRY",
    "compare_income",
    "format_salary_range",
    "get_product_features",
    "list_active_jobs",
    "list_active_projects",
    "recommend_jobs",
    "recommend_projects",
    "search_bus_timetable",
    "search_knowledge",
    "search_user_memory",
    "_active_job_tool_result",
    "_cache_digest",
    "_cached_embed",
    "_format_knowledge_row",
]
