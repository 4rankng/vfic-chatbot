"""Tests for Lost-in-the-Middle context assembly (RAG pack W1 mục 03).

Covers:
  * ``order_context_chunks`` / ``resolve_context_order`` ordering invariants
    (best rank at index 0, second-best at index -1, weakest buried in the middle),
  * ``Settings.rag_context_order`` default (``position-aware``) and validation,
  * ``search_knowledge`` context assembly + cache namespace differentiation,
  * ``scripts.eval_answers`` position tracking, ``summarize_context_positions``,
    and ``--context-order both`` comparison.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.core.config import Settings
from app.graph.tools.knowledge import (
    CONTEXT_ORDER_POSITION_AWARE,
    CONTEXT_ORDER_SIMILARITY,
    order_context_chunks,
    resolve_context_order,
    search_knowledge,
)
from scripts.eval_answers import (
    COMPARISON_SCHEMA,
    compare_context_orders,
    format_context_order_comparison,
    load_gold_bundle,
    main,
    run_case,
    summarize_context_positions,
)


# ---------------------------------------------------------------------------
# order_context_chunks & Settings.rag_context_order
# ---------------------------------------------------------------------------


def test_rag_context_order_defaults_to_position_aware():
    s = Settings()
    assert s.rag_context_order == CONTEXT_ORDER_POSITION_AWARE
    assert Settings(rag_context_order="similarity").rag_context_order == CONTEXT_ORDER_SIMILARITY
    assert Settings(rag_context_order="RANK").rag_context_order == CONTEXT_ORDER_SIMILARITY


def test_rag_context_order_rejects_invalid_value():
    with pytest.raises(ValueError, match="rag_context_order"):
        Settings(rag_context_order="random-shuffle")


@pytest.mark.parametrize(
    ("items", "expected"),
    [
        ([], []),
        (["r1"], ["r1"]),
        (["r1", "r2"], ["r1", "r2"]),
        (["r1", "r2", "r3"], ["r1", "r3", "r2"]),
        (["r1", "r2", "r3", "r4"], ["r1", "r3", "r4", "r2"]),
        (["r1", "r2", "r3", "r4", "r5"], ["r1", "r3", "r5", "r4", "r2"]),
        (
            ["r1", "r2", "r3", "r4", "r5", "r6"],
            ["r1", "r3", "r5", "r6", "r4", "r2"],
        ),
    ],
)
def test_order_context_chunks_places_best_at_edges_and_weakest_in_middle(items, expected):
    out = order_context_chunks(items, order="position-aware")
    assert out == expected
    if len(items) >= 2:
        assert out[0] == items[0]
        assert out[-1] == items[1]


def test_order_context_chunks_13_item_long_context_invariants():
    ranked = [f"rank-{i}" for i in range(1, 14)]
    assembled = order_context_chunks(ranked, order="position-aware")
    assert len(assembled) == 13
    assert set(assembled) == set(ranked)
    # Rank 1 at start (pos 1), Rank 2 at end (pos 13), Rank 3 at pos 2, Rank 4 at pos 12
    assert assembled[0] == "rank-1"
    assert assembled[-1] == "rank-2"
    assert assembled[1] == "rank-3"
    assert assembled[-2] == "rank-4"
    # Lowest-ranked chunk (rank-13) lands at exact center (index 6, 1-based pos 7)
    assert assembled[len(assembled) // 2] == "rank-13"


def test_order_context_chunks_similarity_preserves_monotone_order():
    ranked = [f"rank-{i}" for i in range(1, 10)]
    assert order_context_chunks(ranked, order="similarity") == ranked
    assert order_context_chunks(ranked, order="rank") == ranked


def test_resolve_context_order_reads_settings_and_falls_back_safely(monkeypatch):
    import app.graph.tools.knowledge as knowledge

    monkeypatch.setattr(knowledge, "get_settings", lambda: SimpleNamespace())
    assert resolve_context_order() == CONTEXT_ORDER_POSITION_AWARE

    monkeypatch.setattr(
        knowledge, "get_settings", lambda: SimpleNamespace(rag_context_order="similarity")
    )
    assert resolve_context_order() == CONTEXT_ORDER_SIMILARITY


# ---------------------------------------------------------------------------
# search_knowledge integration + cache namespace safety
# ---------------------------------------------------------------------------


def _row(idx: int, *, category: str = "general") -> SimpleNamespace:
    return SimpleNamespace(
        id=f"chunk-{idx}",
        content=f"Nội dung đoạn {idx}",
        source_quote=f"Nội dung đoạn {idx}",
        summary=None,
        category=category,
        project_name="LG Display",
        project_slug="lg-display",
        metadata={"citation": {"label": f"Tài liệu {idx}"}},
        source_file=f"doc-{idx}.md",
        line_start=idx,
        line_end=idx,
    )


@pytest.mark.asyncio
async def test_search_knowledge_reorders_long_context_when_position_aware(monkeypatch):
    import app.graph.tools.knowledge as knowledge

    rows = [_row(i) for i in range(1, 7)]
    repo = SimpleNamespace(
        active_project_ids=AsyncMock(return_value=["p1"]),
        match_faq=AsyncMock(return_value=[]),
        match_documents=AsyncMock(return_value=rows),
        last_match_degraded=None,
    )
    monkeypatch.setattr(knowledge, "cached_embed", AsyncMock(return_value=[0.1] * 8))
    monkeypatch.setattr(knowledge, "cache_get_json", AsyncMock(return_value=None))
    monkeypatch.setattr(knowledge, "cache_set_json", AsyncMock())
    monkeypatch.setattr(knowledge, "cache_version", AsyncMock(return_value="1"))

    monkeypatch.setattr(
        knowledge,
        "get_settings",
        lambda: SimpleNamespace(
            rag_cache_enabled=False,
            semantic_cache_enabled=False,
            rag_context_order="position-aware",
        ),
    )
    pos_out = await search_knowledge(repo, AsyncMock(), "lương")
    pos_chunks = [line for line in pos_out.splitlines() if line.startswith("- ")]
    assert len(pos_chunks) == 6
    assert "Nội dung đoạn 1" in pos_chunks[0]
    assert "Nội dung đoạn 2" in pos_chunks[-1]
    assert "Nội dung đoạn 3" in pos_chunks[1]
    assert "Nội dung đoạn 4" in pos_chunks[-2]
    assert "Nội dung đoạn 6" in pos_chunks[3]

    monkeypatch.setattr(
        knowledge,
        "get_settings",
        lambda: SimpleNamespace(
            rag_cache_enabled=False,
            semantic_cache_enabled=False,
            rag_context_order="similarity",
        ),
    )
    sim_out = await search_knowledge(repo, AsyncMock(), "lương")
    sim_chunks = [line for line in sim_out.splitlines() if line.startswith("- ")]
    assert [f"Nội dung đoạn {i}" in sim_chunks[i - 1] for i in range(1, 7)] == [True] * 6


@pytest.mark.asyncio
async def test_search_knowledge_faq_header_preserved_and_cache_keys_separated(monkeypatch):
    import app.graph.tools.knowledge as knowledge

    faq_rows = [_row(1, category="faq"), _row(2, category="faq")]
    doc_rows = [_row(3, category="general"), _row(4, category="general")]
    repo = SimpleNamespace(
        active_project_ids=AsyncMock(return_value=["p1"]),
        match_faq=AsyncMock(return_value=faq_rows),
        match_documents=AsyncMock(return_value=doc_rows),
        last_match_degraded=None,
    )
    seen_keys: list[str] = []

    async def _record_get(key: str):
        seen_keys.append(key)
        return None

    monkeypatch.setattr(knowledge, "cached_embed", AsyncMock(return_value=[0.1] * 8))
    monkeypatch.setattr(knowledge, "cache_get_json", _record_get)
    monkeypatch.setattr(knowledge, "cache_set_json", AsyncMock())
    monkeypatch.setattr(knowledge, "cache_version", AsyncMock(return_value="1"))

    for mode in ("position-aware", "similarity"):
        monkeypatch.setattr(
            knowledge,
            "get_settings",
            lambda m=mode: SimpleNamespace(
                rag_cache_enabled=True,
                rag_result_cache_ttl_seconds=60,
                semantic_cache_enabled=False,
                rag_context_order=m,
            ),
        )
        out = await search_knowledge(repo, AsyncMock(), "lương")
        assert out.splitlines()[0] == "CÂU HỎI THƯỜNG GẶP (câu trả lời chuẩn):"
        bullets = [line for line in out.splitlines() if line.startswith("- ")]
        assert "Nội dung đoạn 1" in bullets[0]

    assert len(seen_keys) == 2
    assert seen_keys[0] != seen_keys[1]


# ---------------------------------------------------------------------------
# eval_answers position tracking & comparison
# ---------------------------------------------------------------------------


def test_eval_answers_run_case_passes_reordered_contexts_to_generator():
    bundle = load_gold_bundle()
    # Select a case known to retrieve multiple chunks and have a rank-2 gold hit
    gold = next(e for e in bundle.entries if e.ref == "lgd_salary_total")
    captured_sim: list[list[str]] = []
    captured_pos: list[list[str]] = []

    case_sim = run_case(
        bundle,
        gold,
        top_k=25,
        rerank_enabled=False,
        answers_mode="live",
        replay_answers=None,
        judge=None,
        generate=lambda _q, ctx: (captured_sim.append(list(ctx)) or "ok"),
        context_order="similarity",
    )
    case_pos = run_case(
        bundle,
        gold,
        top_k=25,
        rerank_enabled=False,
        answers_mode="live",
        replay_answers=None,
        judge=None,
        generate=lambda _q, ctx: (captured_pos.append(list(ctx)) or "ok"),
        context_order="position-aware",
    )

    assert case_sim["gold_retrieval_ranks"] == [2]
    assert case_sim["gold_context_positions"] == [2]
    # In position-aware mode, rank 2 moves to the final position (N = 13)
    assert case_pos["gold_retrieval_ranks"] == [2]
    assert case_pos["gold_context_positions"] == [case_pos["context_count"]]
    assert captured_sim[0] != captured_pos[0]
    assert captured_pos[0] == order_context_chunks(captured_sim[0], order="position-aware")


def test_cli_context_order_both_compares_similarity_and_position_aware(tmp_path, capsys):
    out = tmp_path / "order_compare.json"
    rc = main(
        [
            "--rerank",
            "off",
            "--context-order",
            "both",
            "--no-answers",
            "--output",
            str(out),
        ]
    )
    assert rc == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["schema"] == COMPARISON_SCHEMA
    sim_pos = payload["similarity"]["aggregate"]["context_positions"]
    pos_pos = payload["position_aware"]["aggregate"]["context_positions"]
    # Position-aware ordering moves rank-2 gold chunks to the recency edge (end)
    assert sim_pos["end_cases"] == 0
    assert pos_pos["end_cases"] > 0
    assert pos_pos["edge_rate"] > sim_pos["edge_rate"]
    assert pos_pos["middle_rate"] < sim_pos["middle_rate"]
    assert pos_pos["long_context_middle_rate"] < sim_pos["long_context_middle_rate"]

    comparison = compare_context_orders(payload["similarity"], payload["position_aware"])
    table = format_context_order_comparison(comparison)
    assert "position-aware" in table
    assert "edge_rate" in table
    assert "middle_rate" in table
    assert "edge_rate" in capsys.readouterr().out


def test_summarize_context_positions_handles_empty_and_abstain():
    summary = summarize_context_positions(
        [
            {"id": "abstain-1", "abstain": True, "context_count": 3, "gold_context_positions": []},
            {
                "id": "hit-start",
                "abstain": False,
                "context_count": 8,
                "gold_retrieval_ranks": [1],
                "gold_context_positions": [1],
            },
            {
                "id": "hit-end",
                "abstain": False,
                "context_count": 8,
                "gold_retrieval_ranks": [2],
                "gold_context_positions": [8],
            },
            {
                "id": "hit-mid",
                "abstain": False,
                "context_count": 8,
                "gold_retrieval_ranks": [4],
                "gold_context_positions": [7],
            },
        ]
    )
    assert summary["non_abstain_cases"] == 3
    assert summary["long_context_cases"] == 3
    assert summary["start_cases"] == 1
    assert summary["end_cases"] == 1
    assert summary["edge_cases"] == 2
    assert summary["middle_cases"] == 1
    assert summary["long_context_middle_cases"] == 1
