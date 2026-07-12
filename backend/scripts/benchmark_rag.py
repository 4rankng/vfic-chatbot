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
        result = await search_knowledge(
            db,
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
    parser.add_argument("--fixture", required=True, type=Path, help="JSON fixture path")
    parser.add_argument("--top-k", type=int, default=25)
    parser.add_argument("--min-pass-rate", type=float, default=1.0)
    parser.add_argument("--output", type=Path, help="Optional JSON result path")
    args = parser.parse_args()

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


if __name__ == "__main__":
    sys.exit(asyncio.run(_main()))
