"""Pure candidate-intake decision rules."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Literal, cast


ContactIntent = Literal[
    "candidate",
    "non_candidate",
    "spam",
    "bot_testing",
    "uncertain",
]
TextNormalizer = Callable[[str], str]

_CONTACT_INTENTS: frozenset[str] = frozenset(
    {"candidate", "non_candidate", "spam", "bot_testing", "uncertain"}
)
_HUMAN_REVIEW_INTENTS: frozenset[str] = frozenset(
    {"non_candidate", "spam", "bot_testing"}
)
HUMAN_REVIEW_CONFIDENCE_THRESHOLD = 0.95
_EXPLICIT_HUMAN_REVIEW_EVIDENCE: dict[ContactIntent, tuple[str, ...]] = {
    "non_candidate": (
        "khong phai ung vien",
        "khong phai nguoi tim viec",
        "khong tim viec",
        "khong co nhu cau tim viec",
        "toi khong can tim viec",
        "minh khong can tim viec",
        "toi la nha tuyen dung",
        "minh la nha tuyen dung",
        "toi muon tuyen nguoi",
        "minh muon tuyen nguoi",
        "toi dang tuyen nguoi",
        "minh dang tuyen nguoi",
    ),
    "bot_testing": (
        "toi dang kiem tra bot",
        "minh dang kiem tra bot",
        "toi dang kiem tra chatbot",
        "minh dang kiem tra chatbot",
        "toi dang kiem thu bot",
        "minh dang kiem thu bot",
        "toi dang test bot",
        "minh dang test bot",
        "toi dang test chatbot",
        "minh dang test chatbot",
    ),
    "spam": (
        "toi dang spam",
        "minh dang spam",
        "toi gui spam",
        "minh gui spam",
        "toi muon spam",
        "minh muon spam",
        "toi muon pha he thong",
        "minh muon pha he thong",
    ),
}


@dataclass(frozen=True, slots=True)
class CandidateExtraction:
    lead_patch: dict[str, object] | None
    memory_facts: list[str]
    contact_intent: ContactIntent = "uncertain"
    intent_confidence: float = 0.0

    @property
    def requires_human_review(self) -> bool:
        return (
            self.contact_intent in _HUMAN_REVIEW_INTENTS
            and self.intent_confidence >= HUMAN_REVIEW_CONFIDENCE_THRESHOLD
        )


def has_explicit_human_review_evidence(
    user_text: str,
    intent: ContactIntent,
    *,
    normalize_text: TextNormalizer,
) -> bool:
    normalized = normalize_text(user_text or "")
    return any(phrase in normalized for phrase in _EXPLICIT_HUMAN_REVIEW_EVIDENCE.get(intent, ()))


def normalize_contact_intent(value: object, confidence: object) -> tuple[ContactIntent, float]:
    intent = str(value or "").strip().lower()
    if intent not in _CONTACT_INTENTS:
        return "uncertain", 0.0
    try:
        score = float(confidence)
    except (TypeError, ValueError):
        return "uncertain", 0.0
    if not 0.0 <= score <= 1.0:
        return "uncertain", 0.0
    return cast(ContactIntent, intent), score


def finalize_candidate_extraction(
    *,
    lead_patch: dict[str, object] | None,
    memory_facts: list[str],
    contact_intent: ContactIntent,
    intent_confidence: float,
) -> CandidateExtraction:
    negative_intent = contact_intent in _HUMAN_REVIEW_INTENTS
    contradictory_payload = negative_intent and (
        any(value for key, value in (lead_patch or {}).items() if key != "zalo_id")
        or bool(memory_facts)
    )
    if negative_intent:
        lead_patch = None
        memory_facts = []
    if contradictory_payload:
        contact_intent = "uncertain"
        intent_confidence = 0.0
    return CandidateExtraction(
        lead_patch=lead_patch,
        memory_facts=list(memory_facts),
        contact_intent=contact_intent,
        intent_confidence=intent_confidence,
    )


__all__ = [
    "CandidateExtraction",
    "ContactIntent",
    "HUMAN_REVIEW_CONFIDENCE_THRESHOLD",
    "TextNormalizer",
    "finalize_candidate_extraction",
    "has_explicit_human_review_evidence",
    "normalize_contact_intent",
]
