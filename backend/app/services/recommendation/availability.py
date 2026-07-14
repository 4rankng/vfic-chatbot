"""Typed ACTIVE-job availability lookup used for candidate-facing vacancy claims."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from app.core.text import normalize_vietnamese_text

ActiveJobLookupStatus = Literal["matched", "no_match", "unavailable"]

_QUERY_STOPWORDS = frozenset(
    {
        "a",
        "ah",
        "ban",
        "ben",
        "co",
        "con",
        "cua",
        "dang",
        "de",
        "dung",
        "duoc",
        "em",
        "ha",
        "hay",
        "hien",
        "khong",
        "la",
        "lam",
        "minh",
        "nao",
        "o",
        "phai",
        "toi",
        "tuyen",
        "tuyen dung",
        "ung",
        "ung tuyen",
        "viec",
        "vfic",
        "voi",
    }
)


@dataclass(frozen=True)
class ActiveJob:
    """The candidate-visible facts for one currently open posting."""

    id: str
    title: str
    company_name: str
    factory_name: str = ""
    province: str = ""
    district: str = ""
    salary_min: int | None = None
    salary_max: int | None = None
    vacancy_count: int | None = None


@dataclass(frozen=True)
class ActiveJobLookup:
    """Result of checking whether an explicit role has a current vacancy."""

    status: ActiveJobLookupStatus
    jobs: tuple[ActiveJob, ...] = ()


def vacancy_query_terms(query: str) -> tuple[str, ...]:
    """Return meaningful whole-word terms from a Vietnamese vacancy question."""
    normalized = normalize_vietnamese_text(query or "")
    tokens = re.findall(r"[a-z0-9]+", normalized)
    seen: set[str] = set()
    terms: list[str] = []
    for token in tokens:
        if token in _QUERY_STOPWORDS or (len(token) < 3 and not any(char.isdigit() for char in token)):
            continue
        if token not in seen:
            seen.add(token)
            terms.append(token)
    return tuple(terms)


def select_matching_active_jobs(
    query: str, jobs: list[ActiveJob], *, top_k: int = 3
) -> ActiveJobLookup:
    """Match only complete normalized query terms against ACTIVE job facts.

    An explicit term must match a complete token in the title/company/factory/location
    of the same job. This deliberately rejects substring matches such as ``tho`` in
    ``thong`` and never combines facts from different jobs.
    """
    terms = vacancy_query_terms(query)
    if not terms:
        return ActiveJobLookup("matched", tuple(jobs[:top_k])) if jobs else ActiveJobLookup("no_match")

    matches: list[ActiveJob] = []
    required = set(terms)
    for job in jobs:
        haystack = " ".join(
            part
            for part in (
                job.title,
                job.company_name,
                job.factory_name,
                job.province,
                job.district,
            )
            if part
        )
        job_tokens = set(re.findall(r"[a-z0-9]+", normalize_vietnamese_text(haystack)))
        if required <= job_tokens:
            matches.append(job)
    return ActiveJobLookup("matched", tuple(matches[:top_k])) if matches else ActiveJobLookup("no_match")
