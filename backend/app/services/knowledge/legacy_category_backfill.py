"""Deterministically convert current legacy Project data into category documents.

The converter reads only facts already stored in the Project's structured feature,
bus, and FAQ projections. It does not ask an LLM to infer missing business data.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import time
from typing import Any

from app.schemas.knowledge_categories import CategoryDocument, KnowledgeCategoryKey
from app.services.knowledge.category_contracts import validate_category_payload
from app.services.knowledge.derived_jobs import _coerce_salary_value


@dataclass(frozen=True, slots=True)
class LegacyFeature:
    key: str
    value_text: str
    value_json: dict[str, Any] = field(default_factory=dict)
    evidence_text: str | None = None


@dataclass(frozen=True, slots=True)
class LegacyStop:
    order: int
    name: str
    scheduled_time: time | None = None
    address: str | None = None


@dataclass(frozen=True, slots=True)
class LegacyRoute:
    source_id: str
    route_key: str
    name: str
    shift: str
    direction: str
    service_days: tuple[str, ...] = ()
    fee_vnd: int | None = None
    notes: str | None = None
    stops: tuple[LegacyStop, ...] = ()


@dataclass(frozen=True, slots=True)
class LegacyFaq:
    question: str
    answer: str
    variants: tuple[str, ...] = ()
    required_terms: tuple[str, ...] = ()
    forbidden_terms: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class LegacyCategorySnapshot:
    project_name: str
    project_aliases: tuple[str, ...]
    job_titles: tuple[str, ...]
    job_evidence: tuple[str, ...]
    features: tuple[LegacyFeature, ...]
    routes: tuple[LegacyRoute, ...]
    faqs: tuple[LegacyFaq, ...]


def build_legacy_category_documents(
    snapshot: LegacyCategorySnapshot,
) -> dict[KnowledgeCategoryKey, CategoryDocument]:
    """Build every category supported by facts in ``snapshot``.

    A category with no supporting legacy fact is intentionally omitted. This keeps
    a missing fact visible to the admin instead of manufacturing an answer merely
    to make the progress counter reach twelve.
    """

    features = {row.key: row for row in snapshot.features if row.value_text.strip()}
    payloads: dict[KnowledgeCategoryKey, dict[str, Any]] = {}

    job_id = "legacy-main-job"
    title = _first(snapshot.job_titles) or f"Cơ hội việc làm tại {snapshot.project_name}"
    job_summary = _join_unique(snapshot.job_evidence, limit=5000) or _feature_text(
        features, "job_difficulty"
    )
    job_location = _extract_location(job_summary)
    payloads[KnowledgeCategoryKey.JOBS] = _payload(
        KnowledgeCategoryKey.JOBS,
        "jobs",
        [
            {
                "id": job_id,
                "title": title,
                "aliases": list(dict.fromkeys(snapshot.job_titles[1:])),
                "location": job_location,
                "employment_type": "temporary" if "thời vụ" in title.casefold() else None,
                "summary": job_summary or None,
                "keywords": [],
            }
        ],
    )

    salary = features.get("salary_transparency")
    income = features.get("take_home_income")
    pay_frequency = features.get("pay_frequency")
    overtime = features.get("overtime_rate")
    if any((salary, income, pay_frequency, overtime)):
        salary_json = salary.value_json if salary else {}
        total = salary_json.get("total_without_ot") or {}
        allowances = []
        ranged_allowances: list[str] = []
        for allowance in salary_json.get("allowances") or []:
            if not isinstance(allowance, dict) or not allowance.get("name"):
                continue
            amount = allowance.get("amount")
            if isinstance(amount, int):
                allowances.append(
                    {
                        "name": allowance["name"],
                        "amount_vnd": amount,
                        "cadence": "month",
                        "conditions": allowance.get("condition"),
                    }
                )
            else:
                ranged_allowances.append(
                    f"{allowance['name']}: {allowance.get('min')}–{allowance.get('max')} VND/tháng"
                )
        payment_notes = _join_unique(
            [
                salary.value_text if salary else "",
                income.value_text if income else "",
                pay_frequency.value_text if pay_frequency else "",
                *ranged_allowances,
            ],
            limit=3000,
        )
        payloads[KnowledgeCategoryKey.COMPENSATION] = _payload(
            KnowledgeCategoryKey.COMPENSATION,
            "compensation",
            [
                {
                    "id": "legacy-compensation",
                    "job_ids": [job_id],
                    "base_salary_vnd": _coerce_salary_value(salary_json.get("base_salary")),
                    "estimated_income_min_vnd": _coerce_salary_value(total.get("min")),
                    "estimated_income_max_vnd": _coerce_salary_value(total.get("max")),
                    "allowances": allowances,
                    "bonuses": [],
                    "overtime_notes": overtime.value_text if overtime else None,
                    "payment_notes": payment_notes or None,
                }
            ],
        )

    job_detail = features.get("job_difficulty")
    application = features.get("application_simplicity")
    if job_detail or application:
        job_json = job_detail.value_json if job_detail else {}
        application_json = application.value_json if application else {}
        age_min, age_max = _age_range(application_json.get("age_requirement"))
        payloads[KnowledgeCategoryKey.REQUIREMENTS] = _payload(
            KnowledgeCategoryKey.REQUIREMENTS,
            "requirements",
            [
                {
                    "id": "legacy-requirements",
                    "job_ids": [job_id],
                    "age_min": age_min,
                    "age_max": age_max,
                    "genders": ["any"] if _faq_mentions_both_genders(snapshot.faqs) else [],
                    "education": (
                        "Không yêu cầu bằng cấp"
                        if job_json.get("education_required") is False
                        else None
                    ),
                    "experience": (
                        "Không yêu cầu kinh nghiệm; có đào tạo"
                        if job_json.get("experience_required") is False
                        else None
                    ),
                    "health": _as_text_list(application_json.get("health_requirement")),
                    "skills": [],
                    "required_documents": _as_text_list(
                        application_json.get("required_documents")
                    ),
                    "other": [
                        text
                        for text in (
                            job_detail.value_text if job_detail else "",
                            application.value_text if application else "",
                        )
                        if text
                    ],
                }
            ],
        )

    schedule = features.get("shift_schedule")
    if schedule:
        shifts = [
            {
                "name": name,
                "start_time": start,
                "end_time": end,
                "crosses_midnight": start > end,
            }
            for name, start, end in _extract_shifts(schedule.value_text)
        ]
        payloads[KnowledgeCategoryKey.WORK_SCHEDULES] = _payload(
            KnowledgeCategoryKey.WORK_SCHEDULES,
            "work_schedules",
            [
                {
                    "id": "legacy-work-schedule",
                    "job_ids": [job_id],
                    "work_days": [],
                    "shifts": shifts,
                    "rotation": schedule.value_text,
                    "breaks": [],
                    "overtime": _feature_text(features, "overtime_rate") or None,
                    "notes": schedule.evidence_text,
                }
            ],
        )

    benefit_rows = []
    for key, row_id, name in (
        ("joining_bonus", "legacy-joining-bonus", "Thưởng nhận việc"),
        ("daily_cost_benefits", "legacy-daily-cost-benefits", "Hỗ trợ chi phí"),
    ):
        row = features.get(key)
        if row:
            benefit_rows.append(
                {
                    "id": row_id,
                    "job_ids": [job_id],
                    "name": name,
                    "description": row.value_text,
                    "eligibility": row.evidence_text,
                }
            )
    if benefit_rows:
        payloads[KnowledgeCategoryKey.BENEFITS] = _payload(
            KnowledgeCategoryKey.BENEFITS, "benefits", benefit_rows
        )

    housing = features.get("housing")
    if housing:
        payloads[KnowledgeCategoryKey.ACCOMMODATION] = _payload(
            KnowledgeCategoryKey.ACCOMMODATION,
            "accommodation",
            [
                {
                    "id": "legacy-accommodation",
                    "job_ids": [job_id],
                    "available": True,
                    "type": "Ký túc xá",
                    "address": None,
                    "monthly_cost_vnd": None,
                    "deposit_vnd": None,
                    "included_services": [],
                    "eligibility": housing.value_text,
                    "notes": housing.evidence_text,
                }
            ],
        )

    meal_answers = _matching_faq_answers(snapshot.faqs, ("suất ăn", "bữa ăn", "ăn ca", "cơm ca"))
    if meal_answers:
        payloads[KnowledgeCategoryKey.MEALS] = _payload(
            KnowledgeCategoryKey.MEALS,
            "meals",
            [
                {
                    "id": "legacy-meals",
                    "job_ids": [job_id],
                    "provided": True,
                    "meals_per_shift": None,
                    "allowance_vnd": None,
                    "menu_notes": None,
                    "eligibility": None,
                    "notes": _join_unique(meal_answers, limit=3000),
                }
            ],
        )

    if snapshot.routes:
        route_rows = []
        seen_route_ids: set[str] = set()
        for route in snapshot.routes:
            route_id = _unique_route_id(route, seen_route_ids)
            seen_route_ids.add(route_id)
            route_rows.append(
                {
                    "id": route_id,
                    "job_ids": [job_id],
                    "name": route.name,
                    "direction": "to_factory" if route.direction == "outbound" else "from_factory",
                    "service_days": list(route.service_days),
                    "shift": route.shift,
                    "fee_vnd": route.fee_vnd,
                    "stops": [
                        {
                            "order": stop.order,
                            "name": stop.name,
                            "time": (
                                stop.scheduled_time.strftime("%H:%M")
                                if stop.scheduled_time
                                else None
                            ),
                            "address": stop.address,
                        }
                        for stop in route.stops
                    ],
                    "notes": route.notes,
                }
            )
        payloads[KnowledgeCategoryKey.TRANSPORTATION] = _payload(
            KnowledgeCategoryKey.TRANSPORTATION, "transportation", route_rows
        )

    insurance_answers = _matching_faq_answers(snapshot.faqs, ("bảo hiểm", "bhxh", "bhyt", "bhtn"))
    if insurance_answers:
        coverage = [
            label
            for label in ("BHXH", "BHYT", "BHTN")
            if any(
                label.casefold() in f"{faq.question} {faq.answer}".casefold()
                for faq in snapshot.faqs
            )
        ]
        payloads[KnowledgeCategoryKey.INSURANCE] = _payload(
            KnowledgeCategoryKey.INSURANCE,
            "insurance",
            [
                {
                    "id": "legacy-insurance",
                    "job_ids": [job_id],
                    "name": "Bảo hiểm theo nguồn hiện tại",
                    "provider": None,
                    "employee_contribution": None,
                    "employer_contribution": None,
                    "coverage": coverage,
                    "starts_after": _first(insurance_answers),
                    "eligibility": None,
                    "notes": _join_unique(insurance_answers, limit=3000),
                }
            ],
        )

    if application:
        application_json = application.value_json
        payloads[KnowledgeCategoryKey.APPLICATION] = _payload(
            KnowledgeCategoryKey.APPLICATION,
            "application",
            [
                {
                    "id": "legacy-application",
                    "job_ids": [job_id],
                    "application_steps": [],
                    "required_documents": _as_text_list(
                        application_json.get("required_documents")
                    ),
                    "interview_location": None,
                    "interview_process": None,
                    "onboarding_steps": [],
                    "processing_time": None,
                    "fees": (
                        "VFIC hỗ trợ hồ sơ miễn phí; không thu phí"
                        if application_json.get("cost_to_applicant") == 0
                        else None
                    ),
                    "notes": application.value_text,
                }
            ],
        )

    contact = features.get("contact_info")
    if contact:
        contact_json = contact.value_json
        contact_rows = []
        training_contact = str(contact_json.get("training_day_contact") or "").strip()
        if training_contact:
            name, phone = _contact_parts(training_contact)
            contact_rows.append(
                {
                    "id": "legacy-training-contact",
                    "name": name,
                    "role": "Hỗ trợ ngày đào tạo",
                    "phone": phone,
                    "zalo": None,
                    "email": None,
                    "address": None,
                    "working_hours": None,
                    "notes": contact.evidence_text,
                }
            )
        support = str(contact_json.get("vfic_support") or "").strip()
        if support:
            office_address = str(contact_json.get("office_address") or "").strip()
            hotline = str(contact_json.get("hotline") or "").strip()
            company_legal_name = str(contact_json.get("company_legal_name") or "").strip()
            company_tax_code = str(contact_json.get("company_tax_code") or "").strip()
            company_facts = " ".join(
                part
                for part in (
                    company_legal_name,
                    f"MST {company_tax_code}" if company_tax_code else "",
                    f"Văn phòng công ty: {office_address}." if office_address else "",
                    "(văn phòng công ty, khác với nơi làm việc nhà máy)" if office_address else "",
                )
                if part
            )
            contact_rows.append(
                {
                    "id": "legacy-vfic-support",
                    "name": "Nhân viên tuyển dụng VFIC",
                    "role": "Hỗ trợ ứng viên",
                    "phone": hotline or None,
                    "zalo": None,
                    "email": None,
                    "address": office_address or None,
                    "working_hours": None,
                    "notes": _join_unique([support, contact_json.get("fee_note"), company_facts, contact.value_text]),
                }
            )
        if contact_rows:
            payloads[KnowledgeCategoryKey.CONTACTS] = _payload(
                KnowledgeCategoryKey.CONTACTS, "contacts", contact_rows
            )

    faq_rows = []
    for faq in _deduplicate_faqs(snapshot.faqs):
        faq_rows.append(
            {
                "id": f"faq-{hashlib.sha256(_normalize(faq.question).encode()).hexdigest()[:16]}",
                "question": faq.question,
                "answer": faq.answer,
                "question_variants": list(faq.variants[:50]),
                "required_terms": list(faq.required_terms[:50]),
                "forbidden_terms": list(faq.forbidden_terms[:50]),
            }
        )
    if faq_rows:
        payloads[KnowledgeCategoryKey.FAQ] = _payload(
            KnowledgeCategoryKey.FAQ, "faq", faq_rows
        )

    return {
        key: validate_category_payload(key, payload)
        for key, payload in payloads.items()
    }


def _payload(key: KnowledgeCategoryKey, field_name: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {"schema_version": "1.0", "category": key.value, field_name: rows}


def _feature_text(features: dict[str, LegacyFeature], key: str) -> str:
    row = features.get(key)
    return row.value_text.strip() if row else ""


def _first(values) -> str:
    return next((str(value).strip() for value in values if str(value).strip()), "")


def _join_unique(values, *, limit: int = 3000) -> str:
    unique: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        marker = _normalize(text)
        if text and marker not in seen:
            seen.add(marker)
            unique.append(text)
    return "\n".join(unique)[:limit]


def _normalize(value: str) -> str:
    return " ".join(value.casefold().split())


def _as_text_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value or "").strip()
    return [text] if text else []


def _age_range(value: Any) -> tuple[int | None, int | None]:
    numbers = [int(item) for item in re.findall(r"\d{2}", str(value or ""))]
    return (numbers[0], numbers[1]) if len(numbers) >= 2 else (None, None)


def _extract_shifts(value: str) -> list[tuple[str, str, str]]:
    matches = re.findall(
        r"(ca\s+(?:ngày|đêm))\s+(\d{1,2}:\d{2})\s*[-–]\s*(\d{1,2}:\d{2})",
        value,
        flags=re.IGNORECASE,
    )
    return [(name.strip().title(), start.zfill(5), end.zfill(5)) for name, start, end in matches]


def _extract_location(value: str) -> str | None:
    match = re.search(
        r"(?:tại|nằm tại)\s+(Khu công nghiệp[^.\n]+)", value, flags=re.IGNORECASE
    )
    return match.group(1).strip() if match else None


def _faq_mentions_both_genders(faqs: tuple[LegacyFaq, ...]) -> bool:
    return any(
        "nam" in _normalize(faq.answer) and "nữ" in _normalize(faq.answer)
        for faq in faqs
        if "nam" in _normalize(faq.question) or "nữ" in _normalize(faq.question)
    )


def _matching_faq_answers(faqs: tuple[LegacyFaq, ...], terms: tuple[str, ...]) -> list[str]:
    normalized_terms = tuple(_normalize(term) for term in terms)
    return [
        faq.answer
        for faq in _deduplicate_faqs(faqs)
        if any(term in _normalize(f"{faq.question} {faq.answer}") for term in normalized_terms)
    ]


def _deduplicate_faqs(faqs: tuple[LegacyFaq, ...]) -> list[LegacyFaq]:
    by_question: dict[str, LegacyFaq] = {}
    for faq in faqs:
        question = faq.question.strip()
        answer = faq.answer.strip()
        if not question or not answer:
            continue
        marker = _normalize(question)
        current = by_question.get(marker)
        if current is None or len(answer) > len(current.answer):
            by_question[marker] = LegacyFaq(
                question=question,
                answer=answer[:5000],
                variants=faq.variants,
                required_terms=faq.required_terms,
                forbidden_terms=faq.forbidden_terms,
            )
    return [by_question[key] for key in sorted(by_question)]


def _contact_parts(value: str) -> tuple[str, str | None]:
    phone_match = re.search(r"(?<!\d)(0\d{9,10})(?!\d)", value)
    phone = phone_match.group(1) if phone_match else None
    name = value[: phone_match.start()].rstrip(" -–:") if phone_match else value
    return name or "Liên hệ dự án", phone


def _ascii_slug(value: str) -> str:
    folded = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", folded.casefold()).strip("-") or "route"


def _unique_route_id(route: LegacyRoute, seen: set[str]) -> str:
    suffix = route.source_id.replace("-", "")[:8]
    stem = _ascii_slug(f"{route.route_key}-{route.shift}-{route.direction}")[:48]
    candidate = f"bus-{stem}-{suffix}"[:64]
    if candidate not in seen:
        return candidate
    digest = hashlib.sha256(route.source_id.encode()).hexdigest()[:12]
    return f"bus-{stem[:46]}-{digest}"[:64]
