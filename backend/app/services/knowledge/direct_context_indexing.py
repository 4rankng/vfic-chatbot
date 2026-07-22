"""Index DIRECT_CONTEXT KB text into ``knowledge_chunks`` via the shared pipeline.

A DIRECT_CONTEXT knowledge base stores its content as a single text blob in
``knowledge_base_direct_files`` (injected verbatim into the LLM system prompt on FOCUSED
turns). That blob is invisible to ``search_knowledge`` because there are no
``knowledge_chunks`` rows for it. This module closes that gap by routing the text through
the existing :class:`KnowledgePipeline` (digest → embed → store) so DIRECT_CONTEXT content
participates in cross-project retrieval just like RAG content.

Design (from plan ``260722-2300-cross-kb-retrieval-and-stats``, Phase 1):

* A **synthetic** :class:`KnowledgeDocument` anchors the chunks (chunks require NOT NULL
  ``document_id`` FK and every retrieval query INNER JOINs through
  ``knowledge_documents``). One document per KB — find-or-create by
  ``metadata_.knowledge_base_id`` so re-publishing reuses the row and the pipeline's
  ``replace_for_doc`` naturally replaces the old chunks.
* The pipeline runs with ``source="direct_context"``; the pipeline suppresses
  ``index_card`` / ``job_feature_values`` rebuild for that source so the project's
  catalog card (the source of truth for synthesized jobs) is never overwritten.
* Chunks are tagged ``chunk_type='direct_context'`` after the pipeline stores them, so
  the Phase 2 visibility predicate can admit them without touching the shared
  ``chunk_type_from_metadata`` helper.
* Runs in the RQ ``ingest`` worker (off the publish transaction) — see
  :mod:`app.workers.direct_context_worker`.
"""

from __future__ import annotations

import json
import logging
import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.knowledge import KnowledgeDocument, KnowledgeStatus
from app.services.knowledge import KnowledgePipeline

logger = logging.getLogger(__name__)

DIRECT_CONTEXT_SOURCE = "direct_context"
_DIRECT_CONTEXT_CHUNK_TYPE = "direct_context"


async def _find_or_create_direct_document(
    db: AsyncSession,
    *,
    knowledge_base_id: uuid.UUID,
    project_id: uuid.UUID,
    text_blob: str,
) -> KnowledgeDocument:
    """Return the synthetic DIRECT_CONTEXT document for ``knowledge_base_id``.

    Reuses the existing row (matched by ``metadata_ ->> 'knowledge_base_id'``) so the
    pipeline's ``replace_for_doc`` replaces the prior chunks in place. Creates one if
    none exists yet.
    """
    kb_id_str = str(knowledge_base_id)
    existing_id = await db.scalar(
        text(
            "SELECT id FROM knowledge_documents "
            "WHERE source = :src AND metadata_ ->> 'knowledge_base_id' = :kb_id "
            "LIMIT 1"
        ),
        {"src": DIRECT_CONTEXT_SOURCE, "kb_id": kb_id_str},
    )
    if existing_id is not None:
        # Reuse the row so the pipeline's replace_for_doc replaces prior chunks.
        await db.execute(
            text(
                "UPDATE knowledge_documents SET raw_text = :rt, "
                "status = 'UPLOADED', stage = 'UPLOADED', error = NULL "
                "WHERE id = :did"
            ),
            {"rt": text_blob, "did": str(existing_id)},
        )
        await db.flush()
        doc = await db.get(KnowledgeDocument, existing_id)
        assert doc is not None  # just updated above
        return doc

    doc = KnowledgeDocument(
        file_name=f"direct_context::{kb_id_str}",
        source=DIRECT_CONTEXT_SOURCE,
        status=KnowledgeStatus.UPLOADED,
        raw_text=text_blob,
        project_id=project_id,
        mime_type="text/plain",
        stage="UPLOADED",
        metadata_={
            "source": DIRECT_CONTEXT_SOURCE,
            "knowledge_base_id": kb_id_str,
        },
    )
    db.add(doc)
    await db.flush()
    return doc


async def index_direct_context(
    db: AsyncSession,
    knowledge_base_id: uuid.UUID,
    project_id: uuid.UUID,
    text_blob: str,
    *,
    embedder,
    llm_json,
) -> None:
    """Digest + embed + store DIRECT_CONTEXT text as ``direct_context`` chunks.

    ``embedder`` / ``llm_json`` are injected (same shape as :class:`KnowledgePipeline`)
    so the worker can resolve provider credentials and tests can pass fakes. The pipeline
    commits its own transaction; this function does not commit the document row separately.
    """
    if not (text_blob and text_blob.strip()):
        logger.info(
            "direct_context indexing skipped: empty text for kb=%s", knowledge_base_id
        )
        return

    doc = await _find_or_create_direct_document(
        db,
        knowledge_base_id=knowledge_base_id,
        project_id=project_id,
        text_blob=text_blob,
    )
    pipeline = KnowledgePipeline(db, embedder, llm_json)
    await pipeline.run(doc)

    # The pipeline stores chunks via ``chunk_type_from_metadata`` which does not know
    # about DIRECT_CONTEXT. Tag them in one UPDATE so the Phase 2 visibility predicate
    # can admit them by ``chunk_type``.
    await db.execute(
        text(
            "UPDATE knowledge_chunks SET chunk_type = :ct "
            "WHERE document_id = :did"
        ),
        {"ct": _DIRECT_CONTEXT_CHUNK_TYPE, "did": str(doc.id)},
    )
    await db.commit()
    logger.info(
        "direct_context indexed for kb=%s project=%s doc=%s",
        knowledge_base_id,
        project_id,
        doc.id,
    )
