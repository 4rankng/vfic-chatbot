"""Deterministic bullet-list completion for extracted transportation records.

The category-plan importer maps a project brief into grounded records through
the extraction LLM. Providers routinely handle the brief's multi-line bullet
lists inconsistently: sibling bullets on one line map fine, while a bullet
whose value is a nested list ("Tuyến & điểm đón cố định:" followed by
``1.``…``4.`` lines) or an other-areas condition ("Các khu vực khác: … gom đủ
từ 5 người trở lên") is dropped from the transportation record — CHAT-13's
import published ``stops: []`` and ``notes: null`` for exactly such a section.

Because briefs follow one fixed template (``templates/mau-kb-du-an.md``), the
recovery is deterministic: re-read the source under the category's own heading,
parse its labeled bullets and nested ordered lists, and fill ONLY the fields
the extractor left empty. Every completed value is a verbatim slice of that
section, so the grounding pass that runs right after this completion still
verifies it end to end — the completion can never smuggle in unquoted text.
"""

from __future__ import annotations

import re
import unicodedata

from app.services.knowledge.coercion import source_tokens

_LABEL_SPLIT_RE = re.compile(r"^([^:\n]+?)\s*:\s*(.*)$")
_ORDERED_ITEM_RE = re.compile(r"^\s*(\d+)[.)]\s+(.+?)\s*\.?\s*$")
_BULLET_RE = re.compile(r"^\s*-\s+(.+)$")
_HEADING_RE = re.compile(r"^(#{1,6})\s*(.+?)\s*#*\s*$")

# Template labels whose nested ordered list enumerates the fixed stops.
_STOP_LIST_LABELS = ("tuyen", "diem don", "diem dung", "lo trinh", "lich trinh")
# Template labels carrying the other-areas pickup condition (the KB "Ghi chú").
_AREA_NOTE_LABELS = ("khu vuc khac", "dia diem khac", "ghi chu", "luu y")


def _fold(value: str) -> str:
    """Case/diacritics/punctuation-insensitive label form for template labels."""
    text = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", text.casefold()).strip()


def _is_stop_list_label(folded_label: str) -> bool:
    """Complete-word prefix match: 'tuyen diem don co dinh' → 'tuyen diem don'."""
    return any(
        folded_label == variant or folded_label.startswith(f"{variant} ")
        for variant in _STOP_LIST_LABELS
    )


def _is_area_note_label(folded_label: str) -> bool:
    """Substring match: 'cac khu vuc khac' carries 'khu vuc khac'."""
    padded = f" {folded_label} "
    return any(f" {variant} " in padded for variant in _AREA_NOTE_LABELS)


def brief_category_section(source: str, heading_variants: tuple[str, ...]) -> str:
    """Text under the brief heading matching any variant, until the next heading.

    Heading matching is fold-equality on the heading text (or a prefix match for
    labels the template decorates), so ``## Đưa đón & lịch xe`` and a plain
    ``## Đưa đón`` both resolve. Returns '' when the source has no such heading
    — the caller then has nothing deterministic to add.
    """
    folded_variants = tuple(_fold(variant) for variant in heading_variants)
    lines = source.splitlines()
    start = end = None
    for index, line in enumerate(lines):
        match = _HEADING_RE.match(line)
        if not match:
            continue
        folded = _fold(match.group(2))
        if start is None and any(
            folded == variant or folded.startswith(variant) for variant in folded_variants
        ):
            start = index + 1
            continue
        if start is not None:
            end = index
            break
    if start is None:
        return ""
    return "\n".join(lines[start:end])


def _stop_covered(existing_names: list[str], item: str) -> bool:
    """True when a parsed list item is already among the record's stop names.

    Comparison is token-run equivalence both ways: the extractor may shorten a
    source line ("1. Tuyến Đồ Sơn." → "Tuyến Đồ Sơn") and a list item may wrap
    a stop name plus extra words — either direction still means covered.
    """
    item_tokens = source_tokens(item)
    if not item_tokens:
        return True
    for name in existing_names:
        name_tokens = source_tokens(name)
        if not name_tokens:
            continue
        if name_tokens == item_tokens or (
            f" {name_tokens} " in f" {item_tokens} " or f" {item_tokens} " in f" {name_tokens} "
        ):
            return True
    return False


def complete_transportation_record(record: dict, source: str) -> dict:
    """Fill ``stops`` / ``notes`` the extractor dropped, from the brief's bullets.

    Only empty fields are filled — plus the one CHAT-13 gap: an extractor that
    maps only a PREFIX of the section's ordered stop list (dropping the trailing
    items) gets the missing items appended, in list order, after the stops it
    kept. The filled stop names keep their list order (``order`` = 1..n) and are
    the source lines verbatim (trailing sentence period stripped — still a
    verbatim token run). Notes take the FIRST matching area-condition bullet.
    """
    section = brief_category_section(source, ("Đưa đón & lịch xe", "Đưa đón"))
    if not section:
        return record
    filled = dict(record)
    needs_stops = not filled.get("stops")
    needs_notes = not (filled.get("notes") or "").strip()
    existing_stop_names = [
        str(stop.get("name") or "") for stop in (filled.get("stops") or [])
    ]

    ordered_items: list[str] = []
    area_notes: list[str] = []
    in_stop_list = False
    for raw in section.splitlines():
        line = raw.rstrip()
        if not line.strip():
            continue
        ordered = _ORDERED_ITEM_RE.match(line)
        bullet = _BULLET_RE.match(line)
        if not ordered and not bullet:
            in_stop_list = False
            continue
        # Label detection on the bold-stripped bullet text: "- **Tuyến:**
        # value" and "- Tuyến: value" are the same template shape.
        plain = (bullet.group(1) if bullet else "").replace("**", "").strip()
        labeled = _LABEL_SPLIT_RE.match(plain) if plain else None
        if labeled:
            folded_label = _fold(labeled.group(1))
            value = labeled.group(2).strip()
            if _is_stop_list_label(folded_label):
                in_stop_list = True
                if value:
                    ordered_items.append(value)
                continue
            in_stop_list = False
            if needs_notes and _is_area_note_label(folded_label) and value:
                area_notes.append(value)
            continue
        # Plain list-item line: numbered, or an indented nested bullet. Top-level
        # unlabeled bullets are prose outside the list and close it.
        nested_bullet = bool(bullet) and line[:1].isspace()
        if ordered is not None:
            content = ordered.group(2).strip()
        elif bullet is not None:
            content = bullet.group(1).strip()
        else:  # pragma: no cover - one of the two matched above
            continue
        if in_stop_list and content and (ordered is not None or nested_bullet):
            ordered_items.append(content)
            continue
        in_stop_list = False

    if needs_stops and ordered_items:
        filled["stops"] = [
            {"order": index, "name": name, "time": None, "address": None}
            for index, name in enumerate(ordered_items, start=1)
        ]
    elif filled.get("stops") and ordered_items:
        # The extractor kept a prefix of the section's list: append the items it
        # dropped, in list order, so the ≥5-people rule cannot fall off the end.
        next_order = max(int(stop.get("order") or 0) for stop in filled["stops"]) + 1
        for item in ordered_items:
            if _stop_covered(existing_stop_names, item):
                continue
            filled["stops"].append(
                {"order": next_order, "name": item, "time": None, "address": None}
            )
            next_order += 1
    if needs_notes and area_notes:
        filled["notes"] = area_notes[0]
    return filled
