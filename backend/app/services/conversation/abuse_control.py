"""Conservative, deterministic classification for explicit abuse declarations.

This module intentionally does not infer intent. It recognizes only a small set
of bounded first-person declarations and leaves every ambiguous case to normal
conversation handling.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Final, Literal

AbuseReason = Literal[
    "explicit_bot_testing",
    "explicit_spam_intent",
    "explicit_non_candidate",
]

_Pattern = re.Pattern[str]


def _compile(*patterns: str) -> tuple[_Pattern, ...]:
    return tuple(re.compile(pattern) for pattern in patterns)


_CANDIDATE_SIGNALS: Final = _compile(
    r"\b(?:apply|applying|application|candidate application)\b",
    r"\b(?:job|jobs|employment|vacancy|vacancies|recruit(?:ing|ment)?)\b",
    r"\b(?:name|phone|telephone|salary|location|address|shift|experience|interview)\b",
    r"\b(?:cv|resume)\b",
    r"\b(?:ung tuyen|xin viec|ho so|cong viec|viec lam|vi tri|tuyen dung)\b",
    r"\b(?:ten|so dien thoai|dien thoai|sdt)\b",
    r"\b(?:luong|dia diem|dia chi|noi lam viec|ca lam|ca dem|ca ngay)\b",
    r"\b(?:kinh nghiem|phong van)\b",
    r"\b(?:\+?84|0)\d{8,10}\b",
)

_DISALLOWED_CONTEXTS: Final = _compile(
    r"\b(?:ignore|disregard|forget) (?:all |any )?(?:previous|prior|above) instructions\b",
    r"\b(?:system prompt|developer message|prompt injection|jailbreak)\b",
    r"\b(?:act as|pretend (?:to be|you are))\b",
    r"\b(?:someone|somebody|they|he|she) (?:said|says|wrote|writes|reported)\b",
    r"\b(?:reporting|reported|training example|quoted text|for example|classify)\b",
    r"\b(?:if i say|what happens if)\b",
    r"\b(?:bao cao|nguoi nay noi|vi du|doan trich|hay phan loai)\b",
    r"\b(?:i am not|i'm not) (?:here to )?(?:test|testing|spam)\b",
    r"\bi (?:do not|don't|dont) (?:want to )?(?:test|spam)\b",
    r"\b(?:toi|minh|tao) khong (?:muon )?(?:test|thu|spam)\b",
    r"\b(?:toi|minh|tao) khong phai (?:la )?nguoi (?:test|thu)\b",
)

_EXPLICIT_PATTERNS: Final[tuple[tuple[AbuseReason, tuple[_Pattern, ...]], ...]] = (
    (
        "explicit_bot_testing",
        _compile(
            r"(?:i am|i'm) (?:just )?(?:testing|trying out) (?:your |this )?(?:bot|chatbot)",
            r"(?:i am|i'm) (?:a )?(?:bot|chatbot) tester",
            r"(?:toi|minh|tao) (?:chi )?(?:dang )?(?:test|thu|kiem thu|kiem tra) "
            r"(?:con )?(?:bot|chatbot)(?: (?:nay|thoi))?",
            r"(?:toi|minh|tao) (?:la )?nguoi (?:test|thu|kiem thu|kiem tra) (?:bot|chatbot)",
        ),
    ),
    (
        "explicit_spam_intent",
        _compile(
            r"(?:i am|i'm) (?:here )?to spam(?: (?:your |this )?(?:system|bot|chatbot))?",
            r"i (?:want|intend|plan) to spam(?: (?:your |this )?(?:system|bot|chatbot))?",
            r"(?:i am|i'm) (?:a )?spammer",
            r"(?:toi|minh|tao) (?:vao day )?de spam(?: (?:he thong|bot|chatbot))?",
            r"(?:toi|minh|tao) (?:muon|dinh) spam(?: (?:he thong|bot|chatbot))?",
            r"(?:toi|minh|tao) (?:la )?spammer",
        ),
    ),
    (
        "explicit_non_candidate",
        _compile(
            r"(?:i am|i'm) not (?:a )?candidate",
            r"(?:toi|minh|tao) khong phai (?:la )?ung vien(?: dau)?",
        ),
    ),
)

_QUOTE_CHARACTERS: Final = frozenset('"`“”«»「」『』')


def _normalize(user_text: str) -> str:
    compatibility_normalized = unicodedata.normalize("NFKC", user_text).casefold()
    without_diacritics = "".join(
        character
        for character in unicodedata.normalize("NFKD", compatibility_normalized)
        if not unicodedata.combining(character)
    )
    vietnamese_ascii = without_diacritics.translate(str.maketrans({"đ": "d", "‘": "'", "’": "'"}))
    return " ".join(vietnamese_ascii.split())


def _matches_any(text: str, patterns: tuple[_Pattern, ...]) -> bool:
    return any(pattern.search(text) is not None for pattern in patterns)


def _has_quoted_context(user_text: str) -> bool:
    if any(character in _QUOTE_CHARACTERS for character in user_text):
        return True
    if user_text.count("'") >= 2:
        return True
    return user_text.count("‘") + user_text.count("’") >= 2


def classify_suspected_abuse(user_text: str) -> AbuseReason | None:
    """Return a reason only for an unambiguous first-person abuse declaration."""
    if not isinstance(user_text, str) or not user_text.strip():
        return None

    normalized = _normalize(user_text)
    if _has_quoted_context(user_text):
        return None
    if "?" in normalized or _matches_any(normalized, _DISALLOWED_CONTEXTS):
        return None
    if _matches_any(normalized, _CANDIDATE_SIGNALS):
        return None

    declaration = normalized.strip(" .,!;:…")
    for reason, patterns in _EXPLICIT_PATTERNS:
        if any(pattern.fullmatch(declaration) is not None for pattern in patterns):
            return reason
    return None
