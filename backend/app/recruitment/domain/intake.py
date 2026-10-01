"""Evidence-only candidate contact and recruitment-wish rules.

Project knowledge describes the opportunity; only the candidate can supply
their contact information and decide that they want to apply.
"""

from __future__ import annotations

import re

from app.shared.domain.text import normalize_vietnamese_text

_PHONE_CANDIDATE = re.compile(r"(?<![\w+])(?:\+84|84|0)(?:[ .()-]*[0-9]){8,10}(?!\w)")
_MOBILE = re.compile(r"0[35789][0-9]{8}")
_INTENT = re.compile(
    r"\b(?:muon\s+(?:ung tuyen|dang ky|lam)|nguyen vong|mong muon)\s+(.+)"
)
_NEGATED_INTENT = re.compile(r"\b(?:khong|chua|ko|k)\s+(?:con\s+)?muon\b")
_EMPTY_INTENTS = frozenset({"gi", "gi a", "gi vay", "khong", "chua", "chua biet"})
_THIRD_PARTY_CONTACT = re.compile(
    r"\b(?:hotline|tong dai|so (?:dien thoai )?(?:cua )?"
    r"(?:cong ty|nha may|tu van vien|tuyen dung|bo|me|vo|chong|ban em|ban toi))\b"
)
_CONTACT_CLAUSE_BOUNDARY = re.compile(r"[,;!?\n\r]|(?<![0-9])\.(?![0-9])")
_SELF_CONTACT_PREFIX = re.compile(
    r"\b(?:sdt|so(?: dien thoai| di dong| lien he)?|dien thoai) "
    r"(?:cua )?(?:em|toi|minh|anh|chi)(?: la)?[ :–—-]*$"
)
_SELF_CONTACT_SUFFIX = re.compile(
    r"^[ :–—-]*(?:la )?(?:sdt|so(?: dien thoai| di dong| lien he)?|dien thoai) "
    r"(?:cua )?(?:em|toi|minh|anh|chi)\b"
)


def phone_values(text: str | None) -> tuple[str, ...]:
    """Keep complete number tokens separate; never join digits across prose."""
    values: list[str] = []
    for match in _PHONE_CANDIDATE.finditer(text or ""):
        value = re.sub(r"[^0-9+]", "", match.group())
        if value.startswith("+84"):
            value = "0" + value[3:]
        elif value.startswith("84"):
            value = "0" + value[2:]
        if value not in values:
            values.append(value)
    return tuple(values)


def candidate_mobile(text: str | None) -> str | None:
    """Accept one unambiguous mobile number, including +84 and separators."""
    values = phone_values(text)
    if len(values) != 1:
        return None
    return values[0] if _MOBILE.fullmatch(values[0]) else None


def candidate_contact_mobile(text: str | None) -> str | None:
    """Do not make an employer/other person's quoted contact the lead's phone."""
    source = text or ""
    phone = candidate_mobile(source)
    if phone is None:
        return None
    has_third_party_context = bool(
        _THIRD_PARTY_CONTACT.search(normalize_vietnamese_text(source))
    )
    boundaries = list(_CONTACT_CLAUSE_BOUNDARY.finditer(source))
    for number in _PHONE_CANDIDATE.finditer(source):
        start = max(
            (boundary.end() for boundary in boundaries if boundary.end() <= number.start()),
            default=0,
        )
        end = min(
            (boundary.start() for boundary in boundaries if boundary.start() >= number.end()),
            default=len(source),
        )
        before = normalize_vietnamese_text(source[start:number.start()])
        after = normalize_vietnamese_text(source[number.end():end])
        own_prefix = bool(_SELF_CONTACT_PREFIX.search(before))
        own_suffix = bool(_SELF_CONTACT_SUFFIX.search(after))
        # An unrelated hotline in another clause does not own this number.
        # Within a clause, only an explicit adjacent "số của em là ..." can
        # establish candidate ownership after earlier third-party context.
        if (
            _THIRD_PARTY_CONTACT.search(after)
            or (_THIRD_PARTY_CONTACT.search(before) and not own_prefix)
            or (has_third_party_context and not (own_prefix or own_suffix))
        ):
            return None
    return phone


def has_full_name(value: object) -> bool:
    """A nickname alone is insufficient; preserve names without guessing parts."""
    text = " ".join(str(value or "").split())
    words = text.split()
    return (
        2 <= len(words) <= 6
        and len(text) <= 100
        and all(all(char.isalpha() or char in "-'’" for char in word) for word in words)
    )


def candidate_wish(text: str | None) -> str | None:
    """Capture explicit wishes without turning generic job questions into intent.

    Keep the candidate's own wording (including the project they name). More
    nuanced wishes are still handled by the deferred extraction model.
    """
    source = " ".join((text or "").split())
    normalized = normalize_vietnamese_text(source)
    if "?" in source or _NEGATED_INTENT.search(normalized):
        return None
    match = _INTENT.search(normalized)
    if not match:
        return None
    target = re.split(r"[,;.!]", match.group(1), maxsplit=1)[0].strip()
    if not target or target in _EMPTY_INTENTS:
        return None
    wish = source[match.start():]
    wish = re.split(r"[,;.!]", wish, maxsplit=1)[0]
    wish = re.split(
        r"\b(?:sđt|sdt|số điện thoại|so dien thoai|điện thoại|dien thoai)\b",
        wish,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0].strip()
    return wish[:300] or None
