"""Vietnamese RAG gold-set precision CI gate.

Asserts the post-retrieval pipeline (fusion → rerank, with MMR + sha256 dedup
once Phases 2 and 4 land) holds its baseline precision against a checked-in
Vietnamese gold set.

**Scope** (see `plans/260718-1946-kb-rag-quality-and-grounding/phase-01-*.md`):
the gate uses **canned embeddings** checked into
`backend/tests/fixtures/rag_gold/embeddings.json` so CI runs offline and
deterministic. It catches regressions in fusion, rerank, and dedup. It does
NOT catch true vector-recall regressions — an embedding-model swap or HNSW
`ef_search` misconfiguration would not be caught here.

Two run modes:

1. **Baseline mode (default)** — when `baseline.json` is checked in, the gate
   asserts the achieved `mean_precision_at_3` is at least the recorded value.
   This is the CI-critical mode.
2. **Shape mode** — when `baseline.json` is absent (e.g. before the seed
   script has been run on a fresh checkout), the gate runs every case to
   confirm the loader + runner + precision code work end-to-end, but skips
   the numeric regression check. This keeps the suite green during Phase 1
   bring-up; once `seed_rag_gold_embeddings.py` runs once and commits
   `embeddings.json` + `baseline.json`, baseline mode takes over.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.rag_gold.loader import (
    BASELINE_JSON,
    EMBEDDINGS_JSON,
    load_cases,
    load_chunks,
    load_embeddings,
)
from tests.rag_gold.precision import aggregate, score_case
from tests.services_runner import build_rows_for_case


@pytest.fixture(scope="module")
def gold_bundle() -> dict:
    """Load cases, chunks, and embeddings once for the whole module."""
    cases = load_cases()
    chunks = load_chunks()
    embeddings = load_embeddings()
    return {"cases": cases, "chunks": chunks, "embeddings": embeddings}


@pytest.fixture(scope="module")
def gold_scores(gold_bundle: dict) -> list:
    """Run the full pipeline for every case and score it."""
    cases = gold_bundle["cases"]
    chunks = gold_bundle["chunks"]
    embeddings = gold_bundle["embeddings"]
    if not embeddings:
        pytest.skip(
            f"{EMBEDDINGS_JSON} missing — run "
            "`backend/scripts/seed_rag_gold_embeddings.py` once to generate it."
        )
    scores = []
    for case in cases:
        rows = build_rows_for_case(case, chunks, embeddings)
        retrieved_ids = [getattr(row, "id", None) for row in rows]
        scores.append(
            score_case(
                case_id=case.id,
                retrieved=[i for i in retrieved_ids if i],
                expected=set(case.expected_chunk_ids),
                bait=case.bait,
            )
        )
    return scores


def test_gold_set_has_minimum_case_count() -> None:
    """Fixture must have at least 40 cases and 6 hallucination-bait cases."""
    cases = load_cases()
    bait_count = sum(1 for c in cases if c.bait)
    assert len(cases) >= 40, f"gold set has {len(cases)} cases, expected >= 40"
    assert bait_count >= 6, f"gold set has {bait_count} bait cases, expected >= 6"


def test_chunks_have_unique_ids() -> None:
    """Chunk IDs must be unique so retrieval results are unambiguous."""
    chunks = load_chunks()
    ids = [c.id for c in chunks]
    assert len(ids) == len(set(ids)), "duplicate chunk id in chunks.yaml"


def test_expected_chunk_ids_reference_real_chunks() -> None:
    """Every expected_chunk_id in cases.yaml must exist in chunks.yaml."""
    chunks = load_chunks()
    cases = load_cases()
    chunk_ids = {c.id for c in chunks}
    for case in cases:
        missing = case.expected_chunk_ids - chunk_ids
        assert not missing, (
            f"case {case.id!r} references unknown chunk ids: {sorted(missing)}"
        )


def test_every_bait_case_has_empty_expected(gold_bundle: dict) -> None:
    """Bait cases must have empty expected_chunk_ids by construction."""
    for case in gold_bundle["cases"]:
        if case.bait:
            assert not case.expected_chunk_ids, (
                f"bait case {case.id!r} must have empty expected_chunk_ids"
            )


def test_no_bait_case_returns_confident_match(gold_scores: list) -> None:
    """Every hallucination-bait case must abstain (return zero relevant hits).

    This is the core anti-hallucination assertion: a query asking about a
    fact the KB does NOT contain (e.g. "lương 50 triệu") must not pull in a
    chunk that claims otherwise with high confidence. A bait case "passes"
    only when precision@3 == 0 (no relevant retrieved rows). If the lexical
    arm pulls in unrelated chunks, the bait case is allowed to retrieve them —
    only relevant hits fail the case.

    Note: this guards *retrieval* abstention, not *reply* abstention. Reply
    abstention is enforced by Phase 3 grounding and the agent prompt.
    """
    bait_scores = [s for s in gold_scores if s.bait]
    assert bait_scores, "no bait cases found in gold set"
    failed = [s.case_id for s in bait_scores if not s.passed]
    assert not failed, (
        f"{len(failed)}/{len(bait_scores)} bait cases returned relevant hits: {failed}"
    )


def test_mean_precision_at_3_meets_baseline(gold_scores: list) -> None:
    """The achieved mean precision@3 must not regress below the recorded baseline.

    Baseline is captured by `seed_rag_gold_embeddings.py` and stored in
    `baseline.json`. The gate compares against it to detect regressions in
    fusion / rerank / dedup code paths. Improvements are always allowed;
    intentional lowerings must update `baseline.json` with a PR note.
    """
    if not BASELINE_JSON.exists():
        pytest.skip(
            f"{BASELINE_JSON} missing — run "
            "`backend/scripts/seed_rag_gold_embeddings.py` to capture baseline."
        )
    baseline = json.loads(BASELINE_JSON.read_text(encoding="utf-8"))
    expected_p3 = float(baseline["precision_at_3"])
    actual = aggregate(gold_scores)
    # Allow a tiny epsilon for floating-point noise in cosine precomputation.
    assert actual.mean_precision_at_3 + 1e-9 >= expected_p3, (
        f"mean_precision_at_3 regressed: baseline={expected_p3:.4f} "
        f"actual={actual.mean_precision_at_3:.4f}"
    )


def test_mean_mrr_meets_baseline(gold_scores: list) -> None:
    """Mean reciprocal rank must not regress below the recorded baseline."""
    if not BASELINE_JSON.exists():
        pytest.skip(f"{BASELINE_JSON} missing — see seed_rag_gold_embeddings.py")
    baseline = json.loads(BASELINE_JSON.read_text(encoding="utf-8"))
    expected_mrr = float(baseline["mrr"])
    actual = aggregate(gold_scores)
    assert actual.mean_mrr + 1e-9 >= expected_mrr, (
        f"mean_mrr regressed: baseline={expected_mrr:.4f} "
        f"actual={actual.mean_mrr:.4f}"
    )


def _write_local_summary(gold_scores: list, tmp_path: Path) -> Path:
    """Helper for the manual-summary test below — kept pure-file, no network."""
    summary = aggregate(gold_scores)
    out = tmp_path / "gold_summary.json"
    out.write_text(
        json.dumps(
            {
                "case_count": summary.case_count,
                "passed": summary.passed,
                "pass_rate": summary.pass_rate,
                "mean_precision_at_3": summary.mean_precision_at_3,
                "mean_precision_at_5": summary.mean_precision_at_5,
                "mean_recall_at_10": summary.mean_recall_at_10,
                "mean_mrr": summary.mean_mrr,
                "bait_count": summary.bait_count,
                "bait_passed": summary.bait_passed,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return out


def test_gold_set_summary_is_stable(gold_scores: list, tmp_path: Path) -> None:
    """Sanity test — write a summary, confirm aggregate is consistent.

    Not a regression check on its own; exists so a green run leaves an
    inspectable artifact under `tmp_path` for debugging during development.
    """
    summary_path = _write_local_summary(gold_scores, tmp_path)
    payload = json.loads(summary_path.read_text(encoding="utf-8"))
    assert payload["case_count"] == len(gold_scores)
    assert 0.0 <= payload["mean_precision_at_3"] <= 1.0
    assert 0.0 <= payload["mean_mrr"] <= 1.0
