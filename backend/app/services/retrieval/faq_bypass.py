"""Deterministic, non-LLM FAQ bypass cascade (exact -> rule -> hybrid -> gate).

Pure functions + tunable code constants. No DB, no embedder, no graph imports —
trivially unit-testable. The adapter in :mod:`app.graph.factories` composes this
with :class:`RetrievalRepository` + the shared cached embedder.

Design goal: high *precision*, not recall. A wrong FAQ auto-answer is worse than
no FAQ hit, so the gate abstains (returns ``None``) unless a candidate clearly
matches. Tuning happens by editing the constants below, not via env/Settings.

Cascade order (per query):

  1. EXACT  — normalized query equals a stored question variant -> accept (1.0)
  2. RULE   — accepted candidate must satisfy required_terms / forbidden_terms
  3. HYBRID — vector (cosine) + trigram similarity, deterministically re-ranked
  4. GATE   — score >= SCORE_FLOOR AND (top1 - top2) >= MARGIN, else abstain
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.core.text import normalize_vietnamese_text

# ── tunable constants (edit here to tune) ────────────────────────────────────
SCORE_FLOOR = 0.78            # final hybrid score required to accept
MARGIN = 0.12                 # top1 must beat top2 by at least this
VECTOR_WEIGHT = 0.60          # hybrid re-rank weight for the vector arm
TRIGRAM_WEIGHT = 0.40         # hybrid re-rank weight for the trigram arm
TRIGRAM_THRESHOLD = 0.30      # passed to match_faq_lexical SQL WHERE
TOP_K = 5                     # candidates fetched per arm
EXACT_MIN_CHARS = 3           # skip exact tier for very short normalized queries
CANDIDATE_VECTOR_FLOOR = 0.55  # looser SQL floor for vector candidate generation

TIER_EXACT = "exact"
TIER_HYBRID = "hybrid"
TIER_NONE = "none"
DECISION_ACCEPT = "accept"
DECISION_ABSTAIN = "abstain"


@dataclass
class Scored:
    """A re-ranked FAQ candidate."""

    faq_id: str
    answer: str
    vec_sim: float
    tri_sim: float
    score: float  # weighted; 1.0 for an exact match
    required_terms: list[str] = field(default_factory=list)
    forbidden_terms: list[str] = field(default_factory=list)


@dataclass
class FaqBypassDecision:
    """Outcome of the cascade for one query, with detail for logging/tuning."""

    decision: str  # accept / abstain
    tier: str  # exact / hybrid / none
    scored: Scored | None
    top1_score: float
    top2_score: float
    margin: float
    reason: str


def answer_from_row(row: Any) -> str:
    """Prefer the precise answer fields over raw content (mirrors _format_knowledge_row)."""
    for attr in ("source_quote", "summary", "content"):
        val = getattr(row, attr, None)
        if val:
            return str(val)
    return ""


def row_rule_terms(row: Any) -> tuple[list[str], list[str]]:
    required = list(getattr(row, "required_terms", None) or [])
    forbidden = list(getattr(row, "forbidden_terms", None) or [])
    return required, forbidden


def build_exact_map(rows: list[Any]) -> dict[str, str]:
    """Map each normalized question variant to its FAQ id.

    Built from the candidate rows' ``questions`` arrays. A FAQ whose variant
    matches the query exactly will also appear in the candidate set (its
    ``search_text`` contains the variant), so the matched row is reachable for
    the answer + rule check.
    """
    mapping: dict[str, str] = {}
    for row in rows:
        faq_id = str(getattr(row, "id", ""))
        for q in getattr(row, "questions", None) or []:
            nq = normalize_vietnamese_text(str(q))
            if nq:
                mapping.setdefault(nq, faq_id)
    return mapping


def rerank(
    vector_rows: list[Any],
    lexical_rows: list[Any],
    *,
    w_v: float = VECTOR_WEIGHT,
    w_t: float = TRIGRAM_WEIGHT,
) -> list[Scored]:
    """Merge vector + trigram candidates by FAQ id into a weighted, desc-sorted list.

    Weights are normalized over the arms that actually fired for each candidate,
    so a candidate seen by only one arm is scored by that arm alone.
    """
    vec_by_id = {str(r.id): r for r in vector_rows}
    lex_by_id = {str(r.id): r for r in lexical_rows}
    scored: list[Scored] = []
    for faq_id in vec_by_id.keys() | lex_by_id.keys():
        vrow = vec_by_id.get(faq_id)
        lrow = lex_by_id.get(faq_id)
        vec_sim = float(getattr(vrow, "similarity", 0.0) or 0.0) if vrow else 0.0
        tri_sim = float(getattr(lrow, "similarity", 0.0) or 0.0) if lrow else 0.0
        weight_sum = 0.0
        score = 0.0
        if vrow is not None:
            score += w_v * vec_sim
            weight_sum += w_v
        if lrow is not None:
            score += w_t * tri_sim
            weight_sum += w_t
        score = score / weight_sum if weight_sum else 0.0
        row = vrow or lrow
        required, forbidden = row_rule_terms(row)
        scored.append(
            Scored(
                faq_id=faq_id,
                answer=answer_from_row(row),
                vec_sim=vec_sim,
                tri_sim=tri_sim,
                score=score,
                required_terms=required,
                forbidden_terms=forbidden,
            )
        )
    scored.sort(key=lambda s: s.score, reverse=True)
    return scored


def _rule_ok(scored: Scored, q_norm: str) -> str:
    """Return ``"ok"`` or a snake_case rejection reason."""
    for fb in scored.forbidden_terms:
        nfb = normalize_vietnamese_text(fb)
        if nfb and nfb in q_norm:
            return "forbidden_present"
    for rt in scored.required_terms:
        nrt = normalize_vietnamese_text(rt)
        if nrt and nrt not in q_norm:
            return "required_missing"
    return "ok"


def decide(
    query: str,
    exact_map: dict[str, str],
    scored: list[Scored],
    *,
    score_floor: float = SCORE_FLOOR,
    margin: float = MARGIN,
    exact_min_chars: int = EXACT_MIN_CHARS,
) -> FaqBypassDecision:
    """Run the cascade gate. Abstains (never raises) on any uncertainty."""
    q_norm = normalize_vietnamese_text(query)
    top1 = scored[0] if scored else None
    top2 = scored[1] if len(scored) > 1 else None
    top1_score = top1.score if top1 else 0.0
    top2_score = top2.score if top2 else 0.0
    actual_margin = top1_score - top2_score

    # TIER 0 — exact normalized-match (only for non-trivial queries). The matched
    # FAQ must also be a candidate so we have its answer + rule terms.
    if len(q_norm.replace(" ", "")) >= exact_min_chars and q_norm in exact_map:
        faq_id = exact_map[q_norm]
        cand = next((s for s in scored if s.faq_id == faq_id), None)
        if cand is not None:
            reason = _rule_ok(cand, q_norm)
            if reason == "ok":
                return FaqBypassDecision(
                    DECISION_ACCEPT, TIER_EXACT, cand, 1.0, top2_score,
                    1.0 - top2_score, "exact_match",
                )
            return FaqBypassDecision(
                DECISION_ABSTAIN, TIER_EXACT, cand, 1.0, top2_score,
                1.0 - top2_score, f"exact_blocked:{reason}",
            )

    # TIER 2 — hybrid gate
    if top1 is None:
        return FaqBypassDecision(
            DECISION_ABSTAIN, TIER_NONE, None, 0.0, 0.0, 0.0, "no_candidates"
        )
    if top1_score < score_floor:
        return FaqBypassDecision(
            DECISION_ABSTAIN, TIER_HYBRID, top1, top1_score, top2_score,
            actual_margin, f"below_floor:{top1_score:.2f}",
        )
    if actual_margin < margin:
        return FaqBypassDecision(
            DECISION_ABSTAIN, TIER_HYBRID, top1, top1_score, top2_score,
            actual_margin, f"margin_fail:{actual_margin:.2f}",
        )
    reason = _rule_ok(top1, q_norm)
    if reason != "ok":
        return FaqBypassDecision(
            DECISION_ABSTAIN, TIER_HYBRID, top1, top1_score, top2_score,
            actual_margin, f"rule_blocked:{reason}",
        )
    return FaqBypassDecision(
        DECISION_ACCEPT, TIER_HYBRID, top1, top1_score, top2_score,
        actual_margin, "hybrid_match",
    )


__all__ = [
    "SCORE_FLOOR",
    "MARGIN",
    "VECTOR_WEIGHT",
    "TRIGRAM_WEIGHT",
    "TRIGRAM_THRESHOLD",
    "TOP_K",
    "EXACT_MIN_CHARS",
    "CANDIDATE_VECTOR_FLOOR",
    "TIER_EXACT",
    "TIER_HYBRID",
    "TIER_NONE",
    "DECISION_ACCEPT",
    "DECISION_ABSTAIN",
    "Scored",
    "FaqBypassDecision",
    "answer_from_row",
    "build_exact_map",
    "rerank",
    "decide",
]
