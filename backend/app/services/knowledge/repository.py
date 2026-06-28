"""Data-access layer for the knowledge training pipeline.

Encapsulates raw SQL the ORM cannot express cleanly:
- vector-column writes (``CAST(:emb AS vector)``; ``KnowledgeChunk.embedding`` is
  ``Text``-typed on purpose, see ``app.models.knowledge``)
- ``jsonb_set`` mutations on ``projects.index_card``
- the bus-timetable rebuild (parsed in pure Python; see
  ``app.services.knowledge.bus_timetable``)

NO business logic, NO LLM calls. Repositories take a ``db: AsyncSession`` and execute
SQL; coercion/orchestration live in ``coercion.py`` / ``pipeline.py``.
"""
from __future__ import annotations

import json
import uuid
from typing import Any, Sequence

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.vector import vec_literal


class KnowledgeChunkRepo:
    """Read/write the ``knowledge_chunks`` table (RAG units + embeddings)."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def replace_for_doc(self, doc, units_with_vectors: list[tuple[dict, list[float]]]) -> None:
        """Delete a document's existing chunks, then insert one row per (unit, vector).

        ``units_with_vectors`` is a list of ``(coerced_unit_dict, embedding_vector)`` in the
        order chunks should be indexed. An empty list simply clears the document's chunks.
        """
        await self.db.execute(
            text("DELETE FROM knowledge_chunks WHERE document_id = :did"), {"did": str(doc.id)}
        )
        for idx, (u, vec) in enumerate(units_with_vectors):
            metadata = dict(u.get("metadata") or {})
            metadata.setdefault("source_anchor", u["source_anchor"])
            metadata.setdefault("is_inference", u["is_inference"])
            await self.db.execute(
                text(
                    "INSERT INTO knowledge_chunks "
                    "(document_id, chunk_index, content, embedding, metadata, project_id, "
                    " source_quote, summary, questions, category, entities, confidence) "
                    "VALUES (:did, :ci, :content, CAST(:emb AS vector), CAST(:meta AS jsonb), CAST(:pid AS uuid), "
                    "        :sq, :sm, CAST(:q AS text[]), :cat, CAST(:ent AS jsonb), :conf)"
                ),
                {
                    "did": str(doc.id),
                    "ci": idx,
                    "content": u["content"],
                    "emb": vec_literal(vec),
                    "meta": json.dumps(metadata, ensure_ascii=False),
                    "pid": str(doc.project_id) if doc.project_id else None,
                    "sq": u["source_quote"],
                    "sm": u["summary"],
                    "q": u["questions"],
                    "cat": u["category"],
                    "ent": json.dumps(u["entities"], ensure_ascii=False),
                    "conf": u["confidence"],
                },
            )
        await self.db.commit()

    async def list_for_doc(self, doc_id: uuid.UUID, *, limit: int = 50) -> list[dict]:
        """A document's chunks (catalog order) as ready-to-serialize dicts.

        Reshapes the LLM-digest payload + ``metadata`` flags (``is_inference`` /
        ``source_anchor``) the admin chunks endpoint validates against.
        """
        rows = (
            await self.db.execute(
                text(
                    "SELECT id, chunk_index, content, source_quote, summary, questions, "
                    "category, entities, confidence, metadata, created_at "
                    "FROM knowledge_chunks "
                    "WHERE document_id = :did "
                    "ORDER BY chunk_index ASC "
                    "LIMIT :limit"
                ),
                {"did": str(doc_id), "limit": limit},
            )
        ).mappings()
        chunks: list[dict] = []
        for row in rows:
            metadata = row.get("metadata") or {}
            chunks.append(
                {
                    "id": row["id"],
                    "chunk_index": row["chunk_index"],
                    "content": row["content"],
                    "source_quote": row["source_quote"],
                    "summary": row["summary"],
                    "questions": row["questions"] or [],
                    "category": row["category"],
                    "entities": row["entities"] or {},
                    "confidence": row["confidence"],
                    "is_inference": bool(metadata.get("is_inference", False)),
                    "source_anchor": metadata.get("source_anchor"),
                    "citation_label": (metadata.get("citation") or {}).get("label"),
                    "content_type": (metadata.get("chunk_metadata") or {}).get("content_type"),
                    "route_id": (metadata.get("chunk_metadata") or {}).get("route_id"),
                    "effective_from": (metadata.get("document_metadata") or {}).get("effective_from"),
                    "effective_to": (metadata.get("document_metadata") or {}).get("effective_to"),
                    "created_at": row["created_at"],
                }
            )
        return chunks

    async def replace_with_single_chunk(self, doc, content: str, emb: str) -> None:
        """Mechanical fallback: drop the doc's chunks and insert one whole-content chunk.

        Does not commit — the caller (the mechanical ingest path) commits once after
        also flipping the document status. ``emb`` is a pgvector literal.
        """
        await self.db.execute(
            text("DELETE FROM knowledge_chunks WHERE document_id = :did"), {"did": str(doc.id)}
        )
        await self.db.execute(
            text(
                "INSERT INTO knowledge_chunks(document_id, chunk_index, content, embedding, metadata) "
                "VALUES (:did, 0, :content, CAST(:emb AS vector), CAST('{}' AS jsonb))"
            ),
            {"did": str(doc.id), "content": content, "emb": emb},
        )

    async def search_similar(
        self, emb: str, top_k: int, project_id: uuid.UUID | None = None
    ) -> list[dict]:
        """Top-k usable chunks by cosine similarity (the admin search-test).

        Branches in Python on ``project_id`` rather than ``(:pid IS NULL OR ...)`` —
        asyncpg cannot infer the type of a NULL placeholder used only in an IS-NULL
        expression. ``emb`` is a pgvector literal.
        """
        if project_id is not None:
            rows = (
                await self.db.execute(
                    text(
                        "SELECT c.content, 1 - (c.embedding <=> CAST(:emb AS vector)) AS similarity "
                        "FROM knowledge_chunks c JOIN knowledge_documents d ON d.id = c.document_id "
                        "WHERE d.status NOT IN ('ARCHIVED', 'FAILED') "
                        "AND c.embedding IS NOT NULL "
                        "AND d.project_id = CAST(:pid AS uuid) "
                        "ORDER BY c.embedding <=> CAST(:emb AS vector) LIMIT :k"
                    ),
                    {"emb": emb, "k": top_k, "pid": str(project_id)},
                )
            ).all()
        else:
            rows = (
                await self.db.execute(
                    text(
                        "SELECT c.content, 1 - (c.embedding <=> CAST(:emb AS vector)) AS similarity "
                        "FROM knowledge_chunks c JOIN knowledge_documents d ON d.id = c.document_id "
                        "WHERE d.status NOT IN ('ARCHIVED', 'FAILED') "
                        "AND c.embedding IS NOT NULL "
                        "ORDER BY c.embedding <=> CAST(:emb AS vector) LIMIT :k"
                    ),
                    {"emb": emb, "k": top_k},
                )
            ).all()
        return [{"content": r.content, "similarity": float(r.similarity)} for r in rows]


_FEATURE_COLUMNS = (
    "jfv.id, jfv.project_id, jfv.feature_id, jfv.value_text, jfv.value_json, "
    "jfv.strength_score, jfv.display_priority, jfv.is_highlight, jfv.is_missing, "
    "jfv.needs_clarification, jfv.evidence_text, jfv.source_document_id, jfv.updated_at, "
    "wfc.feature_key, wfc.name_vi, wfc.category, wfc.worker_question_vi"
)
_FEATURE_FROM = "job_feature_values jfv JOIN worker_feature_catalog wfc ON wfc.id = jfv.feature_id"


class JobFeatureValueRepo:
    """Read/write the ``job_feature_values`` + ``worker_feature_catalog`` tables."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def fetch_catalog(self) -> list:
        """Return the active catalog (11 manual-labour features) ordered by importance then key.

        Drives both the extraction prompt and the one-row-per-feature write, so inactive
        criteria (migration 0009) drop out of extraction entirely.
        """
        return (
            await self.db.execute(
                text(
                    "SELECT id, feature_key, name_vi, worker_question_vi, default_importance_score "
                    "FROM worker_feature_catalog WHERE is_active = true "
                    "ORDER BY default_importance_score DESC, feature_key"
                )
            )
        ).all()

    async def active_catalog_size(self) -> int:
        """Count of active catalog features — the readiness denominator (11 for manual-labour scope).

        Derived rather than hardcoded so reactivating a criterion stays consistent with the
        extraction prompt and list query without a code edit.
        """
        return int(
            (
                await self.db.execute(
                    text("SELECT count(*) FROM worker_feature_catalog WHERE is_active = true")
                )
            ).scalar()
            or 0
        )

    async def replace_for_project(
        self,
        project_id: uuid.UUID,
        doc_id: uuid.UUID,
        rows: list[tuple[Any, dict]],
    ) -> None:
        """Overwrite a project's feature values (delete-then-insert, one row per catalog feature).

        ``rows`` is a list of ``(catalog_row, coerced_feature_dict)`` in display order; the
        enumerate index becomes ``display_priority``.
        """
        await self.db.execute(
            text("DELETE FROM job_feature_values WHERE project_id = :pid"),
            {"pid": str(project_id)},
        )
        for priority, (c, coerced) in enumerate(rows):
            await self.db.execute(
                text(
                    "INSERT INTO job_feature_values "
                    "(project_id, feature_id, value_text, value_json, strength_score, display_priority, "
                    " is_highlight, is_missing, needs_clarification, evidence_text, source_document_id) "
                    "VALUES (CAST(:pid AS uuid), CAST(:fid AS uuid), :vtext, CAST(:vjson AS jsonb), "
                    "        :strength, :prio, :hl, :missing, :clarify, :evidence, CAST(:did AS uuid))"
                ),
                {
                    "pid": str(project_id),
                    "fid": str(c.id),
                    "vtext": coerced["value_text"],
                    "vjson": json.dumps(coerced["value_json"], ensure_ascii=False),
                    "strength": coerced["strength_score"],
                    "prio": priority,
                    "hl": coerced["is_highlight"],
                    "missing": coerced["is_missing"],
                    "clarify": coerced["needs_clarification"],
                    "evidence": coerced["evidence_text"],
                    "did": str(doc_id),
                },
            )
        await self.db.commit()

    async def list_for_project(self, project_id: uuid.UUID) -> list:
        """A project's feature values joined to the catalog (catalog display order)."""
        return (
            await self.db.execute(
                text(
                    f"SELECT {_FEATURE_COLUMNS} FROM {_FEATURE_FROM} "  # noqa: S608 — static f-string
                    "WHERE jfv.project_id = :pid "
                    "ORDER BY jfv.display_priority ASC, wfc.default_importance_score DESC"
                ),
                {"pid": str(project_id)},
            )
        ).all()

    async def exists_for_project(self, feature_id: uuid.UUID, project_id: uuid.UUID) -> bool:
        """True if the feature value belongs to the project."""
        return (
            await self.db.execute(
                text("SELECT 1 FROM job_feature_values WHERE id = :fid AND project_id = :pid"),
                {"fid": str(feature_id), "pid": str(project_id)},
            )
        ).first() is not None

    async def readiness_by_project(
        self, project_ids: Sequence[uuid.UUID]
    ) -> dict[uuid.UUID, int]:
        """Batched ready-feature count per project.

        Ready = a value row exists, is not missing/unclear, and has non-empty
        ``value_text``. One batched query (``= ANY(:ids)``); projects with no
        ready features are simply absent from the dict (caller treats missing
        as 0). Uses the same text/param style as :meth:`list_for_project`.
        """
        if not project_ids:
            return {}
        rows = (
            await self.db.execute(
                text(
                    "SELECT jfv.project_id, COUNT(*) AS ready "
                    "FROM job_feature_values jfv "
                    "JOIN worker_feature_catalog wfc ON wfc.id = jfv.feature_id "
                    "WHERE jfv.project_id = ANY(:ids) "
                    "  AND wfc.is_active = true "
                    "  AND COALESCE(jfv.is_missing, false) = false "
                    "  AND COALESCE(jfv.needs_clarification, false) = false "
                    "  AND jfv.value_text IS NOT NULL "
                    "  AND btrim(jfv.value_text) <> '' "
                    "GROUP BY jfv.project_id"
                ),
                {"ids": [str(pid) for pid in project_ids]},
            )
        ).all()
        return {r.project_id: int(r.ready) for r in rows}

    async def update_fields(self, assignments: list[str], params: dict) -> None:
        """Apply a dynamically-built SET clause (admin feature edit). No-op if no assignments."""
        if not assignments:
            return
        await self.db.execute(
            text(f"UPDATE job_feature_values SET {', '.join(assignments)} WHERE id = :fid"),  # noqa: S608 — built from a fixed field whitelist in the service
            params,
        )

    async def get(self, feature_id: uuid.UUID):
        """One feature value joined to the catalog, or None."""
        return (
            await self.db.execute(
                text(f"SELECT {_FEATURE_COLUMNS} FROM {_FEATURE_FROM} WHERE jfv.id = :fid"),  # noqa: S608 — static f-string
                {"fid": str(feature_id)},
            )
        ).first()


