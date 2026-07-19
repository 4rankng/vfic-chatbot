#!/usr/bin/env python3
"""One-shot seeder for the Vietnamese RAG gold-set canned embeddings.

The gold gate (`backend/tests/test_rag_precision_gate.py`) runs **offline**:
embeddings are checked into `embeddings.json` so CI never calls the OpenRouter
embedding API. This script is the only place that calls the real
`openai/text-embedding-3-large` model for the gold set.

Run manually when `chunks.yaml` or `cases.yaml` change:

    cd backend
    .venv/bin/python scripts/seed_rag_gold_embeddings.py

Requires `OPENROUTER_API_KEY` in the environment (read via Settings — never
hard-coded). Writes `backend/tests/fixtures/rag_gold/embeddings.json` with one
entry per chunk ID + per case ID. Re-running overwrites the file idempotently.

The script also computes and writes `baseline.json` so the CI gate has a
recorded precision@3 to compare against. Re-run after intentional retrieval
changes; never check in a lower baseline without a PR note explaining why.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

# Make `app` and `tests` importable when run as a script from backend/.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.graph.clients import OpenRouterEmbedder  # noqa: E402

from tests.rag_gold.loader import (  # noqa: E402
    EMBEDDINGS_JSON,
    load_cases,
    load_chunks,
)
from tests.rag_gold.precision import aggregate, score_case  # noqa: E402
from tests.services_runner import build_rows_for_case  # noqa: E402  (added in Phase 1)


async def _seed() -> int:
    chunks = load_chunks()
    cases = load_cases()
    print(f"Loaded {len(chunks)} chunks and {len(cases)} cases from fixtures.")

    texts_to_embed: list[tuple[str, str]] = []
    for chunk in chunks:
        texts_to_embed.append((chunk.id, chunk.content))
    for case in cases:
        texts_to_embed.append((case.id, case.query))

    print(f"Embedding {len(texts_to_embed)} texts via OpenRouter...")
    embedder = OpenRouterEmbedder()
    # Batch to respect the 96-text API cap; reuse the production batch path.
    vectors: dict[str, list[float]] = {}
    batch_size = embedder._EMBED_BATCH_SIZE
    for offset in range(0, len(texts_to_embed), batch_size):
        batch = texts_to_embed[offset : offset + batch_size]
        ids = [item_id for item_id, _ in batch]
        texts = [text for _, text in batch]
        embedded = await embedder.batch(texts)
        if len(embedded) != len(ids):
            raise RuntimeError(
                f"embedding mismatch: requested {len(ids)}, got {len(embedded)}"
            )
        for item_id, vector in zip(ids, embedded, strict=True):
            vectors[item_id] = [float(x) for x in vector]
        print(f"  embedded {min(offset + batch_size, len(texts_to_embed))}/{len(texts_to_embed)}")

    payload_text = json.dumps(vectors, ensure_ascii=False, indent=2)
    EMBEDDINGS_JSON.write_text(payload_text + "\n", encoding="utf-8")
    print(f"Wrote {EMBEDDINGS_JSON} ({len(vectors)} vectors).")

    # Compute and persist baseline metrics so the CI gate has a reference.
    scores = []
    for case in cases:
        retrieved_rows = build_rows_for_case(case, chunks, vectors)
        retrieved_ids = [getattr(row, "id", None) for row in retrieved_rows]
        scores.append(
            score_case(
                case_id=case.id,
                retrieved=[i for i in retrieved_ids if i],
                expected=set(case.expected_chunk_ids),
                bait=case.bait,
            )
        )
    summary = aggregate(scores)
    baseline = {
        "case_count": summary.case_count,
        "precision_at_3": round(summary.mean_precision_at_3, 4),
        "precision_at_5": round(summary.mean_precision_at_5, 4),
        "recall_at_10": round(summary.mean_recall_at_10, 4),
        "mrr": round(summary.mean_mrr, 4),
        "pass_rate": round(summary.pass_rate, 4),
        "bait_count": summary.bait_count,
        "bait_passed": summary.bait_passed,
    }
    baseline_path = EMBEDDINGS_JSON.parent / "baseline.json"
    baseline_path.write_text(
        json.dumps(baseline, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {baseline_path}: {baseline}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_seed()))
