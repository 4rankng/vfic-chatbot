"""LLM-driven "training pipeline" orchestrator — turns a raw KB file into RAG-efficient units.

For one document it runs: extract -> digest -> embed -> index -> product features.

  extract  -> raw text (handled at upload; here we assume ``doc.raw_text`` is set)
  digest   -> the LLM cleans, semantic-splits, self-contained-rewrites, extracts
              metadata + retrieval questions, and flags faithfulness for each unit
  embed    -> GeminiEmbedder.batch over the digested units
  index    -> regenerate the project's catalog card (the agent's master-index entry)
  features -> LLM-extract the 16 worker "product features" for the project (best-effort)

This module is the ORCHESTRATOR only: LLM/embed calls + business flow. SQL lives in
``repository.py`` and coercion in ``coercion.py``. The LLM step is injected (``llm_json``)
so the pipeline is unit-testable without API keys; a fake returns canned JSON.

STRICT grounding rule (existing persona contract): every unit carries a verbatim
``source_quote``; low-confidence / inferred units are flagged, never silently invented.
"""
from __future__ import annotations

import json
import logging
import uuid
from typing import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.knowledge.coercion import (
    DigestError,
    _coerce_feature,
    _parse_json_lenient,
    _product_feature_prompt,
    validate_digest,
)
from app.services.knowledge.extraction import split_for_digest
from app.services.knowledge.prompts import DIGEST_SYSTEM_PROMPT, INDEX_SYSTEM_PROMPT
from app.services.knowledge.repository import (
    JobFeatureValueRepo,
    KnowledgeChunkRepo,
    ProjectIndexRepo,
    rebuild_bus_timetable,
)

logger = logging.getLogger(__name__)

# A function (system_prompt, user_text) -> raw JSON text. Injected so this module
# stays free of langchain/google imports and is unit-testable with a fake.
LLMJson = Callable[[str, str], Awaitable[str]]
Embedder = Callable[[str], Awaitable[list[float]]]


