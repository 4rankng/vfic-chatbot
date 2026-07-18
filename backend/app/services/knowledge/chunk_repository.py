"""Repository for the ``knowledge_chunks`` table (RAG units + embeddings)."""

from __future__ import annotations

import json
import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import bump_kb_caches
from app.core.vector import vec_literal
from app.services.knowledge.text_ingestion import (
    chunk_type_from_metadata,
    estimate_token_count,
    hash_text,
    line_range_for_quote,
    make_content_plain,
    section_path_from_metadata,
)


class KnowledgeChunkRepo:
    """Read/write the ``knowledge_chunks`` table (RAG units + embeddings)."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def replace_for_doc(
        self, doc, units_with_vectors: list[tuple[dict, list[float]]]
    ) -> None:
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
                    " source_quote, summary, questions, category, entities, confidence, "
                    " required_terms, forbidden_terms) "
                    "VALUES (:did, :ci, :content, CAST(:emb AS vector), CAST(:meta AS jsonb), CAST(:pid AS uuid), "
                    "        :sq, :sm, CAST(:q AS text[]), :cat, CAST(:ent AS jsonb), :conf, "
                    "        CAST(:req AS text[]), CAST(:forb AS text[]))"
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
                    "req": u.get("required_terms") or [],
                    "forb": u.get("forbidden_terms") or [],
                },
            )
        await self.db.commit()
        await bump_kb_caches()

    async def clear_version(self, kb_version_id: uuid.UUID) -> None:
        """Delete every chunk generated for a KB version before rebuilding it."""
        await self.db.execute(
            text("DELETE FROM knowledge_chunks WHERE kb_version_id = :vid"),
            {"vid": str(kb_version_id)},
        )

    async def insert_category_revision(
        self,
        *,
        document_id: uuid.UUID,
        project_id: uuid.UUID,
        category_revision_id: uuid.UUID,
        category_key: str,
        units_with_vectors: list[tuple[dict, list[float]]],
    ) -> None:
        """Insert deterministic category chunks without committing activation.

        The category service advances the active pointer in the same transaction,
        so these rows remain invisible until all projections also succeed.
        """
        for index, (unit, vector) in enumerate(units_with_vectors):
            content = str(unit["content"])
            metadata = dict(unit.get("metadata") or {})
            await self.db.execute(
                text(
                    "INSERT INTO knowledge_chunks ("
                    "document_id, category_revision_id, chunk_index, chunk_type, content, "
                    "content_plain, token_count, chunk_sha256, embedding, metadata, project_id, "
                    "source_quote, summary, questions, category, entities, confidence, search_text, "
                    "required_terms, forbidden_terms"
                    ") VALUES ("
                    "CAST(:did AS uuid), CAST(:rid AS uuid), :idx, 'category_record', :content, "
                    ":plain, :tokens, :sha, CAST(:embedding AS vector), CAST(:metadata AS jsonb), "
                    "CAST(:pid AS uuid), :quote, :summary, CAST(:questions AS text[]), :category, "
                    "CAST(:entities AS jsonb), 'high', public.normalize_search_text(:search_text), "
                    "CAST(:required AS text[]), CAST(:forbidden AS text[])"
                    ")"
                ),
                {
                    "did": str(document_id),
                    "rid": str(category_revision_id),
                    "idx": index,
                    "content": content,
                    "plain": make_content_plain(content),
                    "tokens": estimate_token_count(content),
                    "sha": hash_text(content),
                    "embedding": vec_literal(vector),
                    "metadata": json.dumps(metadata, ensure_ascii=False),
                    "pid": str(project_id),
                    "quote": unit.get("source_quote") or content,
                    "summary": unit.get("summary"),
                    "questions": unit.get("questions") or [],
                    "category": category_key,
                    "entities": json.dumps(unit.get("entities") or {}, ensure_ascii=False),
                    "search_text": unit.get("search_text") or content,
                    "required": unit.get("required_terms") or [],
                    "forbidden": unit.get("forbidden_terms") or [],
                },
            )

    async def attach_doc_chunks_to_file(
        self,
        *,
        doc_id: uuid.UUID,
        kb_version_id: uuid.UUID,
        file_id: uuid.UUID,
        project_id: uuid.UUID,
        source_text: str,
    ) -> None:
        """Stamp chunks generated by the legacy document pipeline with version metadata."""
        rows = (
            (
                await self.db.execute(
                    text(
                        "SELECT id, content, source_quote, summary, category, metadata "
                        "FROM knowledge_chunks WHERE document_id = :did ORDER BY chunk_index ASC"
                    ),
                    {"did": str(doc_id)},
                )
            )
            .mappings()
            .all()
        )
        for row in rows:
            metadata = dict(row.get("metadata") or {})
            quote = row.get("source_quote") or row.get("content")
            line_start, line_end = line_range_for_quote(source_text, quote)
            section_path = section_path_from_metadata(metadata)
            category = row.get("category")
            await self.db.execute(
                text(
                    "UPDATE knowledge_chunks "
                    "SET kb_version_id = CAST(:vid AS uuid), "
                    "    file_id = CAST(:fid AS uuid), "
                    "    project_id = CAST(:pid AS uuid), "
                    "    chunk_type = :chunk_type, "
                    "    section_path = CAST(:section_path AS text[]), "
                    "    line_start = :line_start, "
                    "    line_end = :line_end, "
                    "    content_plain = :content_plain, "
                    "    token_count = :token_count, "
                    "    chunk_sha256 = :chunk_sha256 "
                    "WHERE id = :cid"
                ),
                {
                    "vid": str(kb_version_id),
                    "fid": str(file_id),
                    "pid": str(project_id),
                    "chunk_type": chunk_type_from_metadata(metadata, category),
                    "section_path": section_path,
                    "line_start": line_start,
                    "line_end": line_end,
                    "content_plain": make_content_plain(
                        row.get("content"), row.get("source_quote"), row.get("summary")
                    ),
                    "token_count": estimate_token_count(row.get("content") or ""),
                    "chunk_sha256": hash_text(row.get("content") or ""),
                    "cid": str(row["id"]),
                },
            )

    async def list_for_doc(self, doc_id: uuid.UUID, *, limit: int = 50) -> list[dict]:
        """A document's chunks (catalog order) as ready-to-serialize dicts.

        Reshapes the LLM-digest payload + ``metadata`` flags (``is_inference`` /
        ``source_anchor``) the admin chunks endpoint validates against.
        """
        rows = (
            await self.db.execute(
                text(
                    "SELECT id, chunk_index, content, source_quote, summary, questions, "
                    "kb_version_id, file_id, chunk_type, section_path, line_start, line_end, "
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
                    "kb_version_id": row["kb_version_id"],
                    "file_id": row["file_id"],
                    "chunk_type": row["chunk_type"],
                    "section_path": row["section_path"] or [],
                    "line_start": row["line_start"],
                    "line_end": row["line_end"],
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
                    "effective_from": (metadata.get("document_metadata") or {}).get(
                        "effective_from"
                    ),
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
                "INSERT INTO knowledge_chunks("
                "document_id, chunk_index, content, embedding, metadata, project_id, "
                "content_plain, token_count, chunk_sha256"
                ") VALUES ("
                ":did, 0, :content, CAST(:emb AS vector), CAST('{}' AS jsonb), "
                "CAST(:pid AS uuid), :content_plain, :token_count, :chunk_sha256"
                ")"
            ),
            {
                "did": str(doc.id),
                "content": content,
                "emb": emb,
                "pid": str(doc.project_id) if doc.project_id else None,
                "content_plain": make_content_plain(content),
                "token_count": estimate_token_count(content),
                "chunk_sha256": hash_text(content),
            },
        )

    async def search_similar(
        self, emb: str, top_k: int, project_id: uuid.UUID | None = None
    ) -> list[dict]:
        """Top-k usable chunks by cosine similarity (the admin search-test).

        Branches in Python on ``project_id`` rather than ``(:pid IS NULL OR ...)` —
        asyncpg cannot infer the type of a NULL placeholder used only in an IS-NULL
        expression. ``emb`` is a pgvector literal.
        """
        if project_id is not None:
            rows = (
                await self.db.execute(
                    text(
                        "SELECT c.content, 1 - (c.embedding <=> CAST(:emb AS vector)) AS similarity "
                        "FROM knowledge_chunks c "
                        "JOIN knowledge_documents d ON d.id = c.document_id "
                        "JOIN projects p ON p.id = d.project_id "
                        "WHERE d.status NOT IN ('ARCHIVED', 'FAILED') "
                        "AND c.embedding IS NOT NULL "
                        "AND d.project_id = CAST(:pid AS uuid) "
                        "AND ((c.category_revision_id IS NOT NULL AND EXISTS ("
                        "  SELECT 1 FROM knowledge_categories kc "
                        "  WHERE kc.project_id = p.id "
                        "    AND kc.active_revision_id = c.category_revision_id"
                        ")) OR (c.category_revision_id IS NULL "
                        "  AND c.kb_version_id = p.active_kb_version_id "
                        "  AND p.category_authority_started IS FALSE)) "
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
                        "FROM knowledge_chunks c "
                        "JOIN knowledge_documents d ON d.id = c.document_id "
                        "JOIN projects p ON p.id = d.project_id "
                        "WHERE d.status NOT IN ('ARCHIVED', 'FAILED') "
                        "AND c.embedding IS NOT NULL "
                        "AND ((c.category_revision_id IS NOT NULL AND EXISTS ("
                        "  SELECT 1 FROM knowledge_categories kc "
                        "  WHERE kc.project_id = p.id "
                        "    AND kc.active_revision_id = c.category_revision_id"
                        ")) OR (c.category_revision_id IS NULL "
                        "  AND c.kb_version_id = p.active_kb_version_id "
                        "  AND p.category_authority_started IS FALSE)) "
                        "ORDER BY c.embedding <=> CAST(:emb AS vector) LIMIT :k"
                    ),
                    {"emb": emb, "k": top_k},
                )
            ).all()
        return [{"content": r.content, "similarity": float(r.similarity)} for r in rows]

    async def reassign_project(self, doc_id: uuid.UUID, project_id: uuid.UUID | None) -> None:
        """Move a document's chunks to a different project (or clear the project)."""
        await self.db.execute(
            text("UPDATE knowledge_chunks SET project_id = :pid WHERE document_id = :did"),
            {
                "pid": str(project_id) if project_id is not None else None,
                "did": str(doc_id),
            },
        )
