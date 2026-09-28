"""Income-comparison tool: bounded cross-project income evidence.

Produces the typed verdict handed to the grounding/authority layer via
``app.graph.income_contract`` — that contract module owns the status
vocabulary, the trusted Vietnamese safe-reply texts, and the validation rules,
so the invariant exists in exactly one place. This module owns the retrieval,
evidence shaping, and target ranking only.
"""

from __future__ import annotations

import logging
from typing import cast

from app.graph.income_contract import (
    INCOME_STATUS_UNAVAILABLE,
    IncomeVerdict,
    build_income_verdict,
)
from app.graph.ports import GraphRetrievalPort
from app.graph.tools._shared import _single_line
from app.recruitment.domain.recommendation import ActiveProjectIncomeSummary
from app.shared.domain.text import normalize_vietnamese_text

logger = logging.getLogger(__name__)


_MAX_INCOME_PROJECTS = 20
_MAX_INCOME_EVIDENCE_PER_PROJECT = 5


def _income_evidence_payload(feature) -> dict[str, object]:
    return {
        "feature_key": _single_line(feature.feature_key, limit=80),
        "category": _single_line(feature.category, limit=80),
        "name_vi": _single_line(feature.name_vi, limit=60),
        "value_text": _single_line(feature.value_text, limit=190),
    }


def _project_income_payload(summary: ActiveProjectIncomeSummary) -> dict[str, object]:
    valid_evidence = [
        item
        for item in summary.evidence
        if not item.is_missing and not item.needs_clarification and item.value_text.strip()
    ]
    evidence = [
        _income_evidence_payload(item)
        for item in valid_evidence[:_MAX_INCOME_EVIDENCE_PER_PROJECT]
    ]
    return {
        "project_slug": _single_line(summary.project_slug, limit=120),
        "project_name": _single_line(summary.project_name, limit=100),
        "evidence": evidence,
    }


def _mentions_target_amount(project: dict[str, object], target_monthly_vnd: int | None) -> bool:
    """Rank literal target evidence first without deriving a compensation verdict."""
    if target_monthly_vnd is None:
        return False
    target = f"{target_monthly_vnd / 1_000_000:g}"
    # Producers always store ``name_vi``/``value_text`` string pairs under
    # ``evidence``; the dict[str, object] container is the JSON contract, so
    # narrow the read once instead of guarding every row access.
    evidence_rows = cast("list[dict[str, str]]", project.get("evidence") or [])
    for evidence in evidence_rows:
        text = normalize_vietnamese_text(str(evidence.get("value_text") or ""))
        start = 0
        while (index := text.find(target, start)) >= 0:
            before = text[index - 1] if index else " "
            after_index = index + len(target)
            after = text[after_index] if after_index < len(text) else " "
            nearby = text[index : index + 32]
            if not before.isdigit() and not after.isdigit() and (
                "trieu" in nearby or " tr" in nearby
            ):
                return True
            start = after_index
    return False


async def compare_income(
    retrieval: GraphRetrievalPort,
    *,
    target_monthly_vnd: int | None = None,
) -> IncomeVerdict:
    """Return bounded cross-project income evidence from active structured features."""
    try:
        summaries = await retrieval.income_summary_for_active_projects()
    except Exception:
        logger.warning("compare_income failed", exc_info=True)
        return build_income_verdict(
            [],
            target_monthly_vnd=target_monthly_vnd,
            status=INCOME_STATUS_UNAVAILABLE,
        )
    projects = [
        project
        for summary in summaries
        if (project := _project_income_payload(summary))["evidence"]
    ]
    projects.sort(key=lambda project: not _mentions_target_amount(project, target_monthly_vnd))
    projects = projects[:_MAX_INCOME_PROJECTS]
    return build_income_verdict(projects, target_monthly_vnd=target_monthly_vnd)
