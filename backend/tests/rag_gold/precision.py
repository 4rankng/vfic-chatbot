"""Pure precision / recall / MRR scoring for the RAG gold gate.

These functions take *plain lists of chunk IDs* — they do not depend on the
row representation, so they work equally well for the in-process gold gate
and for any future DB-backed variant.

Notation:
  - ``expected``: the chunk IDs a case says SHOULD be retrieved.
  - ``retrieved``: the chunk IDs the pipeline actually returned, in ranked order.
  - ``k``: the cutoff for the metric (``precision_at_3`` uses the first 3).

Definitions used here match the standard IR definitions:
  - ``precision_at_k`` = (# relevant in top-k) / k
  - ``recall_at_k``    = (# relevant in top-k) / (# relevant)
  - ``mrr``            = 1 / rank of the first relevant item, or 0 if none
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CaseScore:
    """Per-case scoring result, captured for the benchmark report."""

    case_id: str
    precision_at_3: float
    precision_at_5: float
    recall_at_10: float
    first_hit_rank: int  # 0 means no hit
    mrr: float
    expected_count: int
    retrieved_count: int
    bait: bool
    passed: bool


def precision_at_k(retrieved: list[str], expected: set[str], k: int) -> float:
    """Fraction of the top-k retrieved IDs that are in ``expected``.

    Returns 0.0 when ``k <= 0``. Pads with zeroes implicitly — retrieving
    fewer than k items counts the missing slots as misses.
    """
    if k <= 0:
        return 0.0
    top = list(retrieved)[:k]
    if not top:
        return 0.0
    hits = sum(1 for chunk_id in top if chunk_id in expected)
    return hits / k


def recall_at_k(retrieved: list[str], expected: set[str], k: int) -> float:
    """Fraction of ``expected`` IDs that appear in the top-k retrieved."""
    if not expected:
        # No expected IDs — convention: undefined, scored as 1.0 so the metric
        # does not pull the average down for bait cases (handled separately).
        return 1.0
    if k <= 0:
        return 0.0
    top = set(retrieved[:k])
    hits = len(top & expected)
    return hits / len(expected)


def first_relevant_rank(retrieved: list[str], expected: set[str]) -> int:
    """1-based rank of the first relevant item, or 0 if none.

    Used for MRR. Bait cases (empty ``expected``) always return 0.
    """
    if not expected:
        return 0
    for rank, chunk_id in enumerate(retrieved, start=1):
        if chunk_id in expected:
            return rank
    return 0


def reciprocal_rank(retrieved: list[str], expected: set[str]) -> float:
    """1 / first_relevant_rank, or 0 when there is no relevant item."""
    rank = first_relevant_rank(retrieved, expected)
    return 1.0 / rank if rank > 0 else 0.0


def score_case(
    case_id: str,
    retrieved: list[str],
    expected: set[str],
    *,
    bait: bool = False,
) -> CaseScore:
    """Score one case across precision@3, precision@5, recall@10, MRR.

    ``passed`` semantics:
      - Bait cases pass when nothing is retrieved (precision@3 == 0 is the
        only acceptable outcome for a hallucination-bait query).
      - Non-bait cases pass when at least one expected chunk appears in the
        top-3 (``precision_at_3 > 0``).
    """
    p3 = precision_at_k(retrieved, expected, 3)
    p5 = precision_at_k(retrieved, expected, 5)
    r10 = recall_at_k(retrieved, expected, 10)
    rank = first_relevant_rank(retrieved, expected)
    mrr = 1.0 / rank if rank > 0 else 0.0
    if bait:
        passed = p3 == 0.0 and p5 == 0.0
    else:
        passed = p3 > 0.0
    return CaseScore(
        case_id=case_id,
        precision_at_3=p3,
        precision_at_5=p5,
        recall_at_10=r10,
        first_hit_rank=rank,
        mrr=mrr,
        expected_count=len(expected),
        retrieved_count=len(retrieved),
        bait=bait,
        passed=passed,
    )


@dataclass(frozen=True)
class AggregateScore:
    """Aggregate metrics across all cases in a run."""

    case_count: int
    passed: int
    pass_rate: float
    mean_precision_at_3: float
    mean_precision_at_5: float
    mean_recall_at_10: float
    mean_mrr: float
    bait_count: int
    bait_passed: int


def aggregate(scores: list[CaseScore]) -> AggregateScore:
    """Average per-case metrics into an aggregate report.

    Bait cases are included in the average (their precision@k is 0.0 by
    construction when ``passed``, which is the correct contribution to the
    mean). ``bait_passed`` is reported separately so regressions in
    abstain-behavior are visible.
    """
    n = len(scores)
    if n == 0:
        return AggregateScore(
            case_count=0,
            passed=0,
            pass_rate=0.0,
            mean_precision_at_3=0.0,
            mean_precision_at_5=0.0,
            mean_recall_at_10=0.0,
            mean_mrr=0.0,
            bait_count=0,
            bait_passed=0,
        )
    bait_scores = [s for s in scores if s.bait]
    passed = sum(1 for s in scores if s.passed)
    return AggregateScore(
        case_count=n,
        passed=passed,
        pass_rate=passed / n,
        mean_precision_at_3=sum(s.precision_at_3 for s in scores) / n,
        mean_precision_at_5=sum(s.precision_at_5 for s in scores) / n,
        mean_recall_at_10=sum(s.recall_at_10 for s in scores) / n,
        mean_mrr=sum(s.mrr for s in scores) / n,
        bait_count=len(bait_scores),
        bait_passed=sum(1 for s in bait_scores if s.passed),
    )
