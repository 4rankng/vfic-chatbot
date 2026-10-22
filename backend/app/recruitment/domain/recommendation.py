"""Pure recruitment matching policies: salary parsing and project fit ranking.

The matching unit is the PROJECT: the app recruits candidates FOR projects, so
salary, location and job scope ("phạm vi công việc") are project features the
candidate must be happy with — they are matching inputs and display info, never
the answer unit. ``rank_projects`` fits every active project against the
candidate's stated preferences and returns the whole ranked catalog.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, replace
from datetime import datetime
from difflib import SequenceMatcher
from typing import Literal

from app.shared.domain.text import normalize_vietnamese_text

SortBy = Literal["updated_at", "salary_desc", "salary_asc", "created_at"]

# Structured physical attributes of a job opening (Zalo post-mortem 2026-10-21:
# the bot pitched 4P Electronics "ngồi" when the plant stands its workers, and
# the contradiction cost a follower). "unknown" is a first-class value — an
# unparsed posting must NEVER be treated as satisfying a stated constraint.
Posture = Literal["seated_only", "standing_only", "mixed", "unknown"]
HeavyLifting = Literal["no", "light_under_5kg", "heavy_over_10kg", "unknown"]
HealthCert = Literal[
    "mandatory_candidate_pays", "company_sponsored", "none_initially", "unknown"
]

# Mean Earth radius in kilometres (IUGG). Used only to turn two coordinates into
# a candidate-facing "cách … km" figure, so the few-hundred-metre difference
# between this and an ellipsoidal mean is far below the precision the answer
# needs.
_EARTH_RADIUS_KM = 6371.0088

# Score nudge for the conversation channel's linked projects: breaks ties and
# orders them first without ever outranking a materially better fit (one
# dimension's honest half-match is worth 0.5). The linked set is the catalog's
# starting point, never a filter (operator directive 2026-10-07).
CHANNEL_PRIORITY_BONUS = 0.05

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
    # Structured age eligibility from the job row. Age is a top candidate
    # concern (owner scan 2026-10-08: 9% of conversations ask an age question)
    # and must be answerable from the catalog alone, not a per-project KB
    # search per turn.
    age_min: int | None = None
    age_max: int | None = None
    # Structured physical attributes from the job row (posture/heavy lifting/
    # health certificate). "unknown" mirrors the DB default: an unparsed
    # posting carries no promise either way.
    posture: str = "unknown"
    heavy_lifting: str = "unknown"
    health_cert: str = "unknown"


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
    aliases: tuple[str, ...] = ()
    # The project's geocoded work address. Both are None for a project whose
    # brief states no work address or that the geocoder could not resolve; the
    # ranker then carries no distance for it.
    latitude: float | None = None
    longitude: float | None = None
    # Project-level physical-attribute aggregates over the project's job rows
    # (card-only projects carry "unknown" — no job row, no promise). These feed
    # the HARD physical-constraint filter: a candidate who must sit is never
    # pitched a standing-only or unparsed project.
    posture: str = "unknown"
    heavy_lifting: str = "unknown"


def aggregate_posture(items: tuple[ProjectScopeItem, ...] | list[ProjectScopeItem]) -> str:
    """Roll job-row postures up to one project-level posture value.

    The safe direction is "what can this project OFFER a seated candidate":
    ``seated_only``  — every known row is seated work (unknown rows don't
                       block the project; they just aren't the pitch),
    ``standing_only``— at least one standing row and no seated/mixed row,
    ``mixed``        — the project offers both seated and standing work,
    ``unknown``      — nothing known at all (never satisfies a constraint).
    """
    known = {item.posture for item in items or ()} - {"unknown"}
    if not known:
        return "unknown"
    seated_known = bool(known & {"seated_only", "mixed"})
    standing_known = "standing_only" in known or "mixed" in known
    if seated_known and standing_known:
        return "mixed"
    if seated_known:
        return "seated_only"
    if standing_known:
        return "standing_only"
    return "unknown"


def aggregate_heavy_lifting(
    items: tuple[ProjectScopeItem, ...] | list[ProjectScopeItem],
) -> str:
    """Roll job-row lifting classes up to the project's lightest known offer.

    A project PASSES a "no heavy lifting" request when at least one of its rows
    is known lifting-free; the aggregate therefore reports the LIGHTEST known
    class (a heavy row beside a free row still leaves the project pitchable —
    the heavy row simply isn't the pitch). Unknown rows never upgrade it.
    """
    order = {"no": 0, "light_under_5kg": 1, "heavy_over_10kg": 2}
    known = [item.heavy_lifting for item in items or () if item.heavy_lifting in order]
    if not known:
        return "unknown"
    return min(known, key=lambda value: order[value])


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
    # Straight-line distance from the candidate's stated area, present only when
    # the caller supplied an ``origin`` and this project has coordinates.
    distance_km: float | None = None


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
    return (project.name, project.company, project.factory, project.slug, *project.aliases)


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
    if terms and all(term in tokens for term in terms):
        score = 1.0
    elif any(term in tokens or _matches_identity_typo(term, tokens) for term in terms):
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


def haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Great-circle distance between two ``(lat, lng)`` pairs, in kilometres."""
    lat_a, lng_a = math.radians(a[0]), math.radians(a[1])
    lat_b, lng_b = math.radians(b[0]), math.radians(b[1])
    dlat = lat_b - lat_a
    dlng = lng_b - lng_a
    h = (
        math.sin(dlat / 2) ** 2
        + math.cos(lat_a) * math.cos(lat_b) * math.sin(dlng / 2) ** 2
    )
    return 2 * _EARTH_RADIUS_KM * math.asin(min(1.0, math.sqrt(h)))


def _distance_km(
    project: ProjectFeatures, origin: tuple[float, float] | None
) -> float | None:
    """Distance from ``origin`` to the project's work address, when both exist."""
    if origin is None or project.latitude is None or project.longitude is None:
        return None
    return haversine_km(origin, (project.latitude, project.longitude))


def _distance_sort_key(fit: ProjectFit) -> tuple[bool, float, float, str]:
    """Nearest first; a project without coordinates sorts last."""
    return (
        fit.distance_km is None,
        fit.distance_km or 0.0,
        -fit.score,
        fit.project.name.casefold(),
    )


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


def _project_posture(project: ProjectFeatures) -> str:
    """The project's effective posture: stored aggregate, else recomputed.

    The catalog repository stores the aggregate; the recompute covers rows
    built without it (tests, older call sites) from the same scope items, so
    the hard filter never silently degrades a known-seated project to
    ``unknown`` because a constructor skipped the field.
    """
    if project.posture != "unknown":
        return project.posture
    return aggregate_posture(project.scope)


def _project_heavy_lifting(project: ProjectFeatures) -> str:
    if project.heavy_lifting != "unknown":
        return project.heavy_lifting
    return aggregate_heavy_lifting(project.scope)


def rank_projects(
    projects: list[ProjectFeatures],
    *,
    job_scope: str | None = None,
    company: str | None = None,
    location: str | None = None,
    salary_min_vnd: int | None = None,
    sort_by: SortBy | None = None,
    strict_criteria: bool = False,
    origin: tuple[float, float] | None = None,
    priority_ids: frozenset[str] | None = None,
    work_posture: str | None = None,
    no_heavy_lifting: bool = False,
) -> FitLookup:
    """Fit every active project against the stated preferences, best fit first.

    The returned list is never capped: the answer unit is the project catalog,
    so ``total`` is the number of projects in ``fits``. A named ``company`` is a
    request, not a preference — it hard-filters the catalog; every other
    criterion scores fit, and a low fit stays in the list with honest notes.
    ``strict_criteria`` is for an explicit "only matching projects" request;
    every stated criterion then needs source-backed full evidence. Unknown
    values are not silently treated as matches.

    Physical constraints (``work_posture="seated"``, ``no_heavy_lifting=True``)
    are HARD filters like ``company`` — the 2026-10-21 Zalo post-mortem: the
    bot pitched a standing-only plant to a candidate who must sit, and the
    contradiction cost the follow. A seated request keeps only projects whose
    aggregate posture is ``seated_only`` or ``mixed``; ``standing_only`` and
    ``unknown`` NEVER survive to be pitched. ``no_heavy_lifting`` keeps only
    projects with a known lifting-free row.

    ``origin`` is the candidate's own ``(lat, lng)``. When given, every fit
    carries ``distance_km`` and the default (fit) order becomes nearest-first,
    with coordinate-less projects last; an explicit ``sort_by`` still wins, and
    ``origin=None`` reproduces the previous ordering exactly.
    """
    if not projects:
        return FitLookup("catalog_empty")

    job_scope = (job_scope or "").strip() or None
    company = (company or "").strip() or None
    location = (location or "").strip() or None
    seated_required = (work_posture or "").strip().casefold() == "seated"

    candidates = projects
    if no_heavy_lifting or seated_required:
        # Deterministic set logic BEFORE any scoring: excluded projects never
        # reach the payload the LLM composes from, so no prompt rule has to be
        # trusted for the promise to hold.
        candidates = [
            project
            for project in candidates
            if (
                not seated_required
                or _project_posture(project) in {"seated_only", "mixed"}
            )
            and (not no_heavy_lifting or _project_heavy_lifting(project) == "no")
        ]
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
    if priority_ids:
        # The channel's linked projects are the starting point of the catalog,
        # never its ceiling (operator directive 2026-10-07): they rank first
        # among EQUAL fits, and a 0.05 nudge breaks those ties without ever
        # outranking a materially better-fitting project (one dimension's
        # honest half-match is worth 0.5).
        fits = [
            replace(
                fit,
                score=min(1.0, fit.score + CHANNEL_PRIORITY_BONUS)
                if str(fit.project.project_id) in priority_ids
                else fit.score,
            )
            for fit in fits
        ]
    if strict_criteria:
        scope_terms = _filter_terms(job_scope)
        fits = [
            fit
            for fit in fits
            if all(dimension.score == 1.0 for dimension in fit.dimensions)
            and (
                not scope_terms
                or any(
                    _matches_filter(scope_terms, (item.title,)) for item in fit.project.scope
                )
            )
        ]

    if origin is not None:
        # Distance is additive evidence, not a filter: a far project stays in
        # the list with an honest number. Only the default fit order changes.
        fits = [replace(fit, distance_km=_distance_km(fit.project, origin)) for fit in fits]

    if sort_by in {"salary_desc", "salary_asc"}:
        fits.sort(
            key=lambda fit: _salary_sort_key(
                fit.project, descending=sort_by == "salary_desc"
            )
        )
    elif sort_by in {"created_at", "updated_at"}:
        fits.sort(key=lambda fit: _updated_at_sort_key(fit.project), reverse=True)
    elif origin is not None:
        fits.sort(key=_distance_sort_key)
    else:
        fits.sort(key=lambda fit: (-fit.score, fit.project.name.casefold()))

    return FitLookup("matched", tuple(fits), total=len(fits))
