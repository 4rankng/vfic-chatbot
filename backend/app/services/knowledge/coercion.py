"""Pure validation/coercion of LLM outputs into the chunk/feature column shapes.

No I/O, no DB, no LLM — same input always yields same output. Unit-tested directly in
``tests/test_knowledge_coercion.py``. These helpers are the seam that lets the pipeline
orchestrator stay free of inline parsing/normalisation.
"""

from __future__ import annotations

import json
import re
from typing import Any

from app.services.knowledge.prompts import PRODUCT_FEATURE_SYSTEM_PROMPT

CATEGORIES = ("job", "salary", "schedule", "policy", "faq", "contact", "benefits", "other")
_CONFIDENCE = ("high", "medium", "low")


class DigestError(Exception):
    """Raised when the LLM output cannot be coerced into the unit schema."""


def _coerce_unit(raw: Any) -> dict:
    if not isinstance(raw, dict):
        raise DigestError(f"unit is not an object: {type(raw).__name__}")
    content = (raw.get("content") or "").strip()
    if not content:
        raise DigestError("unit missing non-empty 'content'")
    cat = str(raw.get("category") or "other").strip().lower()
    if cat not in CATEGORIES:
        cat = "other"
    conf = str(raw.get("confidence") or "medium").strip().lower()
    if conf not in _CONFIDENCE:
        conf = "medium"
    questions = raw.get("questions") or []
    if not isinstance(questions, list):
        questions = [str(questions)]
    questions = [str(q).strip() for q in questions if str(q).strip()]
    entities = raw.get("entities") or {}
    if not isinstance(entities, dict):
        entities = {}
    return {
        "content": content,
        "source_quote": (str(raw.get("source_quote") or "").strip() or None),
        "summary": (str(raw.get("summary") or "").strip() or None),
        "questions": questions,
        "category": cat,
        "entities": entities,
        "source_anchor": (str(raw.get("source_anchor") or "").strip() or None),
        "confidence": conf,
        "is_inference": bool(raw.get("is_inference", False)),
    }


def validate_digest(payload: Any) -> tuple[str, list[dict]]:
    """Validate/coerce the LLM digest payload -> (document_summary, units)."""
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise DigestError(f"payload is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise DigestError("top-level payload is not an object")
    units_raw = payload.get("units")
    if not isinstance(units_raw, list):
        raise DigestError("'units' is missing or not a list")
    units = [_coerce_unit(u) for u in units_raw]
    summary = str(payload.get("document_summary") or "").strip()
    return summary, units


# ------------------------------------------------------------ product features
def _product_feature_prompt(catalog_rows: Any) -> str:
    """Build the extraction system prompt with the live catalog inlined.

    Inlining the catalog (rather than hard-coding keys) keeps prompt + seed in sync; the
    count is interpolated from the rows so disabling a criterion (migration 0009) flows
    through without a prompt edit.
    """
    lines = []
    for c in catalog_rows:
        q = (c.worker_question_vi or "").strip()
        suffix = f' — câu hỏi ứng viên: "{q}"' if q else ""
        lines.append(f"- {c.feature_key}: {c.name_vi}{suffix}")
    return PRODUCT_FEATURE_SYSTEM_PROMPT.replace("{{FEATURES}}", "\n".join(lines)).replace(
        "{{COUNT}}", str(len(catalog_rows))
    )


def _missing_feature_text(catalog_row: Any) -> str:
    q = (catalog_row.worker_question_vi or catalog_row.name_vi or "").strip()
    return f"Tin tuyển dụng chưa ghi rõ: {q}."


def _clamp_strength(value: Any) -> float:
    try:
        s = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        s = 0.5
    return round(max(0.0, min(1.0, s)), 2)


def _coerce_feature(raw: Any, catalog_row: Any, *, source_text: str | None = None) -> dict:
    """Coerce one LLM feature object into the job_feature_values column shape."""
    if not isinstance(raw, dict):
        return {
            "value_text": _missing_feature_text(catalog_row),
            "value_json": {},
            "is_highlight": False,
            "is_missing": True,
            "needs_clarification": False,
            "evidence_text": None,
            "strength_score": 0.0,
        }
    value_text = str(raw.get("value_text") or "").strip()
    is_missing = bool(raw.get("is_missing", False)) or not value_text
    if is_missing:
        value_text = value_text or _missing_feature_text(catalog_row)
    value_json = raw.get("value_json")
    if not isinstance(value_json, dict):
        value_json = {}
    evidence = str(raw.get("evidence_text") or raw.get("evidence") or "").strip() or None
    # Extraction is grounded in a quote, not merely the model's assertion that
    # a benefit exists. Whitespace folding accepts source formatting changes.
    if source_text is not None and not is_missing:
        folded_source = re.sub(r"\s+", " ", source_text).strip()
        folded_quote = re.sub(r"\s+", " ", evidence or "").strip()
        if not folded_quote or folded_quote not in folded_source:
            return {
                "value_text": _missing_feature_text(catalog_row), "value_json": {},
                "is_highlight": False, "is_missing": True, "needs_clarification": True,
                "evidence_text": None, "strength_score": 0.0,
            }
    return {
        "value_text": value_text,
        "value_json": value_json,
        "is_highlight": bool(raw.get("is_highlight", False)) and not is_missing,
        "is_missing": is_missing,
        "needs_clarification": bool(raw.get("needs_clarification", False)),
        "evidence_text": evidence,
        "strength_score": _clamp_strength(raw.get("strength_score")),
    }


def _parse_json_lenient(raw: str) -> Any:
    """Parse JSON, tolerating model-output quirks: a surrounding ```json fence, and
    M2.7 ``<think>…</think>`` reasoning leaked into the content before the JSON.

    MiniMax's M2 reasoning models always emit chain-of-thought; when it is routed into
    ``content`` (rather than a separate reasoning field) it prefixes the JSON object and
    breaks ``json.loads``. Strip closed blocks first, then a trailing unclosed block
    (truncated output) so a half-finished reasoning block cannot shadow the JSON.
    """
    s = (raw or "").strip()
    if "<think" in s.lower():
        s = re.sub(r"<think\b[^>]*>[\s\S]*?</think\s*>", "", s, flags=re.IGNORECASE)
        s = re.sub(r"<think\b[^>]*>[\s\S]*$", "", s, flags=re.IGNORECASE)
        s = s.strip()
    if s.startswith("```"):
        s = s.split("```", 2)
        # s == ['', 'json\n...body...', ' maybe trailing']  or  ['', '\nbody\n','...']
        s = s[1] if len(s) > 1 else ""
        if s.lower().startswith("json"):
            s = s[4:]
    return json.loads(s.strip() or "{}")