class ProjectIndexRepo:
    """Read/write the project catalog card (``projects.summary`` / ``index_card``)."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def fetch_usable_corpus(self, project_id: uuid.UUID) -> list:
        """Usable-unit content+category, newest-first, capped at 200 (master-index input)."""
        return (
            await self.db.execute(
                text(
                    "SELECT kc.content, kc.category FROM knowledge_chunks kc "
                    "JOIN knowledge_documents kd ON kd.id = kc.document_id "
                    "WHERE kd.project_id = :pid "
                    "AND kd.status NOT IN ('ARCHIVED', 'FAILED') "
                    "ORDER BY kc.created_at DESC LIMIT 200"
                ),
                {"pid": str(project_id)},
            )
        ).all()

    async def update_card(self, project_id: uuid.UUID, summary: str | None, card: dict) -> None:
        """Overwrite the project's summary + LLM-generated catalog card (JSONB)."""
        await self.db.execute(
            text(
                "UPDATE projects SET summary = :summary, index_card = CAST(:card AS jsonb) "
                "WHERE id = :pid"
            ),
            {
                "summary": summary,
                "card": json.dumps(card, ensure_ascii=False),
                "pid": str(project_id),
            },
        )
        await self.db.commit()

    async def sync_highlights(self, project_id: uuid.UUID) -> None:
        """Mirror the project's is_highlight feature values into ``index_card.highlights``.

        Feature-derived highlights are authoritative when present (override the LLM card).
        No-op when the project has no highlighted features.
        """
        rows = (
            await self.db.execute(
                text(
                    "SELECT value_text FROM job_feature_values "
                    "WHERE project_id = :pid AND is_highlight "
                    "ORDER BY display_priority ASC, strength_score DESC LIMIT 6"
                ),
                {"pid": str(project_id)},
            )
        ).all()
        if not rows:
            return
        await self.db.execute(
            text(
                "UPDATE projects SET index_card = "
                "jsonb_set(COALESCE(index_card, '{}'::jsonb), '{highlights}', CAST(:hl AS jsonb)) "
                "WHERE id = :pid"
            ),
            {"hl": json.dumps([r.value_text for r in rows], ensure_ascii=False), "pid": str(project_id)},
        )
        await self.db.commit()


