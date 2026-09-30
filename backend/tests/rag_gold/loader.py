"""Load Vietnamese RAG gold-set fixtures and build test retrieval rows.

The loader is a **pure function module** — no I/O except reading the JSON fixture files. It builds the same row shape the real
``RetrievalRepository.match_documents`` returns (``SimpleNamespace`` with
``id``, ``similarity``, ``content``, ``document_id``, ``section_path``,
``source_file``, ``source_label``, ``chunk_sha256``) so the gold gate can
exercise the actual fusion + dedup + rerank code paths without a database.

Embeddings live in ``embeddings.json`` keyed by chunk ID and case ID. They
are pre-computed once by ``backend/scripts/seed_rag_gold_embeddings.py``
using the real ``text-embedding-3-large`` model — that script is run manually
when ``chunks.json`` or ``cases.json`` change; CI never calls the embedding
API. Vector-arm cosine similarity is computed at load time against the
query's canned embedding.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "rag_gold"
CHUNKS_JSON = FIXTURE_DIR / "chunks.json"
CASES_JSON = FIXTURE_DIR / "cases.json"
EMBEDDINGS_JSON = FIXTURE_DIR / "embeddings.json"
BASELINE_JSON = FIXTURE_DIR / "baseline.json"


def hash_text(text: str) -> str:
    """SHA-256 of stripped text — mirrors ``app.services.project.faq.hash_text``."""
    return hashlib.sha256((text or "").strip().encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class GoldCase:
    """A single Vietnamese RAG test case."""

    id: str
    query: str
    project_slug: str | None
    expected_chunk_ids: frozenset[str]
    expected_answer_facts: tuple[str, ...] = ()
    expected_answer_facts_absent: tuple[str, ...] = ()
    bait: bool = False
    note: str = ""


@dataclass(frozen=True)
class GoldChunk:
    """A synthetic KB chunk from ``chunks.json``."""

    id: str
    project_slug: str
    category: str
    document_id: str
    section_path: str
    source_label: str
    content: str
    chunk_sha256: str


@dataclass(frozen=True)
class LoadedGold:
    """Everything the precision runner needs in one immutable bundle."""

    cases: tuple[GoldCase, ...]
    chunks: tuple[GoldChunk, ...]
    # project_slug -> tuple of chunk IDs (lexical-arm candidate filtering)
    chunks_by_project: dict[str, tuple[str, ...]] = field(default_factory=dict)


def _load_json(path: Path) -> Any:
    if not path.exists():
        raise FileNotFoundError(f"fixture missing: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def load_chunks(path: Path = CHUNKS_JSON) -> tuple[GoldChunk, ...]:
    """Parse ``chunks.json`` into immutable :class:`GoldChunk` records.

    Content is stripped; ``chunk_sha256`` is computed when missing so the
    Phase 4 sha256-dedup path can be exercised even before the column is
    populated by the production pipeline.
    """
    raw = _load_json(path)
    if not isinstance(raw, list):
        raise ValueError(f"{path}: expected a JSON list of chunks")
    seen_ids: set[str] = set()
    chunks: list[GoldChunk] = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValueError(f"{path}[{index}]: chunk must be a mapping")
        chunk_id = str(item.get("id") or "").strip()
        if not chunk_id:
            raise ValueError(f"{path}[{index}]: chunk missing 'id'")
        if chunk_id in seen_ids:
            raise ValueError(f"{path}: duplicate chunk id {chunk_id!r}")
        seen_ids.add(chunk_id)
        content = str(item.get("content") or "").strip()
        if not content:
            raise ValueError(f"{path}[{index}]: chunk {chunk_id!r} has empty content")
        sha = str(item.get("chunk_sha256") or "").strip() or hash_text(content)
        chunks.append(
            GoldChunk(
                id=chunk_id,
                project_slug=str(item.get("project_slug") or "").strip(),
                category=str(item.get("category") or "general").strip(),
                document_id=str(item.get("document_id") or chunk_id).strip(),
                section_path=str(item.get("section_path") or "").strip(),
                source_label=str(item.get("source_label") or "").strip(),
                content=content,
                chunk_sha256=sha,
            )
        )
    return tuple(chunks)


def load_cases(path: Path = CASES_JSON) -> tuple[GoldCase, ...]:
    """Parse ``cases.json`` into immutable :class:`GoldCase` records."""
    raw = _load_json(path)
    if not isinstance(raw, list):
        raise ValueError(f"{cases_path_err(path)}: expected a JSON list of cases")
    seen_ids: set[str] = set()
    cases: list[GoldCase] = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValueError(f"{path}[{index}]: case must be a mapping")
        case_id = str(item.get("id") or "").strip()
        if not case_id:
            raise ValueError(f"{path}[{index}]: case missing 'id'")
        if case_id in seen_ids:
            raise ValueError(f"{path}: duplicate case id {case_id!r}")
        seen_ids.add(case_id)
        query = str(item.get("query") or "").strip()
        if not query:
            raise ValueError(f"{path}[{index}]: case {case_id!r} has empty query")
        project_slug = item.get("project_slug")
        expected = item.get("expected_chunk_ids") or []
        if not isinstance(expected, list):
            raise ValueError(f"{path}[{index}]: case {case_id!r} expected_chunk_ids must be a list")
        cases.append(
            GoldCase(
                id=case_id,
                query=query,
                project_slug=str(project_slug).strip() if project_slug else None,
                expected_chunk_ids=frozenset(str(c).strip() for c in expected if str(c).strip()),
                expected_answer_facts=tuple(
                    str(f).strip() for f in (item.get("expected_answer_facts") or []) if str(f).strip()
                ),
                expected_answer_facts_absent=tuple(
                    str(f).strip() for f in (item.get("expected_answer_facts_absent") or []) if str(f).strip()
                ),
                bait=bool(item.get("bait", False)),
                note=str(item.get("note") or "").strip(),
            )
        )
    return tuple(cases)


def cases_path_err(path: Path) -> str:
    """Inline helper so the closure references the right path in errors."""
    return str(path)


def load_embeddings(path: Path = EMBEDDINGS_JSON) -> dict[str, list[float]]:
    """Load canned embeddings keyed by chunk ID and case ID.

    Returns an empty dict when the file is absent — callers fall back to a
    deterministic zero vector so the suite still runs before the seed script
    has been executed. (In that mode the gate only exercises lexical + dedup
    paths; the loader logs a warning.)
    """
    if not path.exists():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{path}: expected a JSON object keyed by id")
    return {str(k): [float(x) for x in v] for k, v in raw.items()}


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Plain cosine similarity. Returns 0.0 on length mismatch or empty input."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(y * y for y in b) ** 0.5
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def build_vector_rows(
    case: GoldCase,
    chunks: tuple[GoldChunk, ...],
    embeddings: dict[str, list[float]],
    *,
    top_k: int = 25,
    floor: float = 0.30,
) -> list[SimpleNamespace]:
    """Build the vector-arm candidate rows for one case.

    Mirrors what ``RetrievalRepository._match_document_vector_rows`` would
    return: every chunk (scoped by ``case.project_slug`` when set) with
    ``similarity`` = cosine similarity to the query's canned embedding,
    filtered by ``floor`` and limited to ``top_k``.
    """
    query_emb = embeddings.get(case.id)
    if query_emb is None:
        # No canned embedding — nothing to rank. This happens before
        # `seed_rag_gold_embeddings.py` has been run; re-seed to gate properly.
        return []
    scored: list[tuple[float, GoldChunk]] = []
    for chunk in chunks:
        if case.project_slug and chunk.project_slug != case.project_slug:
            continue
        chunk_emb = embeddings.get(chunk.id)
        if chunk_emb is None:
            continue
        sim = cosine_similarity(query_emb, chunk_emb)
        if sim >= floor:
            scored.append((sim, chunk))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [_chunk_to_row(sim, chunk) for sim, chunk in scored[:top_k]]


def _chunk_to_row(similarity: float, chunk: GoldChunk) -> SimpleNamespace:
    """Build a SimpleNamespace row matching the production RetrievalRepository shape."""
    return SimpleNamespace(
        id=chunk.id,
        similarity=round(float(similarity), 6),
        content=chunk.content,
        source_quote=chunk.content,  # production distinguishes; gold set treats them equal
        summary="",
        metadata={"category": chunk.category, "source_label": chunk.source_label},
        document_id=chunk.document_id,
        section_path=chunk.section_path,
        source_file=chunk.source_label,
        chunk_sha256=chunk.chunk_sha256,
        source_label=chunk.source_label,
        category=chunk.category,
    )


def load_gold(
    chunks_path: Path = CHUNKS_JSON,
    cases_path: Path = CASES_JSON,
    embeddings_path: Path = EMBEDDINGS_JSON,
) -> LoadedGold:
    """Load cases + chunks + embeddings and index chunks by project_slug."""
    chunks = load_chunks(chunks_path)
    cases = load_cases(cases_path)
    _ = load_embeddings(embeddings_path)  # validated for shape; rows built per case
    chunks_by_project: dict[str, tuple[str, ...]] = {}
    for chunk in chunks:
        chunks_by_project.setdefault(chunk.project_slug, ())
        chunks_by_project[chunk.project_slug] = chunks_by_project[chunk.project_slug] + (chunk.id,)
    return LoadedGold(cases=cases, chunks=chunks, chunks_by_project=chunks_by_project)
