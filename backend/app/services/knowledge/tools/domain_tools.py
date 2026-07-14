"""Direct SQL domain tools + formatters (Tech-Lead Directive §2 Path A).

The directive's central architectural demand: bus/benefit/working-hours/job
queries hit the authoritative tables (P1-1) directly via SQL and format the
result deterministically, with ZERO LLM calls.

Each tool returns a ``ToolResult`` (typed dataclass). Each formatter renders a
``ToolResult`` to a Vietnamese string (tôi/bạn voice per persona.md). The router
(C-1) dispatches factual-intent turns to these tools instead of the RAG path.

Scope precedence (directive §7): job > location > company > global. The resolver
tries each scope level in order and returns the first non-empty result.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.provenance import (
    FaqEntry,
    JobBenefit,
    JobLocation,
    JobRequirement,
    WorkingHours,
    PublishedStatus,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ToolResult:
    """The typed result of a domain tool query.

    ``found`` is False when the authoritative tables have no matching row (the
    formatter renders a graceful "don't know" reply). ``data`` carries the
    structured rows; ``missing_fields`` records which expected fields were
    absent (for observability).
    """

    found: bool
    data: list[dict] = field(default_factory=list)
    missing_fields: list[str] = field(default_factory=list)
    scope_used: str = "global"


# ─── Scope resolver (directive §7 precedence) ────────────────────────────────


_SCOPE_PRECEDENCE = ("job_posting", "location", "company", "global")


async def _resolve_scoped_rows(
    db: AsyncSession,
    model,
    *,
    job_id: str | None = None,
    company_id: str | None = None,
    location_id: str | None = None,
    valid_today: str | None = None,
) -> tuple[list, str]:
    """Try each scope level in precedence order; return (rows, scope_used).

    Only PUBLISHED rows within validity windows are returned.
    """
    for scope in _SCOPE_PRECEDENCE:
        scope_id = {
            "job_posting": job_id,
            "location": location_id,
            "company": company_id,
            "global": None,
        }.get(scope)
        # Skip a scope level if its id is required but missing.
        if scope != "global" and not scope_id:
            continue
        stmt = select(model).where(
            model.status == PublishedStatus.PUBLISHED.value,
            model.scope_type == scope,
        )
        if scope_id:
            stmt = stmt.where(model.scope_id == str(scope_id))
        rows = (await db.execute(stmt)).scalars().all()
        if rows:
            return list(rows), scope
    return [], "global"


# ─── Tools ───────────────────────────────────────────────────────────────────


async def get_benefits(
    db: AsyncSession,
    *,
    job_id: str | None = None,
    company_id: str | None = None,
) -> ToolResult:
    """Query job_benefit for the resolved scope. Zero LLM calls."""
    rows, scope = await _resolve_scoped_rows(
        db, JobBenefit, job_id=job_id, company_id=company_id
    )
    if not rows:
        return ToolResult(found=False, scope_used=scope)
    data = [
        {
            "name": r.name,
            "category": r.category,
            "value": r.value,
            "currency": r.currency,
            "cadence": r.cadence,
            "eligibility": r.eligibility,
        }
        for r in rows
    ]
    missing = [
        f"{r['name']}.value" for r in data if r["value"] is None
    ]
    return ToolResult(found=True, data=data, missing_fields=missing, scope_used=scope)


async def get_working_hours(
    db: AsyncSession,
    *,
    job_id: str | None = None,
    company_id: str | None = None,
) -> ToolResult:
    """Query working_hours for the resolved scope."""
    rows, scope = await _resolve_scoped_rows(
        db, WorkingHours, job_id=job_id, company_id=company_id
    )
    if not rows:
        return ToolResult(found=False, scope_used=scope)
    data = [
        {
            "schedule_type": r.schedule_type,
            "days": r.days or [],
            "start_time": str(r.start_time) if r.start_time else None,
            "end_time": str(r.end_time) if r.end_time else None,
            "crosses_midnight": r.crosses_midnight,
            "breaks": r.breaks or [],
            "timezone": r.timezone,
        }
        for r in rows
    ]
    return ToolResult(found=True, data=data, scope_used=scope)


async def get_job_requirements(
    db: AsyncSession,
    *,
    job_id: str,
) -> ToolResult:
    """Query job_requirement for one job. job_id is required (requirements are per-job)."""
    rows = (
        await db.execute(
            select(JobRequirement).where(
                JobRequirement.job_id == job_id,
                JobRequirement.status == PublishedStatus.PUBLISHED.value,
            )
        )
    ).scalars().all()
    if not rows:
        return ToolResult(found=False)
    data = [
        {
            "text": r.requirement_text,
            "category": r.category,
            "is_required": r.is_required,
            "min_value": r.min_value,
            "max_value": r.max_value,
            "unit": r.unit,
        }
        for r in rows
    ]
    return ToolResult(found=True, data=data)


async def get_job_locations(db: AsyncSession, *, job_id: str) -> ToolResult:
    rows = (
        await db.execute(
            select(JobLocation).where(
                JobLocation.job_id == job_id,
                JobLocation.status == PublishedStatus.PUBLISHED.value,
            )
        )
    ).scalars().all()
    if not rows:
        return ToolResult(found=False)
    data = [
        {
            "address": r.address,
            "locality": r.locality,
            "region": r.region,
            "is_primary": r.is_primary,
        }
        for r in rows
    ]
    return ToolResult(found=True, data=data)


async def get_faq_entry(
    db: AsyncSession,
    *,
    normalized_question: str,
    job_id: str | None = None,
    company_id: str | None = None,
) -> ToolResult:
    """Exact-match FAQ lookup on the canonical normalized question."""
    rows, scope = await _resolve_scoped_rows(
        db, FaqEntry, job_id=job_id, company_id=company_id
    )
    for r in rows:
        if r.normalized_question == normalized_question:
            return ToolResult(
                found=True,
                data=[
                    {
                        "question": r.canonical_question,
                        "answer": r.answer,
                        "resolution_type": r.resolution_type,
                        "tool_name": r.tool_name,
                    }
                ],
                scope_used=scope,
            )
    return ToolResult(found=False, scope_used=scope)


# ─── Formatters (Vietnamese, tôi/bạn voice) ─────────────────────────────────


def format_benefits(result: ToolResult) -> str:
    if not result.found:
        return "Hiện tôi chưa có thông tin về phúc lợi cho vị trí này. Bạn vui lòng cho tôi biết thêm để được hỗ trợ nhé."
    lines = ["Thông tin phúc lợi cho vị trí này:"]
    for b in result.data:
        if b["value"] is not None and b["currency"]:
            lines.append(
                f"- {b['name']}: {int(b['value']):,} {b['currency']}/{b['cadence']}"
                + (f" ({b['eligibility']})" if b["eligibility"] else "")
            )
        else:
            lines.append(f"- {b['name']}" + (f" ({b['eligibility']})" if b["eligibility"] else ""))
    return "\n".join(lines)


def format_working_hours(result: ToolResult) -> str:
    if not result.found:
        return "Tôi chưa có thông tin giờ làm việc cho vị trí này. Bạn vui lòng hỏi lại sau nhé."
    wh = result.data[0]
    days = ", ".join(wh["days"]) if wh["days"] else "(chưa rõ ngày)"
    if wh["start_time"] and wh["end_time"]:
        lines = [f"Giờ làm việc: {wh['start_time']} - {wh['end_time']} ({days})."]
    else:
        lines = [f"Giờ làm việc theo ca ({days})."]
    if wh["crosses_midnight"]:
        lines.append("(Lưu ý: ca làm qua đêm.)")
    return " ".join(lines)


def format_job_requirements(result: ToolResult) -> str:
    if not result.found:
        return "Tôi chưa có thông tin yêu cầu chi tiết cho vị trí này."
    lines = ["Yêu cầu cho vị trí này:"]
    for r in result.data:
        marker = " (bắt buộc)" if r["is_required"] else " (ưu tiên)"
        lines.append(f"- {r['text']}{marker}")
    return "\n".join(lines)


def format_job_locations(result: ToolResult) -> str:
    if not result.found:
        return "Tôi chưa có thông tin địa điểm làm việc cho vị trí này."
    primary = next((loc for loc in result.data if loc["is_primary"]), result.data[0])
    parts = [primary["address"] or ""]
    if primary["locality"]:
        parts.append(primary["locality"])
    if primary["region"]:
        parts.append(primary["region"])
    return "Địa điểm làm việc: " + ", ".join(p for p in parts if p) + "."


def format_faq(result: ToolResult) -> str:
    if not result.found:
        return ""  # Router falls through to RAG when FAQ misses.
    return result.data[0]["answer"]  # Curated canonical text — sent verbatim.