async def rebuild_bus_timetable(db: AsyncSession) -> tuple[int, int]:
    """Rebuild the structured bus-timetable graph from the parsed ``LGDisplay`` document.

    Reads the legacy ``LGDisplay.txt`` raw text, parses it in pure Python
    (``app.services.knowledge.bus_timetable``), and persists via
    ``BusTimetableRepo``. Behaviour-identical to the former
    ``rebuild_bus_timetable_from_documents()`` SQL function (golden-gated). Best-effort:
    callers wrap in ``try/except``; returns ``(0, 0)`` when no source document is present
    (matches the SQL fn's empty loop — does NOT scan unrelated documents).
    """
    # Lazy import keeps this data-access module free of a load-time dependency on the
    # parser package.
    from app.services.knowledge.bus_timetable import parse_bus_timetable
    from app.services.knowledge.bus_timetable.repository import BusTimetableRepo

    source = (
        await db.execute(
            text(
                "SELECT kd.raw_text, p.slug AS project_slug "
                "FROM knowledge_documents kd "
                "JOIN projects p ON p.id = kd.project_id "
                "WHERE kd.file_name = :fn "
                "  AND kd.status NOT IN ('ARCHIVED', 'FAILED') "
                "  AND kd.raw_text IS NOT NULL "
                "ORDER BY kd.updated_at DESC, kd.created_at DESC "
                "LIMIT 1"
            ),
            {"fn": "LGDisplay.txt"},
        )
    ).mappings().first()
    if source is None:
        return (0, 0)
    parsed = parse_bus_timetable(source["raw_text"])
    return await BusTimetableRepo(db).upsert(
        parsed,
        project_slug=source["project_slug"],
        company_name="LG Display",
        source_name="LGDisplay.txt",
    )


__all__ = [
    "JobFeatureValueRepo",
    "KnowledgeChunkRepo",
    "ProjectIndexRepo",
    "rebuild_bus_timetable",
    "mark_document_failed_sync",
]


def mark_document_failed_sync(database_url: str, doc_id: str, error: str) -> None:
    """Sync fallback to mark a knowledge document as FAILED.

    Used by the ingest worker's crash handler (``run_ingest_job``) when RQ's
    death penalty raises an exception *outside* the asyncio.run() frame, making
    the async session unavailable. Creates a short-lived sync engine; callers
    must ensure ``database_url`` is the synchronous (psycopg) URL.
    """
    from sqlalchemy import create_engine

    try:
        engine = create_engine(database_url, future=True)
        try:
            with engine.begin() as conn:
                conn.execute(
                    text(
                        "UPDATE knowledge_documents "
                        "SET status = 'FAILED', stage = 'FAILED', "
                        "error = :error, updated_at = now() "
                        "WHERE id = CAST(:id AS uuid)"
                    ),
                    {"id": doc_id, "error": error[:1000]},
                )
        finally:
            engine.dispose()
    except Exception:  # noqa: BLE001 — do not mask the original RQ failure
        raise
