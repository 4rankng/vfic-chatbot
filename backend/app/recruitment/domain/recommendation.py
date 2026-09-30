"""Pure recruitment matching policies: salary parsing and project fit ranking.

The matching unit is the PROJECT: the app recruits candidates FOR projects, so
salary, location and job scope ("phạm vi công việc") are project features the
candidate must be happy with — they are matching inputs and display info, never
the answer unit. ``rank_projects`` fits every active project against the
candidate's stated preferences and returns the whole ranked catalog.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from difflib import SequenceMatcher
from typing import Literal

from app.shared.domain.text import normalize_vietnamese_text

SortBy = Literal["updated_at", "salary_desc", "salary_asc", "created_at"]

_TRIEU_RE = re.compile(r"(\d[\d.]*)\s*trieu|\b(\d[\d.]*)\s*tr", re.IGNORECASE)
_NGHIN_RE = re.compile(r"(\d[\d.]*)\s*nghin|\b(\d[\d.]*)\s*k\b", re.IGNORECASE)
_PLAIN_RE = re.compile(r"(\d{6,})")
_RANGE_RE = re.compile(r"(\d[\d.]*)\s*[-–]\s*(\d[\d.]*)")
_IDENTITY_FUZZY_MIN_LENGTH = 5
_IDENTITY_FUZZY_THRESHOLD = 0.86
_SALARY_PROFILE_MARKERS = (
    "mong muon",
    "ky vong",
    "expected salary",
    "salary expectation",
    "dang nhan luong",
    "dang co thu nhap",
    "luong hien tai cua",
    "thu nhap hien tai cua",
)


def parse_salary_band(text: str | None) -> tuple[int | None, int | None]:
    """Parse free-text Vietnamese salary into a ``(min, max)`` VND/month band."""
    if not text:
        return None, None
    normalized = normalize_vietnamese_text(str(text))

    def _scale(num_str: str) -> int:
        number = float(num_str)
        if "trieu" in normalized or "tr" in normalized.split() or re.search(r"\btr\b", normalized):
            return int(number * 1_000_000)
        if "nghin" in normalized or re.search(r"\bk\b", normalized):
            return int(number * 1_000)
        if number >= 1_000_000:
            return int(number)
        return int(number * 1_000_000)

    rng = _RANGE_RE.search(normalized)
    if rng:
        try:
            low, high = _scale(rng.group(1)), _scale(rng.group(2))
        except (OverflowError, ValueError):
            return None, None
        if low > high:
            low, high = high, low
        return low, high

    match = _TRIEU_RE.search(normalized) or _NGHIN_RE.search(normalized)
    if match:
        try:
            value = _scale(next(group for group in match.groups() if group))
        except (OverflowError, ValueError):
            return None, None
        return int(value * 0.8), value

    plain = _PLAIN_RE.search(normalized)
    if plain:
        value = int(plain.group(1))
        return int(value * 0.8), value

    return None, None


def is_salary_profile_statement(text: str | None) -> bool:
    """Return true for first-person current/expected salary declarations."""
    normalized = normalize_vietnamese_text(text or "")
    return any(marker in normalized for marker in _SALARY_PROFILE_MARKERS)


@dataclass(frozen=True)
class IncomeFeatureEvidence:
    feature_key: str
    category: str
    name_vi: str
    value_text: str
    is_missing: bool = False
    needs_clarification: bool = False


@dataclass(frozen=True)
class ActiveProjectIncomeSummary:
    project_id: str
    project_slug: str
    project_name: str
    evidence: tuple[IncomeFeatureEvidence, ...] = ()


@dataclass(frozen=True)
class ProjectScopeItem:
    """One job-scope entry of a project: a display/feature item, never a job row."""

    title: str
    salary_min: int | None = None
    salary_max: int | None = None


@dataclass(frozen=True)
class ProjectFeatures:
    """Candidate-visible project facts the fit ranker orders."""

    project_id: str
    slug: str
    name: str
    company: str = ""
    factory: str = ""
    province: str = ""
    district: str = ""
    address: str = ""
    summary: str = ""
    updated_at: datetime | None = None
    salary_min: int | None = None
    salary_max: int | None = None
    scope: tuple[ProjectScopeItem, ...] = ()


@dataclass(frozen=True)
class FitDimension:
    """One stated-preference judgment: expected (candidate) vs actual (project)."""

    name: Literal["job_scope", "location", "salary", "company"]
    score: float  # 1.0 full match, 0.5 partial/unknown, 0.0 differs
    expected: str
    actual: str


@dataclass(frozen=True)
class ProjectFit:
    project: ProjectFeatures
    score: float
    dimensions: tuple[FitDimension, ...]


@dataclass(frozen=True)
class FitLookup:
    status: Literal["matched", "catalog_empty", "unavailable"]
    fits: tuple[ProjectFit, ...] = ()
    total: int = 0


def _text_overlap(query: str, target: str) -> float:
    if not query or not target:
        return 0.0
    query_terms = {word for word in normalize_vietnamese_text(query).split() if len(word) > 1}
    if not query_terms:
        return 0.0
    normalized_target = normalize_vietnamese_text(target)
    hits = sum(1 for term in query_terms if term in normalized_target)
    return hits / len(query_terms)


def _filter_terms(value: str | None) -> tuple[str, ...]:
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


def _company_fields(project: ProjectFeatures) -> tuple[str, ...]:
    return (project.name, project.company, project.factory)


def _job_scope_dimension(project: ProjectFeatures, job_scope: str) -> FitDimension:
    if not project.scope:
        return FitDimension("job_scope", 0.5, job_scope, "")
    best_overlap = 0.0
    best_title = ""
    for item in project.scope:
        overlap = _text_overlap(job_scope, item.title)
        if overlap > best_overlap:
            best_overlap = overlap
            best_title = item.title
    if best_overlap >= 0.5:
        return FitDimension("job_scope", 1.0, job_scope, best_title)
    if best_overlap > 0:
        return FitDimension("job_scope", 0.5, job_scope, best_title)
    actual = ", ".join(item.title for item in project.scope if item.title)
    return FitDimension("job_scope", 0.0, job_scope, actual)


def _location_dimension(project: ProjectFeatures, location: str) -> FitDimension:
    fields = (project.province, project.district, project.address)
    if not any(fields):
        return FitDimension("location", 0.5, location, "")
    terms = _filter_terms(location)
    tokens = set().union(*(_field_search_tokens(field) for field in fields if field))
    if any(term in tokens for term in terms):
        score = 1.0
    elif any(_matches_identity_typo(term, tokens) for term in terms):
        score = 0.5
    else:
        score = 0.0
    actual = ", ".join(part for part in (project.province, project.district) if part) or project.address
    return FitDimension("location", score, location, actual)


def _salary_dimension(project: ProjectFeatures, salary_min_vnd: int) -> FitDimension:
    expected = str(salary_min_vnd)
    if project.salary_min is None and project.salary_max is None:
        return FitDimension("salary", 0.5, expected, "")
    if project.salary_max is not None:
        if project.salary_max >= salary_min_vnd:
            score = 1.0
        elif project.salary_max >= salary_min_vnd * 0.8:
            score = 0.5
        else:
            score = 0.0
    else:
        score = 1.0 if project.salary_min >= salary_min_vnd else 0.0
    actual = "-".join(
        str(value) for value in (project.salary_min, project.salary_max) if value is not None
    )
    return FitDimension("salary", score, expected, actual)


def _project_fit(
    project: ProjectFeatures,
    *,
    job_scope: str | None,
    company: str | None,
    location: str | None,
    salary_min_vnd: int | None,
) -> ProjectFit:
    """Score only the stated preferences; a missing dimension is not a penalty."""
    dimensions: list[FitDimension] = []
    if job_scope:
        dimensions.append(_job_scope_dimension(project, job_scope))
    if location:
        dimensions.append(_location_dimension(project, location))
    if salary_min_vnd is not None:
        dimensions.append(_salary_dimension(project, salary_min_vnd))
    if company:
        # The hard filter already excluded non-matches; surviving rows satisfy it.
        dimensions.append(
            FitDimension("company", 1.0, company, project.company or project.name)
        )
    score = (
        sum(dimension.score for dimension in dimensions) / len(dimensions)
        if dimensions
        else 1.0
    )
    return ProjectFit(project=project, score=score, dimensions=tuple(dimensions))


def _salary_sort_key(
    project: ProjectFeatures, *, descending: bool
) -> tuple[bool, float, str]:
    value = project.salary_max if descending else project.salary_min
    numeric = float(value or 0)
    return value is None, -numeric if descending else numeric, project.name.casefold()


def _updated_at_sort_key(project: ProjectFeatures) -> tuple[bool, float]:
    if project.updated_at is None:
        return False, 0.0
    return True, project.updated_at.timestamp()


def rank_projects(
    projects: list[ProjectFeatures],
    *,
    job_scope: str | None = None,
    company: str | None = None,
    location: str | None = None,
    salary_min_vnd: int | None = None,
    sort_by: SortBy | None = None,
) -> FitLookup:
    """Fit every active project against the stated preferences, best fit first.

    The returned list is never capped: the answer unit is the project catalog,
    so ``total`` is the number of projects in ``fits``. A named ``company`` is a
    request, not a preference — it hard-filters the catalog; every other
    criterion only scores fit, and a low fit stays in the list with honest
    notes.
    """
    if not projects:
        return FitLookup("catalog_empty")

    job_scope = (job_scope or "").strip() or None
    company = (company or "").strip() or None
    location = (location or "").strip() or None

    candidates = projects
    company_terms = _filter_terms(company)
    if company_terms:
        candidates = [
            project
            for project in projects
            if _matches_filter(
                company_terms, _company_fields(project), allow_identity_typo=True
            )
        ]

    fits = [
        _project_fit(
            project,
            job_scope=job_scope,
            company=company,
            location=location,
            salary_min_vnd=salary_min_vnd,
        )
        for project in candidates
    ]

    if sort_by in {"salary_desc", "salary_asc"}:
        fits.sort(
            key=lambda fit: _salary_sort_key(
                fit.project, descending=sort_by == "salary_desc"
            )
        )
    elif sort_by in {"created_at", "updated_at"}:
        fits.sort(key=lambda fit: _updated_at_sort_key(fit.project), reverse=True)
    else:
        fits.sort(key=lambda fit: (-fit.score, fit.project.name.casefold()))

    return FitLookup("matched", tuple(fits), total=len(fits))
