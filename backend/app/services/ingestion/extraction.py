"""Schema-constrained extraction (Tech-Lead Directive §9 stage 6 + §10).

Priority: deterministic → table → regex → LLM → escalate to review. This module
ships the registry + deterministic + table extractors (the cheap, reliable
paths). LLM extraction (the fallback) is a stub that raises NotImplementedError
until P2-4 wires the structured-output client.

Every extracted field carries provenance via the Evidence contract (directive §11).
Missing data → null (never inferred). Conflicts → warning (never silent pick).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from app.schemas.extraction_contracts import (
    BenefitEnvelopeData,
    Evidence,
    ExtractionEnvelope,
    FaqEnvelopeData,
    JobRequirementEnvelopeData,
    Scope,
    SourceRef,
    Validity,
    WorkingHoursEnvelopeData,
)
from app.services.ingestion.classification import SectionType


@dataclass
class ExtractedField:
    """One field extracted from a fragment, with provenance."""

    field_path: str
    value: Any
    method: str
    confidence: float
    fragment_id: int | None = None


# ─── Deterministic extractors (key-value line parsing) ───────────────────────


_KV_PATTERN = re.compile(r"^([^:]{1,64}):\s*(.+)$")


def extract_key_value_lines(text: str) -> dict[str, str]:
    """Parse 'Key: Value' lines into a dict. Deterministic, no LLM."""
    out: dict[str, str] = {}
    for line in text.split("\n"):
        m = _KV_PATTERN.match(line.strip())
        if m:
            key = m.group(1).strip().lower()
            value = m.group(2).strip()
            out[key] = value
    return out


_MONEY_PATTERN = re.compile(r"(\d[\d.,]*)\s*(VND|vnd|đồng|trieu|triệu|k)?")


def _cadence_from_source(text: str) -> str | None:
    lowered = text.lower()
    if any(item in lowered for item in ("/tháng", "mỗi tháng", "hàng tháng")):
        return "monthly"
    if any(item in lowered for item in ("/ngày", "mỗi ngày", "hàng ngày")):
        return "daily"
    if any(item in lowered for item in ("/giờ", "mỗi giờ", "hàng giờ")):
        return "hourly"
    if any(item in lowered for item in ("/năm", "mỗi năm", "hàng năm")):
        return "annual"
    if any(item in lowered for item in ("một lần", "1 lần")):
        return "one_time"
    return None


def _days_from_source(text: str) -> list[str]:
    """Return only days explicitly present in source text; never infer a workweek."""
    lowered = text.lower()
    days = [
        ("thứ 2", "MON"),
        ("thứ hai", "MON"),
        ("thứ 3", "TUE"),
        ("thứ ba", "TUE"),
        ("thứ 4", "WED"),
        ("thứ tư", "WED"),
        ("thứ 5", "THU"),
        ("thứ năm", "THU"),
        ("thứ 6", "FRI"),
        ("thứ sáu", "FRI"),
        ("thứ 7", "SAT"),
        ("thứ bảy", "SAT"),
        ("chủ nhật", "SUN"),
    ]
    result: list[str] = []
    for marker, code in days:
        if marker in lowered and code not in result:
            result.append(code)
    return result


def extract_money(text: str) -> tuple[float, str] | None:
    """Extract (amount, currency) from text. Returns None on no match."""
    m = _MONEY_PATTERN.search(text)
    if not m:
        return None
    raw_amount = m.group(1).replace(".", "").replace(",", "")
    try:
        amount = float(raw_amount)
    except ValueError:
        return None
    unit = (m.group(2) or "").lower()
    if unit in ("k",):
        amount *= 1_000
    elif unit in ("trieu", "triệu"):
        amount *= 1_000_000
    return amount, "VND"


# ─── Per-section-type extraction ─────────────────────────────────────────────


def extract_benefit(text: str, *, fragment_id: int | None = None) -> ExtractionEnvelope | None:
    """Extract a benefit from a fragment. Deterministic-first."""
    kv = extract_key_value_lines(text)
    # Look for a benefit name + value.
    name = None
    value = None
    for k, v in kv.items():
        if any(kw in k for kw in ("phụ cấp", "phuc cap", "trợ cấp", "tro cap", "hỗ trợ", "ho tro")):
            name = k
            money = extract_money(v)
            if money:
                value = money[0]
    # If no key-value structure, try inline money extraction.
    if name is None:
        money = extract_money(text)
        if money:
            value = money[0]
            name = text.strip()[:64]  # use the fragment text as the name
    if name is None or value is None:
        return None  # cannot extract deterministically
    evidence = [
        Evidence(
            field_path="data.name",
            value=name,
            source=SourceRef(fragment_id=fragment_id),
            method="regex",
            confidence=0.85,
        ),
        Evidence(
            field_path="data.value",
            value=value,
            source=SourceRef(fragment_id=fragment_id),
            method="regex",
            confidence=0.85 if value is not None else 0.5,
        ),
    ]
    cadence = _cadence_from_source(text)
    if cadence is None:
        return None
    return ExtractionEnvelope(
        schema_version="1.0",
        scope=Scope(type="global"),
        validity=Validity(),
        data=BenefitEnvelopeData(
            entity_type="benefit",
            name=name,
            category="OTHER",
            value=value,
            currency="VND" if value is not None else None,
            cadence=cadence,
        ),
        evidence=evidence,
        warnings=[],
    )


def extract_working_hours(
    text: str, *, fragment_id: int | None = None
) -> ExtractionEnvelope | None:
    """Extract working hours from a fragment. Deterministic-first."""
    # Look for "HH:MM - HH:MM" or "HH:MM đến HH:MM".
    m = re.search(r"(\d{1,2}:\d{2})\s*(?:-|đến|den|→)\s*(\d{1,2}:\d{2})", text)
    if not m:
        return None
    start_time, end_time = m.group(1), m.group(2)
    # Normalize to HH:MM:SS (the working_hours column type is TIME).
    start_time = _normalize_time_str(start_time)
    end_time = _normalize_time_str(end_time)
    crosses_midnight = _is_midnight_crossing(start_time, end_time)
    days = _days_from_source(text)
    if not days:
        return None
    return ExtractionEnvelope(
        schema_version="1.0",
        scope=Scope(type="global"),
        validity=Validity(),
        data=WorkingHoursEnvelopeData(
            entity_type="working_hours",
            schedule_type="FIXED",
            days=days,
            start_time=start_time,
            end_time=end_time,
            crosses_midnight=crosses_midnight,
        ),
        evidence=[
            Evidence(
                field_path="data.start_time",
                value=start_time,
                source=SourceRef(fragment_id=fragment_id),
                method="regex",
                confidence=0.9,
            )
        ],
    )


def extract_faq(text: str, *, fragment_id: int | None = None) -> ExtractionEnvelope | None:
    """Extract a FAQ Q&A pair. Deterministic-first (Q: / A: markers)."""
    q_match = re.search(r"(?:Q|Câu hỏi|Question)[:.]\s*(.+)", text, re.IGNORECASE)
    a_match = re.search(r"(?:A|Đáp án|Trả lời|Answer)[:.]\s*(.+)", text, re.IGNORECASE)
    if not q_match or not a_match:
        return None
    return ExtractionEnvelope(
        schema_version="1.0",
        scope=Scope(type="global"),
        validity=Validity(),
        data=FaqEnvelopeData(
            entity_type="faq",
            canonical_question=q_match.group(1).strip(),
            answer=a_match.group(1).strip(),
        ),
        evidence=[
            Evidence(
                field_path="data.canonical_question",
                value=q_match.group(1).strip(),
                source=SourceRef(fragment_id=fragment_id),
                method="regex",
                confidence=0.95,
            )
        ],
    )


def extract_job_requirement(
    text: str, *, fragment_id: int | None = None
) -> ExtractionEnvelope | None:
    """Extract a job requirement. Deterministic-first (category inference)."""
    text = text.strip()
    if not text:
        return None
    # Infer category from keywords.
    category = "other"
    if re.search(r"\d+\s*-\s*\d+\s*tuổi", text, re.IGNORECASE) or "tuổi" in text.lower():
        category = "age"
    elif re.search(r"\d+\s*năm", text, re.IGNORECASE) or "kinh nghiệm" in text.lower():
        category = "experience"
    elif "giới tính" in text.lower() or re.search(r"\bnam\b|\bnữ\b", text, re.IGNORECASE):
        category = "gender"
    return ExtractionEnvelope(
        schema_version="1.0",
        scope=Scope(type="job_posting"),
        validity=Validity(),
        data=JobRequirementEnvelopeData(
            entity_type="job_requirement",
            text=text,
            category=category,  # type: ignore[arg-type]
        ),
        evidence=[
            Evidence(
                field_path="data.text",
                value=text,
                source=SourceRef(fragment_id=fragment_id),
                method="deterministic",
                confidence=0.8,
            )
        ],
    )


def _normalize_time_str(t: str) -> str:
    """Normalize a time string to HH:MM:SS form.

    '8:00' → '08:00:00', '17:00' → '17:00:00', '06:10:00' → unchanged.
    """
    parts = t.split(":")
    if len(parts) == 2:
        h, m = parts
        return f"{int(h):02d}:{int(m):02d}:00"
    if len(parts) == 3:
        h, m, s = parts
        return f"{int(h):02d}:{int(m):02d}:{int(s):02d}"
    return t  # unrecognized; return as-is


def _is_midnight_crossing(start: str, end: str) -> bool:
    """True if end_time < start_time (lexically) — implies midnight crossing."""
    return end < start


# ─── Registry: dispatch by section_type ──────────────────────────────────────


_EXTRACTORS: dict[SectionType, Any] = {
    "benefit": extract_benefit,
    "working_hours": extract_working_hours,
    "faq": extract_faq,
    "job_requirements": extract_job_requirement,
}


def extract_for_section(
    section_type: SectionType, text: str, *, fragment_id: int | None = None
) -> ExtractionEnvelope | None:
    """Dispatch to the right extractor by section_type. Returns None when no
    deterministic extractor applies (caller escalates to LLM or review)."""
    fn = _EXTRACTORS.get(section_type)
    if fn is None:
        return None
    try:
        return fn(text, fragment_id=fragment_id)
    except Exception:  # noqa: BLE001
        return None