class KnowledgePipeline:
    """Orchestrates digest -> embed -> index for one document.

    Injected deps (testable): ``embedder`` (GeminiEmbedder-compatible) and
    ``llm_json`` ((system, user) -> json text). Both run inside the RQ worker.
    """

    def __init__(self, db: AsyncSession, embedder: Embedder, llm_json: LLMJson) -> None:
        self.db = db
        self.embedder = embedder
        self.llm_json = llm_json
        self.chunks = KnowledgeChunkRepo(db)
        self.features = JobFeatureValueRepo(db)
        self.index = ProjectIndexRepo(db)

    async def run(self, doc) -> None:
        """Full pipeline for ``doc`` (KnowledgeDocument). Mutates + commits."""
        await self._set_stage(doc, "DIGESTING", status="PROCESSING", error=None)
        raw = doc.raw_text or ""
        sections = split_for_digest(raw)
        all_units: list[dict] = []
        summary_parts: list[str] = []
        for section in sections:
            summary, units = await self._digest_section(section)
            all_units.extend(units)
            if summary:
                summary_parts.append(summary)

        await self._set_stage(doc, "EMBEDDING")
        await self._store_units(doc, all_units)

        doc.digest_summary = " ".join(summary_parts).strip() or None
        flagged = [i for i, u in enumerate(all_units) if u["confidence"] == "low" or u["is_inference"]]
        doc.digest_meta = {
            "section_count": len(sections),
            "unit_count": len(all_units),
            "flagged_unit_indexes": flagged,
        }

        # Product-feature extraction (best-effort): turn the posting into the 16 worker
        # product features the agent answers from. Runs before build_project_index so the
        # derived highlights flow into the catalog card. A failure must never block RAG
        # indexing — the run() try/except below keeps ingest healthy.
        if doc.project_id is not None:
            try:
                await self.extract_product_features(doc, all_units)
            except Exception as exc:  # noqa: BLE001 — extraction is best-effort
                logger.warning("product feature extraction failed for doc %s: %s", doc.id, exc)

        await self._set_stage(doc, "INDEXING")
        if doc.project_id is not None:
            try:
                await self.build_project_index(doc.project_id)
            except Exception as exc:  # noqa: BLE001 — index refresh is best-effort
                logger.warning("project index refresh failed: %s", exc)

        await self._set_stage(doc, "READY_FOR_REVIEW", status="READY_FOR_REVIEW")
        # rebuild the structured bus graph from the `documents` VIEW (verbatim SQL fn)
        try:
            await rebuild_bus_timetable(self.db)
        except Exception:  # noqa: BLE001 — rebuild is best-effort; never block ingest
            pass

    async def _digest_section(self, section: str) -> tuple[str, list[dict]]:
        """Call the LLM once per section; retry once on a malformed response."""
        last_err: str | None = None
        for attempt in range(2):
            try:
                raw = await self.llm_json(DIGEST_SYSTEM_PROMPT, section)
                payload = _parse_json_lenient(raw)
                return validate_digest(payload)
            except DigestError as exc:
                last_err = str(exc)
                logger.warning("digest attempt %d failed: %s", attempt + 1, last_err)
            except json.JSONDecodeError as exc:
                last_err = f"invalid JSON: {exc}"
                logger.warning("digest attempt %d not JSON: %s", attempt + 1, last_err)
        raise DigestError(f"digest failed after retry: {last_err}")

    async def _store_units(self, doc, units: list[dict]) -> None:
        if not units:
            await self.chunks.replace_for_doc(doc, [])  # clear the document's chunks
            return
        # Batch-embed one combined string per unit (content + summary + questions).
        embed_inputs = []
        for u in units:
            pieces = [u["content"]]
            if u["summary"]:
                pieces.append(u["summary"])
            pieces.extend(u["questions"])
            embed_inputs.append("\n".join(pieces))
        vectors = await self._embed_batch(embed_inputs)
        await self.chunks.replace_for_doc(doc, list(zip(units, vectors)))

    async def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed many texts; prefer a batch call when the embedder supports it."""
        batch = getattr(self.embedder, "batch", None)
        if callable(batch):
            return await batch(texts)  # type: ignore[misc]
        return [await self.embedder(t) for t in texts]

    async def build_project_index(self, project_id: uuid.UUID) -> None:
        """Regenerate the project's catalog card from its APPROVED units (master index)."""
        rows = await self.index.fetch_approved_corpus(project_id)
        if not rows:
            return
        corpus = "\n".join(f"- [{r.category}] {r.content}" for r in rows)
        raw = await self.llm_json(INDEX_SYSTEM_PROMPT, corpus)
        card = _parse_json_lenient(raw)
        if not isinstance(card, dict):
            return
        await self.index.update_card(
            project_id, str(card.get("summary") or "").strip() or None, card
        )
        # Feature-derived highlights are authoritative when present (override the LLM card).
        await self.index.sync_highlights(project_id)

    async def extract_product_features(self, doc, units: list[dict]) -> None:
        """LLM-extract the 16 worker product features for ``doc.project_id`` (best-effort).

        Always writes exactly one job_feature_values row per catalog feature — features the
        posting omits get ``is_missing=true`` — so the project has a stable 16-row set.
        Idempotent: deletes the project's existing rows before inserting.
        """
        if doc.project_id is None:
            return
        catalog = await self.features.fetch_catalog()
        if not catalog:
            return
        corpus = (doc.raw_text or "").strip() or "\n".join(u["content"] for u in units)
        if not corpus.strip():
            return
        raw = await self.llm_json(_product_feature_prompt(catalog), corpus)
        payload = _parse_json_lenient(raw)
        feats = payload.get("features") if isinstance(payload, dict) else None
        feats = feats if isinstance(feats, list) else []
        # Parse the LLM list into a by-key map, then coerce one row per catalog feature
        # (missing features fall back to the is_missing marker) in catalog display order.
        by_key: dict[str, dict] = {}
        for f in feats:
            if isinstance(f, dict):
                key = str(f.get("feature_key") or f.get("key") or "").strip()
                if key:
                    by_key[key] = f
        rows = [(c, _coerce_feature(by_key.get(c.feature_key), c)) for c in catalog]
        await self.features.replace_for_project(doc.project_id, doc.id, rows)
        await self.index.sync_highlights(doc.project_id)

    async def _set_stage(self, doc, stage: str, *, status: str | None = None, error: str | None = None) -> None:
        doc.stage = stage
        if status is not None:
            # late import to avoid a circular at module load
            from app.models.knowledge import KnowledgeStatus

            doc.status = KnowledgeStatus(status)
        doc.error = error
        await self.db.commit()


async def sync_project_highlights(db: AsyncSession, project_id: uuid.UUID) -> None:
    """Mirror a project's is_highlight feature values into ``projects.index_card.highlights``.

    Standalone (no embedder/LLM deps) so the admin PATCH endpoint can re-sync after an
    edit without instantiating the full pipeline.
    """
    await ProjectIndexRepo(db).sync_highlights(project_id)
