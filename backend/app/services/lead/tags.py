"""Manual + system tag normalization for leads (pure functions, no DB).

Extracted from ``LeadService`` so the tag vocabulary and key-derivation rules live
in one focused module. The service composes these via thin delegates.
"""

from __future__ import annotations

import re
import unicodedata

from app.models.conversation import Conversation, ConversationMode
from app.models.lead import Lead, LeadScore, LeadStage

_TAG_META: dict[str, dict[str, str | bool]] = {
    "has_phone": {"label": "Có SĐT", "tone": "good", "system": True},
    "missing_phone": {"label": "Thiếu SĐT", "tone": "warn", "system": True},
    "needs_follow_up": {"label": "Cần follow-up", "tone": "info", "system": False},
    "not_interested": {"label": "Không quan tâm", "tone": "danger", "system": False},
    "registered": {"label": "Đã đăng ký", "tone": "good", "system": False},
    "salary_missing": {"label": "Thiếu lương", "tone": "warn", "system": False},
    "location_missing": {"label": "Thiếu khu vực", "tone": "warn", "system": False},
    "needs_human": {"label": "Cần người xử lý", "tone": "danger", "system": False},
}

_MANUAL_TAG_KEYS = {key for key, meta in _TAG_META.items() if not bool(meta.get("system"))}
_SYSTEM_TAG_KEYS = {key for key, meta in _TAG_META.items() if bool(meta.get("system"))}


def tag_payload(key: str, *, system: bool) -> dict:
    meta = _TAG_META[key]
    return {
        "key": key,
        "label": meta["label"],
        "tone": meta["tone"],
        "system": system,
    }


def system_tag_keys(lead: Lead, conversation: Conversation | None) -> list[str]:
    tags: list[str] = []
    tags.append("has_phone" if lead.phone and lead.phone.strip() else "missing_phone")
    if lead.next_action_at:
        tags.append("needs_follow_up")
    if lead.lead_score == LeadScore.not_interested or lead.lead_stage == LeadStage.SKIPPED:
        tags.append("not_interested")
    if lead.lead_stage == LeadStage.REGISTERED:
        tags.append("registered")
    if not (lead.expected_salary and lead.expected_salary.strip()):
        tags.append("salary_missing")
    if not (lead.region and lead.region.strip()) and not (
        lead.living_area and lead.living_area.strip()
    ):
        tags.append("location_missing")
    if conversation is not None and (
        conversation.needs_human or conversation.mode == ConversationMode.HUMAN
    ):
        tags.append("needs_human")
    return tags


def normalize_manual_tag_keys(keys: list[str]) -> list[str]:
    return [payload["key"] for payload in normalize_manual_tag_payloads(keys, [])]


def normalize_manual_tag_payloads(
    keys: list[str],
    tags: list[dict],
) -> list[dict[str, str]]:
    normalized: list[str] = []
    payloads: list[dict[str, str]] = []
    seen: set[str] = set()

    def add(raw_key: str, raw_label: str | None = None, tone: str = "info") -> None:
        source = (raw_label or raw_key or "").strip()
        if not source:
            return
        key = normalize_manual_tag_key(raw_key or source)
        if not key or key in _SYSTEM_TAG_KEYS or key in seen:
            return
        if key in _MANUAL_TAG_KEYS:
            meta = _TAG_META[key]
            label = str(meta["label"])
            tag_tone = str(meta["tone"])
        else:
            label = source[:64]
            tag_tone = tone if tone in {"good", "warn", "danger", "info"} else "info"
        normalized.append(key)
        payloads.append({"key": key, "label": label, "tone": tag_tone})
        seen.add(key)

    for key in keys:
        add(key)

    for tag in tags:
        key = str(tag.get("key") or tag.get("label") or "")
        label = tag.get("label")
        if label is not None:
            label = str(label)
        add(key, label, str(tag.get("tone") or "info"))

    return payloads[:12]


def normalize_manual_tag_key(value: str) -> str:
    value = value.strip()
    if not value:
        return ""
    if value in _TAG_META:
        return value
    if value.startswith("custom_") and re.fullmatch(r"custom_[a-z0-9_]{1,40}", value):
        return value
    vietnamese_safe = value.replace("đ", "d").replace("Đ", "D")
    ascii_value = (
        unicodedata.normalize("NFKD", vietnamese_safe)
        .encode("ascii", "ignore")
        .decode("ascii")
        .lower()
    )
    key = re.sub(r"[^a-z0-9]+", "_", ascii_value).strip("_")
    if not key:
        key = re.sub(r"\s+", "_", value.lower()).strip("_")
        key = re.sub(r"[^\w]+", "_", key).strip("_")
    if not key:
        return ""
    custom_key = f"custom_{key[:40]}"
    if custom_key in _SYSTEM_TAG_KEYS:
        return ""
    return custom_key
