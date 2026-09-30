#!/usr/bin/env python3
"""Calibration harness for the answer cache's paraphrase (semantic) tier.

The paraphrase tier serves a stored reply to a *different* question text, so its
threshold must sit above every within-scope negative and below every intended
paraphrase. This script measures that boundary against the live embedding model
and the checked-in fixture, so enabling ``answer_cache_semantic_enabled`` is a
decision backed by numbers rather than a guess.

Fixture shape (``tests/fixtures/answer_cache/paraphrase_groups.json``):

    [
      {
        "id": "lgd-hp-salary",
        "project_slug": "lg-display-hai-phong",
        "canonical": "Lương công nhân LG Display Hải Phòng bao nhiêu?",
        "paraphrases": ["Mức thu nhập ... là bao nhiêu?"],
        "negatives": ["LG Display Hải Phòng có ký túc xá không?"]
      }
    ]

Negatives are **within-project, different-fact** questions on purpose: the
cross-project dimension is already enforced by ``answer_cache.answer_scope``
(the project scope is part of the key), so the threshold is only responsible for
separating topics inside one project's KB.

Run before flipping ``answer_cache_semantic_enabled``:

    cd backend
    .venv/bin/python scripts/calibrate_answer_cache.py --min-precision 1.0 --min-recall 0.5

Needs an embedding credential in ``.env`` (the same provider ``build_embedder``
resolves for the app). Exits 0 only when precision is at least
``--min-precision`` (no negative reaches the threshold) and recall is at least
``--min-recall``; the printed boundary is what the operator uses to pick
``ANSWER_CACHE_THRESHOLD``.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import dataclass
from pathlib import Path

# Make `app` importable when run as a script from backend/.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings  # noqa: E402
from app.graph.embedders import build_embedder  # noqa: E402
# The runtime compares cached and incoming vectors with exactly this function, so
# the harness must measure the same quantity rather than a reimplementation.
from app.graph.semantic_cache import _cosine  # noqa: E402

DEFAULT_FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "tests"
    / "fixtures"
    / "answer_cache"
    / "paraphrase_groups.json"
)


@dataclass(frozen=True)
class Group:
    id: str
    project_slug: str
    canonical: str
    paraphrases: list[str]
    negatives: list[str]


def _load_groups(path: Path) -> list[Group]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list) or not raw:
        raise ValueError("fixture must be a non-empty JSON array")
    groups: list[Group] = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValueError(f"group {index} must be an object")
        group_id = str(item.get("id") or f"group_{index + 1}")
        canonical = str(item.get("canonical") or "").strip()
        if not canonical:
            raise ValueError(f"{group_id}: canonical is required")
        paraphrases = [str(v).strip() for v in item.get("paraphrases") or [] if str(v).strip()]
        negatives = [str(v).strip() for v in item.get("negatives") or [] if str(v).strip()]
        if not paraphrases:
            raise ValueError(f"{group_id}: paraphrases must contain at least one question")
        if not negatives:
            raise ValueError(f"{group_id}: negatives must contain at least one question")
        groups.append(
            Group(
                id=group_id,
                project_slug=str(item.get("project_slug") or ""),
                canonical=canonical,
                paraphrases=paraphrases,
                negatives=negatives,
            )
        )
    return groups


async def _embed_all(embedder, texts: list[str]) -> list[list[float]]:
    batch_size = getattr(embedder, "_EMBED_BATCH_SIZE", 32)
    vectors: list[list[float]] = []
    for offset in range(0, len(texts), batch_size):
        vectors.extend(await embedder.batch(texts[offset : offset + batch_size]))
    if len(vectors) != len(texts):
        raise RuntimeError(f"embedding mismatch: requested {len(texts)}, got {len(vectors)}")
    return vectors


async def _main() -> int:
    settings = get_settings()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument(
        "--threshold",
        type=float,
        default=settings.answer_cache_threshold,
        help="cosine floor to evaluate (default: the configured answer_cache_threshold)",
    )
    parser.add_argument("--min-precision", type=float, default=1.0)
    parser.add_argument("--min-recall", type=float, default=0.5)
    parser.add_argument("--output", type=Path, help="Optional JSON result path")
    parser.add_argument(
        "--provider",
        choices=("openrouter", "gemini"),
        default=None,
        help="Embedding provider (default: the configured EMBEDDING_PROVIDER)",
    )
    args = parser.parse_args()

    groups = _load_groups(args.fixture)
    embedder = build_embedder(settings, provider=args.provider)

    texts = [group.canonical for group in groups]
    for group in groups:
        texts.extend(group.paraphrases)
        texts.extend(group.negatives)
    vectors = await _embed_all(embedder, texts)

    cursor = 0
    canonical_vectors: list[list[float]] = []
    for group in groups:
        canonical_vectors.append(vectors[cursor])
        cursor += 1
    paraphrase_vectors: list[list[list[float]]] = []
    negative_vectors: list[list[list[float]]] = []
    for group in groups:
        paraphrase_vectors.append(vectors[cursor : cursor + len(group.paraphrases)])
        cursor += len(group.paraphrases)
        negative_vectors.append(vectors[cursor : cursor + len(group.negatives)])
        cursor += len(group.negatives)

    results: list[dict] = []
    all_negatives: list[float] = []
    all_paraphrases: list[float] = []
    for group, base, para_vecs, neg_vecs in zip(
        groups, canonical_vectors, paraphrase_vectors, negative_vectors, strict=True
    ):
        para_sims = [_cosine(base, vector) for vector in para_vecs]
        neg_sims = [_cosine(base, vector) for vector in neg_vecs]
        all_paraphrases.extend(para_sims)
        all_negatives.extend(neg_sims)
        results.append(
            {
                "id": group.id,
                "project_slug": group.project_slug,
                "canonical": group.canonical,
                "paraphrases": [
                    {"text": text, "similarity": round(sim, 4)}
                    for text, sim in zip(group.paraphrases, para_sims, strict=True)
                ],
                "negatives": [
                    {"text": text, "similarity": round(sim, 4)}
                    for text, sim in zip(group.negatives, neg_sims, strict=True)
                ],
                "min_paraphrase": round(min(para_sims), 4),
                "max_negative": round(max(neg_sims), 4),
            }
        )
        print(f"[{group.id}] {group.project_slug}")
        for text, sim in zip(group.paraphrases, para_sims, strict=True):
            mark = "HIT " if sim >= args.threshold else "miss"
            print(f"  {mark} paraphrase {sim:.4f}  {text}")
        for text, sim in zip(group.negatives, neg_sims, strict=True):
            mark = "HIT " if sim >= args.threshold else "miss"
            print(f"  {mark} negative   {sim:.4f}  {text}")
        print(
            f"  boundary: max(negative)={max(neg_sims):.4f} "
            f"min(paraphrase)={min(para_sims):.4f}"
        )

    paraphrase_hits = sum(1 for sim in all_paraphrases if sim >= args.threshold)
    negative_hits = sum(1 for sim in all_negatives if sim >= args.threshold)
    hits = paraphrase_hits + negative_hits
    precision = paraphrase_hits / hits if hits else 1.0
    recall = paraphrase_hits / len(all_paraphrases)
    worst_negative = max(all_negatives)
    best_paraphrase = min(all_paraphrases)
    separable = worst_negative < best_paraphrase

    print()
    print(f"threshold              : {args.threshold}")
    print(f"max(negatives)         : {worst_negative:.4f}")
    print(f"min(paraphrases)       : {best_paraphrase:.4f}")
    print(f"precision              : {precision:.3f} (required >= {args.min_precision})")
    print(f"recall                 : {recall:.3f} (required >= {args.min_recall})")
    if separable:
        print(
            "recommended threshold  : "
            f"({worst_negative:.4f}, {best_paraphrase:.4f}] — any value in this range "
            "separates every negative from every paraphrase"
        )
    else:
        print(
            "recommended threshold  : NONE — max(negatives) >= min(paraphrases); "
            "keep answer_cache_semantic_enabled=False"
        )

    payload = {
        "fixture": str(args.fixture),
        "provider": args.provider or settings.embedding_provider,
        "threshold": args.threshold,
        "group_count": len(groups),
        "paraphrase_count": len(all_paraphrases),
        "negative_count": len(all_negatives),
        "precision": precision,
        "recall": recall,
        "max_negative": worst_negative,
        "min_paraphrase": best_paraphrase,
        "separable": separable,
        "min_precision": args.min_precision,
        "min_recall": args.min_recall,
        "groups": results,
    }
    if args.output:
        args.output.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    return 0 if precision >= args.min_precision and recall >= args.min_recall else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
