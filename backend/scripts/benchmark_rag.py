#!/usr/bin/env python3
"""Golden-case benchmark for chatbot knowledge retrieval.

The benchmark runs the same `search_knowledge` tool path the agent uses, then
scores each case by whether expected evidence terms appear in the retrieved
context.  It needs a configured database, Redis, and Gemini embedding key.

Fixture shape:

[
  {
    "id": "lgd_salary",
    "query": "Thu nhập công nhân LG Display bao nhiêu?",
    "project_slug": "lg-display",
    "expected_terms": ["lương", "LG Display"],
    "forbidden_terms": ["Samsung"]
  }
]

``--gold`` mode runs the offline Vietnamese RAG gold set
(``backend/tests/fixtures/rag_gold/``) against canned embeddings — no DB, no
network, no Gemini key. Use it during retrieval tuning (Phases 2–5 of plan
``260718-1946-kb-rag-quality-and-grounding``) to see per-case pass/fail:

    .venv/bin/python scripts/benchmark_rag.py --gold
    .venv/bin/python scripts/benchmark_rag.py --gold --top-k 10
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Any

from app.core.db import async_session
from app.graph.clients import GeminiEmbedder
from app.graph.tools import search_knowledge
from app.services.retrieval.repository import RetrievalRepository


@dataclass(frozen=True)
class RagCase:
    id: str
    query: str
    project_slug: str | None
    expected_terms: list[str]
    forbidden_terms: list[str]


def _load_cases(path: Path) -> list[RagCase]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError("fixture must be a JSON array")
    cases: list[RagCase] = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValueError(f"case {index} must be an object")
        case_id = str(item.get("id") or f"case_{index + 1}")
        query = str(item.get("query") or "").strip()
        if not query:
            raise ValueError(f"{case_id}: query is required")
        expected_terms = [str(v) for v in item.get("expected_terms") or [] if str(v).strip()]
        if not expected_terms:
            raise ValueError(f"{case_id}: expected_terms must contain at least one term")
        forbidden_terms = [str(v) for v in item.get("forbidden_terms") or [] if str(v).strip()]
        project_slug = item.get("project_slug")
        cases.append(
            RagCase(
                id=case_id,
                query=query,
                project_slug=str(project_slug) if project_slug else None,
                expected_terms=expected_terms,
                forbidden_terms=forbidden_terms,
            )
        )
    return cases


def _contains_all(text: str, terms: list[str]) -> bool:
    haystack = text.casefold()
    return all(term.casefold() in haystack for term in terms)


def _contains_any(text: str, terms: list[str]) -> bool:
    haystack = text.casefold()
    return any(term.casefold() in haystack for term in terms)


async def _run_case(case: RagCase, top_k: int) -> dict[str, Any]:
    embedder = GeminiEmbedder()
    started = perf_counter()
    async with async_session() as db:
        # `search_knowledge` takes the graph retrieval port, not a bare session:
        # the benchmark must exercise the same read surface the agent's tools do.
        result = await search_knowledge(
            RetrievalRepository(db),
            embedder.embed,
            case.query,
            project_slug=case.project_slug,
            top_k=top_k,
        )
    elapsed_ms = round((perf_counter() - started) * 1000)
    expected_hit = _contains_all(result, case.expected_terms)
    forbidden_hit = _contains_any(result, case.forbidden_terms)
    passed = expected_hit and not forbidden_hit
    return {
        "id": case.id,
        "query": case.query,
        "project_slug": case.project_slug,
        "passed": passed,
        "expected_hit": expected_hit,
        "forbidden_hit": forbidden_hit,
        "elapsed_ms": elapsed_ms,
        "expected_terms": case.expected_terms,
        "forbidden_terms": case.forbidden_terms,
        "result_preview": result[:1200],
    }


async def _main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, help="JSON fixture path (legacy mode)")
    parser.add_argument("--gold", action="store_true", help=(
        "Run the offline Vietnamese RAG gold set from "
        "backend/tests/fixtures/rag_gold/. No DB/network."
    ))
    parser.add_argument("--top-k", type=int, default=25)
    parser.add_argument("--min-pass-rate", type=float, default=1.0)
    parser.add_argument("--output", type=Path, help="Optional JSON result path")
    args = parser.parse_args()

    if args.gold:
        return _run_gold(args)

    if not args.fixture:
        parser.error("--fixture is required when --gold is not set")

    cases = _load_cases(args.fixture)
    results = [await _run_case(case, args.top_k) for case in cases]
    passed = sum(1 for r in results if r["passed"])
    pass_rate = passed / max(len(results), 1)
    payload = {
        "case_count": len(results),
        "passed": passed,
        "pass_rate": pass_rate,
        "top_k": args.top_k,
        "results": results,
    }
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if pass_rate >= args.min_pass_rate else 1


def _run_gold(args: argparse.Namespace) -> int:
    """Run the offline Vietnamese RAG gold set against canned embeddings."""
    # Make `tests.*` importable when this script is run directly (not via pytest).
    # Mirrors the sys.path tweak used by seed_rag_gold_embeddings.py.
    backend_root = Path(__file__).resolve().parents[1]
    if str(backend_root) not in sys.path:
        sys.path.insert(0, str(backend_root))
    # Late import so the legacy path doesn't pay for it.
    from tests.rag_gold.loader import load_cases, load_chunks, load_embeddings
    from tests.rag_gold.precision import aggregate, score_case
    from tests.services_runner import build_rows_for_case

    cases = load_cases()
    chunks = load_chunks()
    embeddings = load_embeddings()
    if not embeddings:
        print(
            "ERROR: embeddings.json missing. Run "
            "`scripts/seed_rag_gold_embeddings.py` once to generate it.",
            file=sys.stderr,
        )
        return 2
    per_case = []
    for case in cases:
        rows = build_rows_for_case(case, chunks, embeddings, top_k=args.top_k)
        retrieved = [getattr(row, "id", None) for row in rows]
        score = score_case(
            case_id=case.id,
            retrieved=[i for i in retrieved if i],
            expected=set(case.expected_chunk_ids),
            bait=case.bait,
        )
        per_case.append((case, score, [i for i in retrieved if i]))
    summary = aggregate([s for _, s, _ in per_case])
    print(
        f"Gold set: {summary.case_count} cases, "
        f"{summary.passed} passed ({summary.pass_rate:.1%}), "
        f"{summary.bait_passed}/{summary.bait_count} bait cases abstained."
    )
    print(
        f"  precision@3={summary.mean_precision_at_3:.4f}  "
        f"precision@5={summary.mean_precision_at_5:.4f}  "
        f"recall@10={summary.mean_recall_at_10:.4f}  "
        f"mrr={summary.mean_mrr:.4f}"
    )
    print("\nPer-case detail (failures first):")
    failures = [item for item in per_case if not item[1].passed]
    passes = [item for item in per_case if item[1].passed]
    for case, score, retrieved in sorted(failures, key=lambda x: x[1].case_id) + sorted(
        passes, key=lambda x: x[1].case_id
    ):
        flag = "PASS" if score.passed else "FAIL"
        bait_marker = " [bait]" if case.bait else ""
        retrieved_preview = retrieved[:5]
        print(
            f"  [{flag}] {case.id}{bait_marker}  "
            f"p@3={score.precision_at_3:.2f} mrr={score.mrr:.2f}  "
            f"got={retrieved_preview}"
        )
    if args.output:
        payload = {
            "case_count": summary.case_count,
            "passed": summary.passed,
            "pass_rate": summary.pass_rate,
            "mean_precision_at_3": summary.mean_precision_at_3,
            "mean_precision_at_5": summary.mean_precision_at_5,
            "mean_recall_at_10": summary.mean_recall_at_10,
            "mean_mrr": summary.mean_mrr,
            "bait_count": summary.bait_count,
            "bait_passed": summary.bait_passed,
            "cases": [
                {
                    "id": case.id,
                    "query": case.query,
                    "project_slug": case.project_slug,
                    "bait": case.bait,
                    "passed": score.passed,
                    "precision_at_3": score.precision_at_3,
                    "mrr": score.mrr,
                    "expected": sorted(case.expected_chunk_ids),
                    "retrieved": retrieved,
                }
                for case, score, retrieved in per_case
            ],
        }
        args.output.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    return 0 if summary.pass_rate >= args.min_pass_rate else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(_main()))
