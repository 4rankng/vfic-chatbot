"""LLM-driven "training pipeline" orchestrator — turns a raw KB file into RAG-efficient units.

For one document it runs: extract -> digest -> embed -> index -> product features.

  extract  -> raw text (handled at upload; here we assume ``doc.raw_text`` is set)
  digest   -> the LLM cleans, semantic-splits, self-contained-rewrites, extracts
              metadata + retrieval questions, and flags faithfulness for each unit
  embed    -> configured embedder batch over the digested units
  index    -> regenerate the project's catalog card (the agent's master-index entry)
  features -> LLM-extract the 11 worker "product features" for the project (best-effort)

This module is the ORCHESTRATOR only: LLM/embed calls + business flow. SQL lives in
``repository.py`` and coercion in ``coercion.py``. The LLM step is injected (``llm_json``)
so the pipeline is unit-testable without API keys; a fake returns canned JSON.

STRICT grounding rule (existing persona contract): every unit carries a verbatim
``source_quote``; low-confidence / inferred units are flagged, never silently invented.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from datetime import UTC, datetime
from typing import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.embedding import embed_with_fallback
from app.services.knowledge.coercion import (
    DigestError,
    _coerce_feature,
    _parse_json_lenient,
    _product_feature_prompt,
    validate_digest,
)
from app.services.knowledge.canonical import (
    CANONICAL_SCHEMA_VERSIONS,
    ParsedKnowledgeDocument,
    checksum_text,
    parse_canonical_markdown,
)
from app.services.knowledge.extraction import DigestSections, split_for_digest
from app.services.knowledge.prompts import DIGEST_SYSTEM_PROMPT, INDEX_SYSTEM_PROMPT
from app.services.knowledge.repository import (
    JobFeatureValueRepo,
    KnowledgeChunkRepo,
    ProjectIndexRepo,
    rebuild_bus_timetable,
)

logger = logging.getLogger(__name__)

# A function (system_prompt, user_text) -> raw JSON text. Injected so this module
# stays free of provider SDK imports and is unit-testable with a fake.
LLMJson = Callable[[str, str], Awaitable[str]]
Embedder = Callable[[str], Awaitable[list[float]]]


class KnowledgePipeline:
    """Orchestrates digest -> embed -> index for one document.

    Injected deps (testable): ``embedder`` (configured-provider-compatible) and
    ``llm_json`` ((system, user) -> json text). Runs in the RQ ingest worker by default
    (``call_timeout`` unset -> the generous digest ceiling); web-process callers
    (``reindex``, feature re-extract) pass ``call_timeout`` = the tighter request timeout
    so a slow MiniMax call cannot stall the 2-worker API.
    """

    def __init__(
        self,
        db: AsyncSession,
        embedder: Embedder,
        llm_json: LLMJson,
        *,
        call_timeout: int | None = None,
    ) -> None:
        self.db = db
        self.embedder = embedder
        self.llm_json = llm_json
        # Per-instance LLM ceiling. None (background ingest) -> provider digest timeout;
        # web-process callers pass provider request timeout so they don't hold a web worker
        # for the full digest ceiling.
        self._call_timeout = call_timeout
        self.chunks = KnowledgeChunkRepo(db)
        self.features = JobFeatureValueRepo(db)
        self.index = ProjectIndexRepo(db)

    async def run(self, doc) -> None:
        """Full pipeline for ``doc`` (KnowledgeDocument). Mutates + commits."""
        raw = doc.raw_text or ""
        canonical_doc = None
        digest_sections: DigestSections | None = None
        is_canonical = (doc.metadata_ or {}).get("schema_version") in CANONICAL_SCHEMA_VERSIONS
        await self._set_stage(doc, "DIGESTING", status="PROCESSING", error=None)
        if is_canonical:
            stored_checksum = (doc.metadata_ or {}).get("checksum")
            current_checksum = checksum_text(raw)
            if stored_checksum and stored_checksum != current_checksum:
                raise ValueError("canonical document checksum changed after upload validation")
            canonical_doc = parse_canonical_markdown(raw)
            all_units = [chunk.to_unit(canonical_doc) for chunk in canonical_doc.chunks]
            summary_parts = [canonical_doc.document_summary]
            sections = [raw] if raw.strip() else []
        else:
            digest_sections = split_for_digest(raw)
            sections = digest_sections.sections
            if digest_sections.truncated:
                logger.warning(
                    "digest truncated for doc %s: %d of %d source chars not covered",
                    doc.id,
                    digest_sections.dropped_chars,
                    digest_sections.total_chars,
                )
            all_units = []
            summary_parts = []
            for section in sections:
                summary, units = await self._digest_section(section)
                all_units.extend(units)
                if summary:
                    summary_parts.append(summary)

        await self._set_stage(doc, "EMBEDDING")
        await self._store_units(doc, all_units)

        doc.digest_summary = " ".join(summary_parts).strip() or None
        flagged = [
            i for i, u in enumerate(all_units) if u["confidence"] == "low" or u["is_inference"]
        ]
        doc.digest_meta = {
            "section_count": len(sections),
            "unit_count": len(all_units),
            "flagged_unit_indexes": flagged,
            "truncated": bool(digest_sections and digest_sections.truncated),
            "dropped_chars": digest_sections.dropped_chars if digest_sections else 0,
            "source_chars": digest_sections.total_chars if digest_sections else len(raw),
        }

        # DIRECT_CONTEXT documents carry their own curated content; their
        # ``projects.index_card`` is the SOURCE OF TRUTH for synthesized jobs and must
        # not be overwritten by LLM-driven feature/card rebuilds. Skip those side-effects
        # while still running digest → embed → store so the content is searchable.
        # ``rebuild_project_jobs`` is also skipped (DIRECT_CONTEXT jobs are synthesized
        # from ``index_card`` at query time, not from Job rows).
        is_direct_context = (doc.metadata_ or {}).get("source") == "direct_context" or getattr(
            doc, "source", None
        ) == "direct_context"

        if is_direct_context:
            # Only the core digest → embed → store path is meaningful here. The
            # PUBLISHED stage is set by the outer ``run`` below; nothing else to do.
            pass
        elif doc.project_id is not None and canonical_doc is not None:
            await self.sync_canonical_product_features(doc, canonical_doc)
        elif doc.project_id is not None:
            try:
                await self.extract_product_features(doc, all_units)
            except Exception as exc:  # noqa: BLE001 — extraction is best-effort
                logger.warning("product feature extraction failed for doc %s: %s", doc.id, exc)

        await self._set_stage(doc, "INDEXING", status="PUBLISHED")
        if canonical_doc is not None and canonical_doc.bus_timetable.routes:
            await self._persist_canonical_bus_timetable(doc, canonical_doc)
        if is_direct_context:
            pass  # do not rebuild index_card for DIRECT_CONTEXT (source of truth)
        elif doc.project_id is not None and canonical_doc is not None:
            await self._update_canonical_project_card(doc, canonical_doc)
        elif doc.project_id is not None:
            try:
                await self.build_project_index(doc.project_id)
            except Exception as exc:  # noqa: BLE001 — index refresh is best-effort
                logger.warning("project index refresh failed: %s", exc)

        if not is_direct_context and doc.project_id is not None:
            from app.services.knowledge.derived_jobs import rebuild_project_jobs

            await rebuild_project_jobs(
                self.db,
                project_id=doc.project_id,
                source_document_id=doc.id,
            )

        await self._set_stage(doc, "PUBLISHED", status="PUBLISHED")
        if canonical_doc is None:
            # Legacy LGDisplay parser fallback.
            try:
                await rebuild_bus_timetable(self.db)
            except Exception:  # noqa: BLE001 — rebuild is best-effort; never block ingest
                pass

    async def _digest_section(self, section: str) -> tuple[str, list[dict]]:
        """Call the LLM once per section; retry once on a malformed/empty response.

        A *timeout* is NOT retried: at the digest-timeout ceiling (180s) a retry is
        futile (in practice both attempts time out) and would burn the RQ job budget on
        multi-section docs, so it falls back at once. Empty/malformed JSON is retried
        once (transient emptiness can recover) before falling back. Either way the
        document keeps source-grounded units instead of failing at 0.
        """
        last_err: str | None = None
        for attempt in range(2):
            try:
                raw = await self._llm_json_with_timeout(
                    DIGEST_SYSTEM_PROMPT, section, purpose="digest"
                )
                payload = _parse_json_lenient(raw)
                return validate_digest(payload)
            except DigestError as exc:
                last_err = str(exc)
                logger.warning("digest attempt %d failed: %s", attempt + 1, last_err)
            except json.JSONDecodeError as exc:
                last_err = f"invalid JSON: {exc}"
                logger.warning("digest attempt %d not JSON: %s", attempt + 1, last_err)
            except TimeoutError as exc:
                # Provider slowness (M2.7 always reasons) must never fail the document.
                # Retry is futile here and would risk the RQ job budget on multi-section
                # docs, so fall back at once to source-grounded units.
                last_err = str(exc)
                logger.warning("digest timed out, using deterministic fallback: %s", last_err)
                return self._fallback_digest_section(section)
        logger.warning("digest failed after retry; using deterministic fallback: %s", last_err)
        return self._fallback_digest_section(section)

    def _fallback_digest_section(self, section: str) -> tuple[str, list[dict]]:
        """Source-grounded fallback when the LLM digest returns unusable JSON."""
        blocks = _fallback_blocks(section)
        units = [_fallback_unit(block, index) for index, block in enumerate(blocks)]
        summary = blocks[0][:220] if blocks else ""
        return summary, units

    async def _store_units(self, doc, units: list[dict]) -> None:
        if not units:
            await self.chunks.replace_for_doc(doc, [])  # clear the document's chunks
            return
        # Batch-embed one combined string per unit (content + summary + questions).
        embed_inputs = []
        for u in units:
            pieces = [u.get("contextual_text") or u["content"]]
            if u["summary"]:
                pieces.append(u["summary"])
            pieces.extend(u["questions"])
            embed_inputs.append("\n".join(pieces))
        vectors = await self._embed_batch(embed_inputs)
        await self.chunks.replace_for_doc(doc, list(zip(units, vectors)))

    async def _persist_canonical_bus_timetable(self, doc, canonical_doc) -> None:
        from app.services.knowledge.bus_timetable.repository import BusTimetableRepo

        meta = canonical_doc.metadata
        project_slug = str(meta["project_slug"])
        company_name = str(meta.get("company_name") or "").strip()
        if not company_name:
            logger.warning("canonical bus timetable has no configured company name; skipping")
            return
        await BusTimetableRepo(self.db).upsert(
            canonical_doc.bus_timetable,
            project_slug=project_slug,
            company_name=company_name,
            source_name=doc.file_name,
            source_ref=str(doc.id),
            version=str(meta.get("doc_version") or ""),
            source_type="canonical_markdown",
        )

    async def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed many texts; prefer a batch call when the embedder supports it."""
        batch = getattr(self.embedder, "batch", None)
        if not callable(batch):
            return [await self.embedder(t) for t in texts]
        return await embed_with_fallback(batch, texts, label="embedder batch")

    async def build_project_index(self, project_id: uuid.UUID) -> None:
        """Regenerate the project's catalog card from usable units (master index)."""
        rows = await self.index.fetch_usable_corpus(project_id)
        if not rows:
            return
        corpus = "\n".join(f"- [{r.category}] {r.content}" for r in rows)
        raw = await self._llm_json_with_timeout(
            INDEX_SYSTEM_PROMPT, corpus, purpose="project index"
        )
        card = _parse_json_lenient(raw)
        if not isinstance(card, dict):
            return
        await self.index.update_card(
            project_id, str(card.get("summary") or "").strip() or None, card
        )
        # Feature-derived highlights are authoritative when present (override the LLM card).
        await self.index.sync_highlights(project_id)

    async def extract_product_features(self, doc, units: list[dict]) -> None:
        """LLM-extract the 11 worker product features for ``doc.project_id`` (best-effort).

        Keeps one job_feature_values row per active catalog feature. New concrete values
        update the project profile, but missing values from a newer upload do not erase
        older useful answers.
        """
        if doc.project_id is None:
            return
        catalog = await self.features.fetch_catalog()
        if not catalog:
            return
        corpus = (doc.raw_text or "").strip() or "\n".join(u["content"] for u in units)
        if not corpus.strip():
            return
        raw = await self._llm_json_with_timeout(
            _product_feature_prompt(catalog), corpus, purpose="product feature extraction"
        )
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
        await self.features.merge_for_project(doc.project_id, doc.id, rows)
        await self.index.sync_highlights(doc.project_id)

    async def sync_canonical_product_features(
        self, doc, canonical_doc: ParsedKnowledgeDocument
    ) -> None:
        """Copy canonical Worker Features into the project feature read model.

        The canonical format is already curated and validator-gated, so this mirrors
        it directly into ``job_feature_values`` without MiniMax extraction.
        """
        if doc.project_id is None:
            return
        catalog = await self.features.fetch_catalog()
        if not catalog:
            return
        by_key = _canonical_feature_answers(canonical_doc)
        rows = []
        for priority, c in enumerate(catalog):
            answer = by_key.get(c.feature_key)
            raw = None
            if answer:
                raw = {
                    "feature_key": c.feature_key,
                    "value_text": answer,
                    "value_json": {},
                    "strength_score": float(c.default_importance_score or 0.85),
                    "is_highlight": priority < 6,
                    "is_missing": False,
                    "needs_clarification": False,
                    "evidence_text": answer[:1000],
                }
            rows.append((c, _coerce_feature(raw, c)))
        await self.features.merge_for_project(doc.project_id, doc.id, rows)
        await self.index.sync_highlights(doc.project_id)

    async def _update_canonical_project_card(
        self, doc, canonical_doc: ParsedKnowledgeDocument
    ) -> None:
        if doc.project_id is None:
            return
        meta = canonical_doc.metadata
        company = str(meta.get("company_name") or "").strip()
        summary = _canonical_project_summary(canonical_doc)
        card = {
            "summary": summary,
            "key_roles": list(
                dict.fromkeys(
                    str(chunk.entities.get("job_title") or "").strip()
                    for chunk in canonical_doc.chunks
                    if chunk.category == "job" and chunk.entities.get("job_title")
                )
            ),
            "location": _canonical_location(canonical_doc),
            "highlights": [],
            "company_name": company,
            "source_document_id": str(doc.id),
            "canonical": True,
        }
        await self.index.update_card(doc.project_id, summary, card)
        await self.index.sync_highlights(doc.project_id)

    async def _llm_json_with_timeout(self, system: str, user: str, *, purpose: str) -> str:
        timeout = (
            self._call_timeout
            if self._call_timeout is not None
            else get_settings().active_llm_digest_timeout
        )
        try:
            return await asyncio.wait_for(self.llm_json(system, user), timeout=timeout)
        except TimeoutError as exc:
            raise TimeoutError(
                f"{get_settings().active_llm_provider} {purpose} timed out after {timeout}s"
            ) from exc

    async def _set_stage(
        self, doc, stage: str, *, status: str | None = None, error: str | None = None
    ) -> None:
        doc.stage = stage
        doc.updated_at = datetime.now(UTC)
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


