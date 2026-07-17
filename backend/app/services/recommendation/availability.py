"""Typed ACTIVE-job availability lookup used for candidate-facing vacancy claims."""

from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
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
        "ko",
        "la",
        "lam",
        "minh",
        "ma",
        "nao",
        "nhe",
        "nhi",
        "o",
        "phai",
        "roi",
        "sao",
        "thay",
        "toi",
        "tuyen",
        "tuyen dung",
        "ung",
        "ung tuyen",
        "viec",
        "viet",
        "vfic",
        "voi",
    }
)
_IDENTITY_FUZZY_MIN_LENGTH = 5
_IDENTITY_FUZZY_THRESHOLD = 0.86


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
    company_aliases: tuple[str, ...] = ()
    project_name: str = ""
    project_slug: str = ""
    address: str = ""
    shift: str = ""
    gender_requirement: str = ""
    age_min: int | None = None
    age_max: int | None = None
    experience_required: str = ""
    accommodation_support: bool | None = None
    meal_support: bool | None = None
    transport_support: bool | None = None
    description: str = ""
    requirements: str = ""
    benefits: str = ""


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
        if token in _QUERY_STOPWORDS or (
            len(token) < 2 and not any(char.isdigit() for char in token)
        ):
            continue
        if token not in seen:
            seen.add(token)
            terms.append(token)
    return tuple(terms)


def _field_search_tokens(value: str) -> set[str]:
    tokens = re.findall(r"[a-z0-9]+", normalize_vietnamese_text(value or ""))
    searchable = set(tokens)
    if len(tokens) >= 2:
        acronym = "".join(token[0] for token in tokens if token)
        if len(acronym) >= 2:
            searchable.add(acronym)
    return searchable


def _matches_identity_typo(term: str, identity_tokens: set[str]) -> bool:
    if len(term) < _IDENTITY_FUZZY_MIN_LENGTH:
        return False
    return any(
        len(candidate) >= _IDENTITY_FUZZY_MIN_LENGTH
        and SequenceMatcher(None, term, candidate).ratio() >= _IDENTITY_FUZZY_THRESHOLD
        for candidate in identity_tokens
    )


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
        return (
            ActiveJobLookup("matched", tuple(jobs[:top_k])) if jobs else ActiveJobLookup("no_match")
        )

    matches: list[ActiveJob] = []
    required = set(terms)
    for job in jobs:
        identity_fields = (
            job.company_name,
            *job.company_aliases,
            job.factory_name,
            job.address,
            job.province,
            job.district,
            job.project_name,
            job.project_slug,
        )
        identity_tokens = set().union(
            *(_field_search_tokens(field) for field in identity_fields if field)
        )
        job_tokens = identity_tokens | _field_search_tokens(job.title)
        if all(
            term in job_tokens or _matches_identity_typo(term, identity_tokens)
            for term in required
        ):
            matches.append(job)
    return (
        ActiveJobLookup("matched", tuple(matches[:top_k]))
        if matches
        else ActiveJobLookup("no_match")
    )
