"""Section classification for ingestion (Tech-Lead Directive §9 stage 5).

A single document may contain multiple knowledge types (FAQ + bus + benefits +
requirements). Each fragment is classified independently into a section_type.
Deterministic-first (keyword/regex rules); LLM-fallback only when rules are
uncertain (deferred to P2-4 — this module ships the rule layer).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

SectionType = Literal[
    "faq",
    "bus_timetable",
    "benefit",
    "working_hours",
    "job_requirements",
    "salary",
    "location",
    "application_process",
    "general_policy",
    "unknown",
]


@dataclass(frozen=True)
class Classification:
    """The result of classifying one fragment."""

    section_type: SectionType
    confidence: float
    method: str  # "rule" | "heading_inheritance" | "unknown"
    matched_keywords: list[str]


# Vietnamese keyword/regex rules per section_type. Includes diacritic + accent-
# stripped variants so "xe dua rước" matches "xe đưa rước".
_RULES: dict[SectionType, list[str]] = {
    "bus_timetable": [
        "xe đưa rước",
        "xe dua ruoc",
        "tuyến bus",
        "tuyen bus",
        "đón",
        "don",
        "b03",
        "b07",
    ],
    "benefit": [
        "phúc lợi",
        "phuc lo",
        "phụ cấp",
        "phu cap",
        "trợ cấp",
        "tro cap",
        "bảo hiểm",
        "bao hiem",
    ],
    "working_hours": [
        "giờ làm",
        "gio lam",
        "ca làm",
        "ca lam",
        "ca sáng",
        "ca sang",
        "ca chiều",
        "ca chieu",
    ],
    "job_requirements": [
        "yêu cầu",
        "yeu cau",
        "tiêu chuẩn",
        "tieu chuan",
        "CCCD",
        "cmnd",
        "tuổi",
        "tuoi",
    ],
    "salary": ["lương", "luong", "mức lương", "muc luong", "thu nhập", "thu nhap"],
    "location": [
        "địa chỉ",
        "dia chi",
        "khu công nghiệp",
        "khu cong nghiep",
        "kcn",
        "nhà máy",
        "nha may",
    ],
    "application_process": [
        "hồ sơ",
        "ho so",
        "ứng tuyển",
        "ung tuyen",
        "đăng ký",
        "dang ky",
        "cách ứng tuyển",
    ],
    "faq": ["câu hỏi", "cau hoi", "q&a", "faq", "thường gặp", "thuong gap"],
    "general_policy": ["chính sách", "chinh sach", "nội quy", "noi quy", "quy định", "quy dinh"],
}

# Compile a single combined regex per section_type for efficiency.
_COMPILED: dict[SectionType, re.Pattern] = {
    section: re.compile("|".join(re.escape(k) for k in keywords), re.IGNORECASE)
    for section, keywords in _RULES.items()
}


def classify_fragment(text: str, *, heading_context: SectionType | None = None) -> Classification:
    """Classify one fragment by keyword rules.

    ``heading_context`` lets a fragment inherit its section's type when no rule
    matches (e.g. everything under a "Phúc lợi" heading is a benefit). Returns
    ``unknown`` when no rule matches AND no heading context is set.
    """
    matched: list[str] = []
    best_section: SectionType = "unknown"
    best_count = 0
    for section, pattern in _COMPILED.items():
        hits = pattern.findall(text)
        if hits:
            # Count distinct matched keywords.
            unique_hits = list({h.lower() for h in hits})
            if len(unique_hits) > best_count:
                best_count = len(unique_hits)
                best_section = section
                matched = unique_hits
    if best_section != "unknown":
        return Classification(
            section_type=best_section,
            confidence=min(0.99, 0.6 + 0.1 * best_count),
            method="rule",
            matched_keywords=matched,
        )
    # Heading inheritance fallback.
    if heading_context is not None:
        return Classification(
            section_type=heading_context,
            confidence=0.5,
            method="heading_inheritance",
            matched_keywords=[],
        )
    return Classification(
        section_type="unknown", confidence=0.0, method="unknown", matched_keywords=[]
    )


def classify_fragments(
    fragments: list[str],
) -> list[Classification]:
    """Classify many fragments. Heading inheritance uses the most recent
    confidently-classified fragment as the context for subsequent unknowns."""
    out: list[Classification] = []
    current_heading: SectionType | None = None
    for frag in fragments:
        cls = classify_fragment(frag, heading_context=current_heading)
        if cls.method == "rule" and cls.confidence >= 0.7:
            current_heading = cls.section_type
        out.append(cls)
    return out
