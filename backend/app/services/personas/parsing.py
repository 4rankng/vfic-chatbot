"""Pure persona-markdown parsing (no framework/service imports).

Split out of the old ``persona_service`` so it can be reused without dragging in
SQLAlchemy / FastAPI. Raises ``ValueError`` for malformed input.
"""

from __future__ import annotations

from typing import Any


def parse_persona_markdown(text: str) -> tuple[str, str | None, str | None, str]:
    """Parse a persona markdown file with optional YAML frontmatter.

    Returns ``(name, slug_or_None, notes_or_None, body_md)``.
    Raises ``ValueError`` if *name* is missing/blank or body is empty.
    """
    errors: list[str] = []

    # --- frontmatter split (hand-rolled, same shape as knowledge/canonical.py) ---
    if not text.startswith("---\n"):
        # No frontmatter — treat entire file as body; name will fail validation.
        fm: dict[str, Any] = {}
        body = text.strip()
    else:
        end = text.find("\n---", 4)
        if end == -1:
            errors.append("frontmatter closing --- delimiter is missing")
            fm, body = {}, text
        else:
            raw = text[4:end].strip("\n")
            body = text[end + 4 :].lstrip("\r\n")
            fm = _parse_persona_frontmatter(raw, errors)

    if errors:
        raise ValueError("; ".join(errors))

    name = str(fm.get("name", "")).strip()
    if not name:
        raise ValueError("Frontmatter thiếu 'name' — tên Agent là bắt buộc.")

    body_md = body.strip()
    if not body_md:
        raise ValueError("Nội dung Agent (body) trống — cần ít nhất 1 phần.")

    slug = str(fm.get("slug", "")).strip() or None
    notes = str(fm.get("notes", "")).strip() or None
    return name, slug, notes, body_md


def _parse_persona_frontmatter(raw: str, errors: list[str]) -> dict[str, Any]:
    """Minimal key:value frontmatter parser (flat only, no nested objects)."""
    out: dict[str, Any] = {}
    current_key: str | None = None
    for line_no, line in enumerate(raw.splitlines(), start=1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if ":" not in line:
            errors.append(f"frontmatter line {line_no}: expected key: value")
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        current_key = key  # noqa: F841 — preserved from original parser
        value = value.strip()
        out[key] = value  # persona frontmatter is always scalar
    return out