def _fallback_blocks(section: str) -> list[str]:
    paragraphs = [p.strip(" \t\r\n-•") for p in re.split(r"\n\s*\n+", section or "") if p.strip()]
    blocks: list[str] = []
    for paragraph in paragraphs:
        if len(paragraph) <= 1200:
            blocks.append(paragraph)
            continue
        sentences = re.split(r"(?<=[.!?。])\s+", paragraph)
        current = ""
        for sentence in sentences:
            candidate = f"{current} {sentence}".strip()
            if current and len(candidate) > 1200:
                blocks.append(current)
                current = sentence.strip()
            else:
                current = candidate
        if current:
            blocks.append(current)
    return [b for b in blocks if b]


def _canonical_feature_answers(canonical_doc: ParsedKnowledgeDocument) -> dict[str, str]:
    answers: dict[str, str] = {}
    for chunk in canonical_doc.chunks:
        if chunk.category != "feature":
            continue
        match = re.match(r"^Feature:\s*([a-z0-9_]+)\s*$", chunk.section_title, flags=re.IGNORECASE)
        if match is None:
            continue
        answer = _canonical_field_block(chunk.content, "Answer") or chunk.content
        answer = _compact_text(answer)
        if answer:
            answers[match.group(1)] = answer
    return answers


def _canonical_project_summary(canonical_doc: ParsedKnowledgeDocument) -> str:
    overview = next(
        (
            chunk.content
            for chunk in canonical_doc.chunks
            if chunk.section_title == "Company Overview"
        ),
        "",
    )
    return _compact_text(overview) or canonical_doc.document_summary


