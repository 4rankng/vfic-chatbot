"""Typed active-opportunity lookup used for candidate-facing vacancy claims."""

from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Literal

from app.core.text import normalize_vietnamese_text

ActiveJobLookupStatus = Literal["matched", "no_match", "catalog_empty", "unavailable"]

SortBy = Literal["updated_at", "salary_desc", "salary_asc"]

_IDENTITY_FUZZY_MIN_LENGTH = 5
_IDENTITY_FUZZY_THRESHOLD = 0.86
_MAX_RESULTS = 10


@dataclass(frozen=True)
class ActiveJob:
    """Candidate-visible facts for one open job or ready single-page project."""

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


def _filter_terms(value: str | None) -> tuple[str, ...]:
    """Normalize an already-interpreted semantic filter into whole-word terms."""
    return tuple(dict.fromkeys(re.findall(r"[a-z0-9]+", normalize_vietnamese_text(value or ""))))


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


def _matches_filter(
    terms: tuple[str, ...],
    fields: tuple[str, ...],
    *,
    allow_identity_typo: bool = False,
) -> bool:
    if not terms:
        return True
    tokens = set().union(*(_field_search_tokens(field) for field in fields if field))
    return all(
        term in tokens or (allow_identity_typo and _matches_identity_typo(term, tokens))
        for term in terms
    )


def select_matching_active_jobs(
    jobs: list[ActiveJob],
    *,
    role: str | None = None,
    company: str | None = None,
    location: str | None = None,
    top_k: int = 3,
    sort_by: SortBy | None = None,
) -> ActiveJobLookup:
    """Apply explicit semantic filters to a scoped ACTIVE-job catalog.

    The caller, normally the LLM tool dispatcher, owns interpretation of candidate
    wording. This function only compares supplied role/company/location values with
    their corresponding structured fields; it has no conversational stopword list.

    ``sort_by`` optionally reorders matches: ``salary_desc`` / ``salary_asc`` rank by
    the highest available salary figure (``salary_max`` with ``salary_min`` fallback),
    so DIRECT_CONTEXT jobs and structured Job rows sort uniformly. Jobs with no
    salary always sort last (stable by title) so they remain visible rather than
    disappearing from a bounded ``top_k`` window.
    """
    if not jobs:
        return ActiveJobLookup("catalog_empty")

    role_terms = _filter_terms(role)
    company_terms = _filter_terms(company)
    location_terms = _filter_terms(location)
    limit = max(1, min(top_k, _MAX_RESULTS))

    matches: list[ActiveJob] = []
    for job in jobs:
        company_fields = (
            job.company_name,
            *job.company_aliases,
            job.factory_name,
            job.project_name,
            job.project_slug,
        )
        location_fields = (job.province, job.district, job.address)
        if (
            _matches_filter(role_terms, (job.title,))
            and _matches_filter(company_terms, company_fields, allow_identity_typo=True)
            and _matches_filter(location_terms, location_fields, allow_identity_typo=True)
        ):
            matches.append(job)
    if sort_by in {"salary_desc", "salary_asc"}:
        matches.sort(
            key=lambda job: _salary_sort_key(
                job,
                descending=sort_by == "salary_desc",
            ),
        )
    return (
        ActiveJobLookup("matched", tuple(matches[:limit]))
        if matches
        else ActiveJobLookup("no_match")
    )


def _salary_sort_key(job: ActiveJob, *, descending: bool) -> tuple[bool, float, str]:
    """Return a deterministic key that always places unknown salary last.

    Uses ``salary_max`` when present, falling back to ``salary_min``. Direction
    affects only the numeric component; missing salaries remain last for both
    ascending and descending requests.
    """
    magnitude = job.salary_max if job.salary_max is not None else job.salary_min
    numeric = float(magnitude or 0)
    return magnitude is None, -numeric if descending else numeric, job.title.casefold()
