"""Pure normalisation functions for lead extraction.

No DB/ORM imports — only string/number manipulation.
"""

from __future__ import annotations

import json
import re
from datetime import datetime


_NOTE_PREFIX_RE = re.compile(r"^(?:(?:[-*•–—])\s*|(?:\d+[.)])\s+)")
_NOTE_TRAILING_PUNCTUATION_RE = re.compile(r"[.!?;:,]+$")


def parse_lead_json(value) -> dict:
    if isinstance(value, dict):
        return value
    s = str(value if value is not None else "").strip()
    if not s:
        return {}
    s = re.sub(r"^\s*```(?:json)?", "", s, flags=re.IGNORECASE).strip()
    s = re.sub(r"```\s*$", "", s, flags=re.IGNORECASE).strip()
    m = re.search(r"\{[\s\S]*\}", s)
    if not m:
        return {}
    try:
        parsed = json.loads(m.group(0))
    except Exception:  # noqa: BLE001
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _pick(value) -> str | None:
    if value is None:
        return None
    t = re.sub(r"\s+", " ", str(value)).strip()
    return t or None


def _note_identity(note: str) -> str:
    normalized = re.sub(r"\s+", " ", note).strip().lower()
    return _NOTE_TRAILING_PUNCTUATION_RE.sub("", normalized).strip()


def normalize_notes(value) -> str | None:
    """Return newline-separated, normalized, unique candidate note facts.

    The extractor owns semantic atomization. This deterministic boundary removes
    presentation prefixes and exact normalized duplicates without fuzzy matching,
    which could otherwise discard distinct candidate facts.
    """
    if value is None:
        return None

    seen: set[str] = set()
    notes: list[str] = []
    for raw_line in str(value).splitlines():
        note = _NOTE_PREFIX_RE.sub("", raw_line.strip())
        note = re.sub(r"\s+", " ", note).strip()
        identity = _note_identity(note)
        if not identity or identity in seen:
            continue
        seen.add(identity)
        notes.append(note)
    return "\n".join(notes) or None


def normalize_phone(value) -> str | None:
    text = _pick(value)
    if not text:
        return None
    phone = re.sub(r"[^\d+]", "", text)
    if phone.startswith("+84"):
        phone = "0" + phone[3:]
    if phone.startswith("84") and len(phone) >= 11:
        phone = "0" + phone[2:]
    return phone if re.fullmatch(r"0\d{8,10}", phone) else None


def normalize_integer(value, min_v: int, max_v: int) -> int | None:
    text = _pick(value)
    if not text:
        return None
    m = re.search(r"\d{1,4}", text)
    if not m:
        return None
    n = int(m.group(0))
    if n < min_v or n > max_v:
        return None
    return n


def normalize_lead_score(value) -> str | None:
    """Return the LLM verdict verbatim; fall back to None (never guess).

    The old ``return "hot" if phone else None`` override was removed because it
    stamped every phone-bearing turn ``hot`` regardless of the LLM's warm /
    not_interested verdict, conflating "contactable" with "high intent".
    """
    score = (_pick(value) or "").lower()
    return score if score in ("hot", "warm", "not_interested") else None


_NAME_STOP_RE = re.compile(
    r"\b(?:số điện thoại|so dien thoai|sdt|phone|ở|o|muốn|muon|chưa|chua|"
    r"có|co|làm|lam|kinh nghiệm|kinh nghiem)\b",
    flags=re.IGNORECASE,
)