def _canonical_location(canonical_doc: ParsedKnowledgeDocument) -> str:
    overview = next(
        (
            chunk.content
            for chunk in canonical_doc.chunks
            if chunk.section_title == "Company Overview"
        ),
        "",
    )
    match = re.search(r"\bat\s+(.+?)(?:\.|$)", overview, flags=re.IGNORECASE)
    return _compact_text(match.group(1)) if match else ""


def _canonical_field_block(content: str, field: str) -> str | None:
    match = re.search(
        rf"^{re.escape(field)}:\s*(.*?)(?=\n[A-Z][A-Za-z _-]*:\s*|\Z)",
        content,
        flags=re.MULTILINE | re.DOTALL,
    )
    if match is None:
        return None
    return match.group(1).strip()


def _compact_text(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _fallback_unit(block: str, index: int) -> dict:
    lowered = block.lower()
    category = "other"
    if any(k in lowered for k in ("lương", "thu nhập", "trợ cấp", "thưởng")):
        category = "salary"
    elif any(k in lowered for k in ("ca ", "lịch", "nghỉ", "giờ", "tăng ca")):
        category = "schedule"
    elif any(k in lowered for k in ("liên hệ", "hotline", "admin", "sđt", "zalo")):
        category = "contact"
    elif any(k in lowered for k in ("yêu cầu", "hồ sơ", "cccd", "đào tạo", "quy định")):
        category = "policy"
    elif any(k in lowered for k in ("tuyển", "vị trí", "công việc", "địa điểm")):
        category = "job"
    elif any(k in lowered for k in ("ký túc", "ăn", "xe", "bảo hiểm", "phúc lợi")):
        category = "benefits"

    location = None
    if "hải phòng" in lowered:
        location = "Hải Phòng"
    elif "tràng duệ" in lowered:
        location = "KCN Tràng Duệ"

    entities = {}
    if location:
        entities["location"] = location
    return {
        "content": block,
        "source_quote": block[:1000],
        "summary": block[:160],
        "questions": [_fallback_question(category)],
        "category": category,
        "entities": entities,
        "source_anchor": f"fallback §{index + 1}",
        "confidence": "medium",
        "is_inference": False,
    }


def _fallback_question(category: str) -> str:
    return {
        "salary": "Thông tin này nói gì về thu nhập, giá hoặc hỗ trợ?",
        "schedule": "Thông tin này nói gì về lịch hoặc thời gian áp dụng?",
        "contact": "Thông tin này nêu kênh liên hệ nào?",
        "policy": "Thông tin này nêu yêu cầu hoặc quy định nào?",
        "job": "Thông tin này nói gì về công việc hoặc nội dung cung cấp?",
        "benefits": "Thông tin này nói gì về quyền lợi hoặc hỗ trợ?",
    }.get(category, "Thông tin này trả lời câu hỏi nào?")
