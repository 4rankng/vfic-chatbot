"""FAQ-scoped retrieval: the canonical FAQ read path for the bot.

The live FAQ surface is chunk-based: ``KnowledgeChunk`` rows with
``category='faq'`` (see ``services/project/faq.py`` for the writer). This
module holds the embedding-similarity read arm (higher floor) that the FAQ
pre-pass consumes. The former trigram arm served only the removed FAQ
bypass.
"""

from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.retrieval.document_repository import DocumentRepository

logger = logging.getLogger(__name__)


class FaqRepository:
    """Read-only FAQ chunk queries (embedding arm)."""

    # FAQ pre-pass floor. Sheet-sourced FAQ chunks embed their full rendered
    # record (label + id + question + answer + terms + tags), so a verbatim
    # user query — which embeds as the bare question — scores below the 0.70
    # this was originally set to, and the FAQ pre-pass returned nothing. Measured
    # on prod (lg-display, post category-authority cutover): verbatim FAQ queries
    # score 0.62-0.79 (weakest 0.621) while non-FAQ queries top out at ~0.47, so
    # 0.55 sits in the clean gap with ~0.07 margin on both sides. Do not raise
    # above ~0.60 or every sheet-FAQ verbatim match is filtered out again.
    FAQ_SIMILARITY_FLOOR = 0.55

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def match_faq(
        self,
        emb: str,
        top_k: int = 3,
        *,
        filter_json: str = "{}",
        project_ids: list[str] | None = None,
        floor: float | None = None,
    ) -> list:
        """FAQ-first retrieval: scoped to ``category='faq'`` chunks with a higher floor.

        Used by ``search_knowledge`` to prepend canonical FAQ answers before the
        general retrieval pass.  Reuses ``_chunk_visibility`` for status / effective-date /
        project scoping so archived or out-of-date FAQ chunks are excluded automatically.
        """
        if floor is None:
            floor = self.FAQ_SIMILARITY_FLOOR
        project_clause = ""
        params: dict[str, object] = {"emb": emb, "k": top_k, "filter": filter_json}
        if project_ids:
            project_clause = "AND d.project_id = ANY(CAST(:pids AS uuid[]))"
            params["pids"] = project_ids
        rows = (
            await self.db.execute(
                text(
                    "SELECT c.id, c.content, c.source_quote, c.summary, c.metadata, "
                    "       c.questions, c.required_terms, c.forbidden_terms, "
                    "       c.line_start, c.line_end, c.section_path, ktf.filename AS source_file, "
                    "       1 - (c.embedding <=> CAST(:emb AS vector)) AS similarity "
                    "FROM knowledge_chunks c "
                    "JOIN knowledge_documents d ON d.id = c.document_id "
                    "JOIN projects p ON p.id = d.project_id "
                    "LEFT JOIN kb_text_files ktf ON ktf.id = c.file_id "
                    "WHERE " + DocumentRepository._chunk_visibility(project_clause) + " "
                    "  AND c.category = 'faq' "
                    "  AND 1 - (c.embedding <=> CAST(:emb AS vector)) >= :faq_floor "
                    "ORDER BY c.embedding <=> CAST(:emb AS vector) "
                    "LIMIT :k"
                ),
                {**params, "faq_floor": floor},
            )
        ).all()
        logger.debug(
            "match_faq: %d rows (floor=%.2f, category=faq)",
            len(rows),
            floor,
        )
        return list(rows)