def extract_self_reported_name(text: str | None) -> str | None:
    """Extract explicit self-introduction names from short Vietnamese replies.

    This is a narrow deterministic fallback for turns like "tôi tên Mai" when
    the LLM lead extractor misses the `name` field but the bot/memory extractor
    correctly understood it. It intentionally requires the word "tên" / "ten"
    to avoid treating "tôi là công nhân" as a candidate name.
    """
    body = _pick(text)
    if not body:
        return None

    patterns = [
        r"(?:^|\b)(?:tôi|toi|mình|minh|em|e|anh|chị|chi)\s+"
        r"(?:tên|ten)(?:\s+(?:là|la))?\s+(.+)$",
        r"(?:^|\b)(?:tên|ten)\s+(?:tôi|toi|mình|minh|em|e|anh|chị|chi)"
        r"(?:\s+(?:là|la))?\s+(.+)$",
    ]
    for pattern in patterns:
        match = re.search(pattern, body, flags=re.IGNORECASE)
        if not match:
            continue
        candidate = _NAME_STOP_RE.split(match.group(1), maxsplit=1)[0]
        candidate = re.split(r"[,.;:!?()\[\]\n\r]", candidate, maxsplit=1)[0]
        candidate = re.sub(r"\s+", " ", candidate).strip(" -–—\"'“”‘’")
        if not candidate:
            continue
        words = candidate.split()
        if 1 <= len(words) <= 5 and all(re.search(r"[A-Za-zÀ-ỹĐđ]", w) for w in words):
            return candidate
    return None


def current_year() -> int:
    return datetime.now().year


def normalize_lead(raw, chat_id: str) -> dict | None:
    """Full port of 'Merge Lead': returns the normalised lead dict, or None if no chat_id."""
    chat_id = _pick(chat_id)
    if not chat_id:
        return None
    ext = parse_lead_json(raw)
    phone = normalize_phone(ext.get("phone"))

    notes = normalize_notes(ext.get("notes"))

    return {
        "zalo_id": chat_id,
        "name": _pick(ext.get("name")),
        "phone": phone,
        "birth_year": normalize_integer(ext.get("birth_year"), 1900, current_year()),
        "age": normalize_integer(ext.get("age"), 15, 80),
        "living_area": _pick(ext.get("living_area")),
        "address": _pick(ext.get("address")),
        "gender": _pick(ext.get("gender")),
        "region": _pick(ext.get("region")),
        "desired_job": _pick(ext.get("desired_job")),
        "years_experience": _pick(ext.get("years_experience")),
        "expected_salary": _pick(ext.get("expected_salary")),
        "lead_score": normalize_lead_score(ext.get("lead_score")),
        "notes": notes,
    }


# Fields shown to the agent so it can see what's known and what's missing.
# Order matters: top = highest collection priority.  ``notes`` is passive
# capture (never probed directly — there is no natural "what are your notes?" question).
_PROFILE_FIELDS: list[tuple[str, str]] = [
    ("name", "Họ tên"),
    ("phone", "Số điện thoại"),
    ("desired_job", "Công việc mong muốn"),
    ("expected_salary", "Lương mong muốn"),
    ("region", "Tỉnh / thành"),
    ("living_area", "Khu vực sinh sống"),
    ("notes", "Ghi chú"),
]


def lead_profile_text(lead: dict | None, *, personalize: bool = False) -> str:
    """Format a lead dict into a compact text block for injection into the agent context.

    Returns a 'THÔNG TIN ỨNG VIÊN' section showing known values and 'chưa có'
    for missing priority fields. Returns empty string when lead is None (new user).
    """
    if not lead:
        lines = [f"- {label}: chưa có" for _, label in _PROFILE_FIELDS]
        return "THÔNG TIN ỨNG VIÊN (mới, chưa có dữ liệu):\n" + "\n".join(lines)

    lines: list[str] = []
    for key, label in _PROFILE_FIELDS:
        val = _pick(lead.get(key))
        lines.append(f"- {label}: {val or 'chưa có'}")
    if personalize and _pick(lead.get("name")):
        lines.extend(
            [
                "",
                "CÁ NHÂN HÓA TỪ HỒ SƠ OA:",
                "- Đã biết tên ứng viên: không hỏi lại tên.",
                "- Có thể gọi tên tự nhiên khi phù hợp để cuộc trò chuyện thân thiện hơn, "
                "nhưng không lặp tên máy móc trong mọi câu.",
                "- Vẫn xưng hô với người dùng là 'bạn'.",
            ]
        )
    return "THÔNG TIN ỨNG VIÊN:\n" + "\n".join(lines)
