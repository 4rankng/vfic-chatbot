"""Pure-Python scoring for the Job↔Lead structured recommendation engine.

No DB, no embeddings, no LLM — just deterministic scoring of candidate ``Job`` rows
against a ``LeadProfile``. This is the MiniMax §7.2 hybrid scoring formula adapted
to the columns the VFIC schema already has.

Weights are tunable via :mod:`app.core.config` (``rec_weight_*``) because the research
is explicit: "weights must be re-tuned against labeled hires after the first 1,000
production conversations; this is a starting point, not a final answer."

Intentionally pure so :mod:`backend/tests/test_recommendation_scoring` can pin every
signal in isolation without a database.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.core.config import get_settings
from app.core.text import normalize_vietnamese_text

# Salary is stored on Lead as free text ("12 triệu", "10-15 trieu", "20000000").
# Parse to a VND/month integer band; None when unparseable. The Job table already
# carries numeric salary_min/salary_max, so we only parse the lead side.
_TRIEU_RE = re.compile(r"(\d[\d.]*)\s*trieu|\b(\d[\d.]*)\s*tr", re.IGNORECASE)
_NGHIN_RE = re.compile(r"(\d[\d.]*)\s*nghin|\b(\d[\d.]*)\s*k\b", re.IGNORECASE)
_PLAIN_RE = re.compile(r"(\d{6,})")  # 6+ digits → assume raw VND
_RANGE_RE = re.compile(r"(\d[\d.]*)\s*[-–]\s*(\d[\d.]*)")


def parse_salary_band(text: str | None) -> tuple[int | None, int | None]:
    """Parse free-text Vietnamese salary into a ``(min, max)`` VND/month band.

    Handles "12 triệu", "10-15 trieu", "20tr", "15000000", "12-15 triệu".
    Returns ``(None, None)`` when unparseable. A single number yields a band
    centered loosely on it (min = 80%, max = the stated figure) so a candidate
    saying "around 12 million" matches jobs paying >= ~9.6M.
    """
    if not text:
        return None, None
    t = normalize_vietnamese_text(str(text))

    def _scale(num_str: str) -> int:
        n = float(num_str)
        if "trieu" in t or "tr" in t.split() or re.search(r"\btr\b", t):
            return int(n * 1_000_000)
        if "nghin" in t or re.search(r"\bk\b", t):
            return int(n * 1_000)
        if n >= 1_000_000:
            return int(n)
        # Small bare number with no unit — assume triệu (most common in VN recruiting).
        return int(n * 1_000_000)

    # Range first: "10-15 triệu"
    rng = _RANGE_RE.search(t)
    if rng:
        lo, hi = _scale(rng.group(1)), _scale(rng.group(2))
        if lo > hi:
            lo, hi = hi, lo
        return lo, hi

    # Single figure with unit
    m = _TRIEU_RE.search(t) or _NGHIN_RE.search(t)
    if m:
        num_str = next(g for g in m.groups() if g)
        val = _scale(num_str)
        return int(val * 0.8), val

    # Bare large number (raw VND)
    plain = _PLAIN_RE.search(t)
    if plain:
        val = int(plain.group(1))
        return int(val * 0.8), val

    return None, None


@dataclass
class LeadProfile:
    """The candidate signals the ranker uses, extracted from the ``leads`` row."""

    desired_job: str = ""
    living_area: str = ""
    region: str = ""
    expected_salary_text: str = ""
    age: int | None = None
    gender: str = ""
    years_experience_text: str = ""
    wants_accommodation: bool | None = None
    wants_transport: bool | None = None
    # Pre-parsed salary band (avoids re-parsing per job).
    salary_min: int | None = None
    salary_max: int | None = None

    @classmethod
    def from_lead(cls, lead: dict | None) -> "LeadProfile":
        lead = lead or {}
        sal_min, sal_max = parse_salary_band(lead.get("expected_salary"))
        return cls(
            desired_job=lead.get("desired_job") or "",
            living_area=lead.get("living_area") or "",
            region=lead.get("region") or "",
            expected_salary_text=lead.get("expected_salary") or "",
            age=lead.get("age"),
            gender=(lead.get("gender") or "").lower(),
            years_experience_text=lead.get("years_experience") or "",
            salary_min=sal_min,
            salary_max=sal_max,
        )

    @property
    def has_any_signal(self) -> bool:
        """A recommendation only makes sense with at least one matching signal."""
        return bool(self.desired_job or self.living_area or self.region or self.salary_max)


@dataclass
class JobCandidate:
    """A job row shaped for scoring (a flat dict from the SQL query)."""

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


def _text_overlap(query: str, target: str) -> float:
    """Normalized term-overlap ratio (trigram-free, deterministic).

    Returns the fraction of query terms present in target. Both sides are
    ASCII-folded + lowercased so "Bình Dương" matches "binh duong".
    """
    if not query or not target:
        return 0.0
    q = normalize_vietnamese_text(query)
    t = normalize_vietnamese_text(target)
    q_terms = {w for w in q.split() if len(w) > 1}
    if not q_terms:
        return 0.0
    hits = sum(1 for term in q_terms if term in t)
    return hits / len(q_terms)


def score_title(lead: LeadProfile, job: JobCandidate) -> tuple[float, list[str]]:
    if not lead.desired_job or not job.title:
        return 0.0, []
    sim = _text_overlap(lead.desired_job, job.title)
    if sim >= 0.5:
        return sim, [f"vị trí khớp mong muốn ({job.title})"]
    if sim > 0:
        return sim * 0.5, []  # partial — don't surface a weak reason
    return 0.0, []


def score_salary(lead: LeadProfile, job: JobCandidate) -> tuple[float, list[str]]:
    if lead.salary_max is None or job.salary_max is None:
        return 0.0, []
    # Salary fit: does the job's disclosed band reach the candidate's minimum?
    job_floor = job.salary_min or 0
    job_ceil = job.salary_max
    lead_floor = lead.salary_min or int(lead.salary_max * 0.8)
    if job_ceil >= lead_floor:
        fit = 1.0 if job_floor >= lead_floor else 0.7
        reason = f"lương {job_floor // 1_000_000}-{job_ceil // 1_000_000} triệu phù hợp"
        return fit, [reason]
    return 0.0, []


def score_location(lead: LeadProfile, job: JobCandidate) -> tuple[float, list[str]]:
    area = lead.living_area or lead.region
    if not area:
        return 0.0, []
    job_loc = f"{job.province} {job.district}".strip()
    sim = _text_overlap(area, job_loc)
    if sim <= 0:
        return 0.0, []
    label = "cùng khu vực" if sim >= 0.5 else "gần khu vực"
    return sim, [f"{label} ({job.province or job.district})"]


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
    """Soft experience match — surfaces 'no experience required' as a plus."""
    if not job.experience_required:
        return 0.0, []
    req = normalize_vietnamese_text(job.experience_required)
    if any(w in req for w in ("khong", "chua can", "khong can", "duoc hoc viec", "moi ra truong")):
        return 1.0, ["không yêu cầu kinh nghiệm"]
    return 0.0, []


def score_job(lead: LeadProfile, job: JobCandidate) -> ScoredJob:
    """Apply the full weighted scoring formula and collect matched reasons."""
    s = get_settings()
    w_title = getattr(s, "rec_weight_title", 0.35)
    w_salary = getattr(s, "rec_weight_salary", 0.25)
    w_location = getattr(s, "rec_weight_location", 0.20)
    w_support = getattr(s, "rec_weight_support", 0.10)
    w_experience = getattr(s, "rec_weight_experience", 0.10)

    t_score, t_reasons = score_title(lead, job)
    sal_score, sal_reasons = score_salary(lead, job)
    loc_score, loc_reasons = score_location(lead, job)
    sup_score, sup_reasons = score_support_flags(lead, job)
    exp_score, exp_reasons = score_experience(lead, job)

    total = (
        w_title * t_score
        + w_salary * sal_score
        + w_location * loc_score
        + w_support * sup_score
        + w_experience * exp_score
    )
    reasons = (t_reasons + sal_reasons + loc_reasons + sup_reasons + exp_reasons) or [
        "việc làm đang tuyển"
    ]
    return ScoredJob(job=job, score=round(total, 3), reasons=reasons)
