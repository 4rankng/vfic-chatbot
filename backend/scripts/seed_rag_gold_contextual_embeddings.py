#!/usr/bin/env python3
"""Seed the contextual-prefix variant of the Vietnamese RAG gold embeddings.

The Contextual Retrieval feature (``app.services.knowledge.contextual``) changes
what a chunk's embedding is computed FROM: a document-context prefix rides in
front of the content. The checked-in ``embeddings.json`` holds the *unprefixed*
chunk embeddings, so measuring the feature's retrieval effect means re-embedding
the gold chunks with the production prefix builder and re-running the offline
gold benchmark against both files:

    cd backend
    .venv/bin/python scripts/seed_rag_gold_contextual_embeddings.py
    .venv/bin/python scripts/benchmark_rag.py --gold --min-pass-rate 0 \
        --embeddings tests/fixtures/rag_gold/embeddings_contextual.json

The script embeds each gold chunk's text exactly as ``KnowledgePipeline``
would at index time — ``contextual_embed_input`` over the chunk's metadata —
using the real OpenRouter embedding model. Query embeddings are NOT re-called:
they are copied byte-identical from ``embeddings.json`` so the before/after
comparison changes only the chunk side, never the queries.

Writes ``embeddings_contextual.json`` next to the checked-in fixtures and
prints the resulting metrics summary. Requires ``OPENROUTER_API_KEY`` in the
environment (read via Settings — never hard-coded).
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

# Make `app` and `tests` importable when run as a script from backend/.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.graph.clients import OpenRouterEmbedder  # noqa: E402
from app.services.knowledge.contextual import (  # noqa: E402
    contextual_embed_input,
    contextual_enabled,
)

from tests.rag_gold.loader import (  # noqa: E402
    EMBEDDINGS_JSON,
    load_cases,
    load_chunks,
    load_embeddings,
)
from tests.rag_gold.precision import aggregate, score_case  # noqa: E402
from tests.services_runner import build_rows_for_case  # noqa: E402

CONTEXTUAL_EMBEDDINGS_JSON = EMBEDDINGS_JSON.parent / "embeddings_contextual.json"


def contextual_chunk_embed_text(chunk) -> str:
    """The embed input the production pipeline would index ``chunk`` under.

    Mirrors ``KnowledgePipeline._store_units`` for a digest unit: the
    contextual prefix rides in front of the content (gold chunks carry no
    digest summary/questions, so those pieces are empty here).
    """
    unit: dict = {
        "summary": None,
        "source_anchor": chunk.section_path,
        "category": chunk.category,
    }
    return contextual_embed_input(
        unit,
        chunk.content,
        doc_title=chunk.source_label,
        doc_summary=None,
    )


async def _seed() -> int:
    if not contextual_enabled():
        print(
            "ERROR: rag_contextual_enabled is off — this seeder would only "
            "reproduce the unprefixed embeddings.json. Enable the toggle.",
            file=sys.stderr,
        )
        return 2
    chunks = load_chunks()
    cases = load_cases()
    unprefixed = load_embeddings()
    if not unprefixed:
        print(
            "ERROR: embeddings.json missing. Run "
            "`scripts/seed_rag_gold_embeddings.py` once to generate it.",
            file=sys.stderr,
        )
        return 2
    print(f"Loaded {len(chunks)} chunks and {len(cases)} cases from fixtures.")

    texts = [(chunk.id, contextual_chunk_embed_text(chunk)) for chunk in chunks]
    sample = next(iter(texts))[1]
    print(f"Embedding {len(texts)} prefixed chunk texts via OpenRouter...")
    print(f"  embed input sample: {sample[:160]!r}")

    embedder = OpenRouterEmbedder()
    vectors: dict[str, list[float]] = {}
    batch_size = embedder._EMBED_BATCH_SIZE
    for offset in range(0, len(texts), batch_size):
        batch = texts[offset : offset + batch_size]
        ids = [item_id for item_id, _ in batch]
        embedded = await embedder.batch([text for _, text in batch])
        if len(embedded) != len(ids):
            raise RuntimeError(
                f"embedding mismatch: requested {len(ids)}, got {len(embedded)}"
            )
        for item_id, vector in zip(ids, embedded, strict=True):
            vectors[item_id] = [float(x) for x in vector]
        print(f"  embedded {min(offset + batch_size, len(texts))}/{len(texts)}")

    # Queries stay byte-identical to the unprefixed run: the feature changes
    # the INDEX side only, and the benchmark must not move two variables.
    missing = [case.id for case in cases if case.id not in unprefixed]
    if missing:
        print(f"ERROR: query embeddings missing from embeddings.json: {missing}", file=sys.stderr)
        return 2
    for case in cases:
        vectors[case.id] = unprefixed[case.id]

    CONTEXTUAL_EMBEDDINGS_JSON.write_text(
        json.dumps(vectors, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"Wrote {CONTEXTUAL_EMBEDDINGS_JSON} ({len(vectors)} vectors).")

    scores = []
    for case in cases:
        rows = build_rows_for_case(case, chunks, vectors)
        retrieved = [getattr(row, "id", None) for row in rows]
        scores.append(
            score_case(
                case_id=case.id,
                retrieved=[i for i in retrieved if i],
                expected=set(case.expected_chunk_ids),
                bait=case.bait,
            )
        )
    summary = aggregate(scores)
    print(
        f"Contextual gold set: {summary.case_count} cases, "
        f"{summary.passed} passed ({summary.pass_rate:.1%}), "
        f"{summary.bait_passed}/{summary.bait_count} bait cases abstained."
    )
    print(
        f"  precision@3={summary.mean_precision_at_3:.4f}  "
        f"precision@5={summary.mean_precision_at_5:.4f}  "
        f"recall@10={summary.mean_recall_at_10:.4f}  "
        f"mrr={summary.mean_mrr:.4f}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_seed()))
