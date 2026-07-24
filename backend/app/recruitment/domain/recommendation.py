"""Pure recommendation scoring and active-opportunity matching policies."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from difflib import SequenceMatcher
from typing import Literal

from app.shared.domain.text import normalize_vietnamese_text

ActiveJobLookupStatus = Literal["matched", "no_match", "catalog_empty", "unavailable"]
SortBy = Literal["updated_at", "salary_desc", "salary_asc", "created_at"]

_TRIEU_RE = re.compile(r"(\d[\d.]*)\s*trieu|\b(\d[\d.]*)\s*tr", re.IGNORECASE)
_NGHIN_RE = re.compile(r"(\d[\d.]*)\s*nghin|\b(\d[\d.]*)\s*k\b", re.IGNORECASE)
_PLAIN_RE = re.compile(r"(\d{6,})")
_RANGE_RE = re.compile(r"(\d[\d.]*)\s*[-–]\s*(\d[\d.]*)")
_IDENTITY_FUZZY_MIN_LENGTH = 5
_IDENTITY_FUZZY_THRESHOLD = 0.86
_MAX_RESULTS = 10
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


@dataclass(frozen=True)
class RecommendationWeights:
    """Tunable weights for the structured lead-to-job scorer."""

    title: float = 0.35
    salary: float = 0.25
    location: float = 0.20
    support: float = 0.10
    experience: float = 0.10


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


@dataclass
class LeadProfile:
    """Candidate signals used by the structured ranker."""

    desired_job: str = ""
    living_area: str = ""
    region: str = ""
    expected_salary_text: str = ""
    age: int | None = None
    gender: str = ""
    years_experience_text: str = ""
    wants_accommodation: bool | None = None
    wants_transport: bool | None = None
    salary_min: int | None = None
    salary_max: int | None = None

    @classmethod
    def from_lead(cls, lead: dict | None) -> "LeadProfile":
        lead = lead or {}
        salary_min, salary_max = parse_salary_band(lead.get("expected_salary"))
        return cls(
            desired_job=lead.get("desired_job") or "",
            living_area=lead.get("living_area") or "",
            region=lead.get("region") or "",
            expected_salary_text=lead.get("expected_salary") or "",
            age=lead.get("age"),
            gender=(lead.get("gender") or "").lower(),
            years_experience_text=lead.get("years_experience") or "",
            salary_min=salary_min,
            salary_max=salary_max,
        )

    @property
    def has_any_signal(self) -> bool:
        return bool(self.desired_job or self.living_area or self.region or self.salary_max)


@dataclass
class JobCandidate:
    """One structured job row shaped for pure scoring."""

    id: str
    title: str = ""
    province: str = ""
    district: str = ""
    salary_min: int | None = None
    salary_max: int | None = None
    shift: str = ""
    age_min: int | None = None
    age_max: int | None = None
    gender_requirement: str = ""
    experience_required: str = ""
    accommodation_support: bool | None = None
    meal_support: bool | None = None
    transport_support: bool | None = None
    vacancy_count: int | None = None

    @classmethod
    def from_row(cls, row: dict) -> "JobCandidate":
        return cls(
            id=str(row["id"]),
            title=row.get("title") or "",
            province=row.get("province") or "",
            district=row.get("district") or "",
            salary_min=row.get("salary_min"),
            salary_max=row.get("salary_max"),
            shift=row.get("shift") or "",
            age_min=row.get("age_min"),
            age_max=row.get("age_max"),
            gender_requirement=(row.get("gender_requirement") or "").lower(),
            experience_required=row.get("experience_required") or "",
            accommodation_support=row.get("accommodation_support"),
            meal_support=row.get("meal_support"),
            transport_support=row.get("transport_support"),
            vacancy_count=row.get("vacancy_count"),
        )


@dataclass
class ScoredJob:
    job: JobCandidate
    score: float
    reasons: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ActiveJob:
    """Candidate-visible facts for one active job or ready single-page project."""

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
    created_at: datetime | None = None


@dataclass(frozen=True)
class ActiveJobLookup:
    status: ActiveJobLookupStatus
    jobs: tuple[ActiveJob, ...] = ()
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


def score_title(lead: LeadProfile, job: JobCandidate) -> tuple[float, list[str]]:
    if not lead.desired_job or not job.title:
        return 0.0, []
    similarity = _text_overlap(lead.desired_job, job.title)
    if similarity >= 0.5:
        return similarity, [f"vị trí khớp mong muốn ({job.title})"]
    if similarity > 0:
        return similarity * 0.5, []
    return 0.0, []


def score_salary(lead: LeadProfile, job: JobCandidate) -> tuple[float, list[str]]:
    if lead.salary_max is None or job.salary_max is None:
        return 0.0, []
    job_floor = job.salary_min or 0
    job_ceiling = job.salary_max
    lead_floor = lead.salary_min or int(lead.salary_max * 0.8)
    if job_ceiling >= lead_floor:
        fit = 1.0 if job_floor >= lead_floor else 0.7
        reason = f"lương {job_floor // 1_000_000}-{job_ceiling // 1_000_000} triệu phù hợp"
        return fit, [reason]
    return 0.0, []


def score_location(lead: LeadProfile, job: JobCandidate) -> tuple[float, list[str]]:
    area = lead.living_area or lead.region
    if not area:
        return 0.0, []
    similarity = _text_overlap(area, f"{job.province} {job.district}".strip())
    if similarity <= 0:
        return 0.0, []
    label = "cùng khu vực" if similarity >= 0.5 else "gần khu vực"
    return similarity, [f"{label} ({job.province or job.district})"]


def score_support_flags(lead: LeadProfile, job: JobCandidate) -> tuple[float, list[str]]:
    reasons: list[str] = []
    score = 0.0
    if lead.wants_accommodation and job.accommodation_support:
        score += 0.5
        reasons.append("có KTX/chỗ ở")
    if lead.wants_transport and job.transport_support:
        score += 0.5
        reasons.append("có xe đưa đón")
    return min(score, 1.0), reasons


def score_experience(lead: LeadProfile, job: JobCandidate) -> tuple[float, list[str]]:
    if not job.experience_required:
        return 0.0, []
    requirement = normalize_vietnamese_text(job.experience_required)
    if any(
        token in requirement
        for token in ("khong", "chua can", "khong can", "duoc hoc viec", "moi ra truong")
    ):
        return 1.0, ["không yêu cầu kinh nghiệm"]
    return 0.0, []


def score_job(
    lead: LeadProfile,
    job: JobCandidate,
    *,
    weights: RecommendationWeights = RecommendationWeights(),
) -> ScoredJob:
    """Apply the weighted structured recommendation formula."""
    title_score, title_reasons = score_title(lead, job)
    salary_score, salary_reasons = score_salary(lead, job)
    location_score, location_reasons = score_location(lead, job)
    support_score, support_reasons = score_support_flags(lead, job)
    experience_score, experience_reasons = score_experience(lead, job)

    total = (
        weights.title * title_score
        + weights.salary * salary_score
        + weights.location * location_score
        + weights.support * support_score
        + weights.experience * experience_score
    )
    reasons = (
        title_reasons
        + salary_reasons
        + location_reasons
        + support_reasons
        + experience_reasons
    ) or ["việc làm đang tuyển"]
    return ScoredJob(job=job, score=round(total, 3), reasons=reasons)


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


def _salary_sort_key(job: ActiveJob, *, descending: bool) -> tuple[bool, float, str]:
    magnitude = job.salary_max if job.salary_max is not None else job.salary_min
    numeric = float(magnitude or 0)
    return magnitude is None, -numeric if descending else numeric, job.title.casefold()


def _created_at_sort_key(job: ActiveJob) -> tuple[bool, float]:
    if job.created_at is None:
        return False, 0.0
    return True, job.created_at.timestamp()


def select_matching_active_jobs(
    jobs: list[ActiveJob],
    *,
    role: str | None = None,
    company: str | None = None,
    location: str | None = None,
    top_k: int = 3,
    sort_by: SortBy | None = None,
) -> ActiveJobLookup:
    """Apply explicit semantic filters to a scoped active-job catalog."""
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
        matches.sort(key=lambda job: _salary_sort_key(job, descending=sort_by == "salary_desc"))
    elif sort_by == "created_at":
        matches.sort(key=_created_at_sort_key, reverse=True)

    total = len(matches)
    return (
        ActiveJobLookup("matched", tuple(matches[:limit]), total=total)
        if matches
        else ActiveJobLookup("no_match", total=total)
    )
