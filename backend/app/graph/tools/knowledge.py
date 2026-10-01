"""Knowledge search tool: project-scoped semantic retrieval over the usable KB.

FAQ-first pre-pass plus single-flight request coalescing so concurrent turns
asking the same uncached question share one computation. All SQL lives in
``app.services.retrieval.RetrievalRepository`` (behind the ``GraphRetrievalPort``);
this module owns the embedding + citation formatting only.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable, Iterable
from itertools import islice
from typing import Any

from app.core.cache import cache_get_json, cache_set_json, cache_version
from app.core.config import get_settings
from app.core.vector import vec_literal
from app.graph.embed_cache import cached_embed
from app.graph.llm import Embedder
from app.graph.ports import GraphRetrievalPort
from app.graph.tools._shared import _cache_digest
from app.project_knowledge.domain.legacy_job_references import strip_legacy_job_reference_source

logger = logging.getLogger(__name__)

# --- Rendered-evidence budget -------------------------------------------------
#
# Prod measurement (2026-09, 284 turns/24h): tool-round turns rendered up to
# ``top_k=25`` knowledge rows with unbounded per-row text, pushing the agent
# prompt to 26k-33k tokens and 18-26s of LLM time per round. Retrieval already
# returns rows best-first (FAQ prepass, then similarity order), so capping the
# rendered evidence AFTER ranking keeps the highest-value citations while
# bounding the prompt. Ranking, thresholds, and SQL are untouched.
#
# The budget is deliberately generous: the cost being bounded is decode time,
# which is dominated by OUTPUT tokens, not by prefill (measured TTFT is only
# 0.8-2.2s at a 15-16k prompt), while dropping a row can lose the one fact a
# multi-part question needed. Prod chunk sizes: 1164 chunks, p50 268 chars, p90
# 521, max 90,455 — so 20 rows x 640 chars is ~13k chars of ordinary evidence
# (the pre-cap normal case) and the char ceiling exists to clip the pathological
# document, not to trim normal retrieval. Lower these only with golden-set
# evidence that recall survives.
_MAX_EVIDENCE_ROWS = 20
_MAX_EVIDENCE_CHARS = 20000
_MAX_EVIDENCE_ROW_CHARS = 4000
_EVIDENCE_CACHE_FORMAT = "project-evidence-v2"


def _format_knowledge_row(r) -> str:
    """Format a single retrieval row into the agent-readable citation string."""
    metadata = getattr(r, "metadata", None) or {}
    citation = metadata.get("citation") or {}
    document_meta = metadata.get("document_metadata") or {}
    chunk_meta = metadata.get("chunk_metadata") or {}
    source = citation.get("label") or document_meta.get("title") or "Nguồn kiến thức"
    anchor = citation.get("source_anchor") or metadata.get("source_anchor")
    source_file = getattr(r, "source_file", None)
    line_start = getattr(r, "line_start", None)
    line_end = getattr(r, "line_end", None)
    effective = document_meta.get("effective_from")
    if document_meta.get("effective_to"):
        effective = (
            f"{effective} đến {document_meta.get('effective_to')}"
            if effective
            else document_meta.get("effective_to")
        )
    route = chunk_meta.get("route_id")
    suffix = f" Nguồn: {source}"
    project_name = getattr(r, "project_name", None)
    project_slug = getattr(r, "project_slug", None)
    category = getattr(r, "category", None) or metadata.get("category")
    if project_name or project_slug:
        suffix += f"; dự án: {project_name or project_slug}"
        if project_name and project_slug:
            suffix += f" ({project_slug})"
    if category:
        suffix += f"; mục: {category}"
    if source_file:
        suffix += f"; file: {source_file}"
    if line_start:
        suffix += f"; dòng: {line_start}"
        if line_end and line_end != line_start:
            suffix += f"-{line_end}"
    if anchor:
        suffix += f" ({anchor})"
    if effective:
        suffix += f"; hiệu lực: {effective}"
    if route:
        suffix += f"; route_id: {route}"
    # Prefer source_quote (precise evidence) over raw content;
    # append summary as supplementary context when available.
    quote = getattr(r, "source_quote", None)
    summary = getattr(r, "summary", None)
    clean_quote = strip_legacy_job_reference_source(str(quote)) if quote else ""
    primary = clean_quote if clean_quote.strip() else strip_legacy_job_reference_source(str(r.content))
    parts: list[str] = [primary] if primary.strip() else []
    if summary:
        clean_summary = strip_legacy_job_reference_source(str(summary))
        if clean_summary.strip():
            parts.append(f"Tóm tắt: {clean_summary}")
    content = "\n".join(parts)
    return f"- {content}\n  {suffix}"


def _truncate_evidence_line(rendered: str, limit: int) -> str:
    """Clip one rendered row to ``limit`` chars, keeping its source suffix.

    ``_format_knowledge_row`` renders ``- {content}\\n  {suffix}``. When a single
    row is longer than the whole budget, keep the suffix (citation integrity) and
    clip the content. Falls back to a plain clip when even the suffix cannot fit.
    """
    if len(rendered) <= limit:
        return rendered
    head, sep, suffix = rendered.partition("\n  ")
    if sep and len(sep) + len(suffix) + 1 <= limit:
        room = limit - len(sep) - len(suffix) - 1
        return head[:room] + "…" + sep + suffix
    return rendered[:limit]


def _render_capped_evidence(rows: Iterable[Any]) -> list[str]:
    """Render ranked rows within the evidence budget, best rows first.

    The caller passes already-ranked rows (FAQ prepass, then similarity order);
    this drops the tail once either the per-round row cap or the total character
    cap is reached. With multiple hits, oversized individual rows are clipped
    before they can consume the entire budget; ordinary rows keep their full
    text. A sole hit can use the complete budget. The
    citation/source suffix format from ``_format_knowledge_row`` is preserved;
    only how many rows are rendered (and, for an oversized sole row, how much
    content survives) changes.
    """
    lines: list[str] = []
    total = 0
    selected = list(islice(rows, _MAX_EVIDENCE_ROWS))
    row_budget = _MAX_EVIDENCE_CHARS if len(selected) == 1 else _MAX_EVIDENCE_ROW_CHARS
    for row in selected:
        rendered = _format_knowledge_row(row)
        rendered = _truncate_evidence_line(rendered, row_budget)
        remaining = _MAX_EVIDENCE_CHARS - total
        if len(rendered) > remaining:
            if not lines:
                # A single hit larger than the whole budget: keep it, clipped,
                # rather than returning no evidence at all.
                lines.append(_truncate_evidence_line(rendered, _MAX_EVIDENCE_CHARS))
            break
        lines.append(rendered)
        total += len(rendered)
    return lines


async def search_knowledge(
    retrieval: GraphRetrievalPort,
    embedder: Embedder,
    query: str,
    project_slug: str | None = None,
    top_k: int = 25,
    *,
    metrics: dict | None = None,
) -> str:
    """Project-scoped semantic search over usable knowledge (the `documents` VIEW).

    ``project_slug`` (from the master index) scopes retrieval to one product; omit it
    to search across all active projects. The agent is told to advise ONLY from this.

    FAQ-first pre-pass: canonical FAQ chunks (``category='faq'``) are retrieved with a
    higher similarity floor and prepended so the agent leads with curated answers.

    Semantic-cache entries are namespaced by the retrieval scope (sorted
    ``project_ids`` + ``top_k``), so a Page-scoped lookup — ``project_slug=None`` with
    the Page's non-empty ``project_ids`` — can never be served an answer cached
    against another Page's catalog.

    When ``metrics`` is provided, RAG cache hit/miss + lookup latency are recorded
    under ``metrics["rag_cache"]`` (``exact_hit``, ``semantic_hit``, ``semantic_sim``)
    and ``metrics["rag_cache_lookup_ms"]`` so the release gate can evaluate whether
    caching pays for itself from existing ``BotRun.stage_timings`` rows.
    """
    repo = retrieval
    project_ids: list[str] | None = None
    if project_slug:
        pid = await repo.project_id_by_slug(project_slug, active_only=True)
        if pid is None:
            return "Không tìm thấy thông tin phù hợp trong cơ sở dữ liệu."
        project_ids = [str(pid)]
    else:
        active_project_ids = getattr(repo, "active_project_ids", None)
        if active_project_ids is not None:
            project_ids = await active_project_ids()
            if not project_ids:
                return "Không tìm thấy thông tin phù hợp trong cơ sở dữ liệu."
    # The project-id list feeds the cache digest, so DB row order must never
    # leak into the key: sort here as well as in the repository query so the
    # digest does not depend on the port's ordering alone.
    if project_ids is not None:
        project_ids = sorted(project_ids)
    s = get_settings()
    knowledge_version = await cache_version("knowledge") if s.rag_cache_enabled else "0"
    cache_key = (
        "rag:knowledge:"
        f"{_cache_digest(query, project_slug, top_k, project_ids, knowledge_version, _EVIDENCE_CACHE_FORMAT)}"
    )

    # --- Cache-read window: wrap exact + semantic lookup together so the
    # lookup timer answers "is the cache paying for itself?" without including
    # the DB retrieval that follows. ---
    cache_t0 = time.monotonic()

    def _record_cache(
        *,
        exact_hit: bool | None = None,
        semantic_hit: bool | None = None,
        semantic_sim: float | None = None,
    ) -> None:
        if metrics is None:
            return
        metrics["rag_cache_lookup_ms"] = int(round((time.monotonic() - cache_t0) * 1000))
        bucket = metrics.setdefault("rag_cache", {})
        if exact_hit is not None:
            bucket["exact_hit"] = exact_hit
        if semantic_hit is not None:
            bucket["semantic_hit"] = semantic_hit
        if semantic_sim is not None:
            bucket["semantic_sim"] = round(semantic_sim, 3)

    if s.rag_cache_enabled:
        cached = await cache_get_json(cache_key)
        if isinstance(cached, str):
            _record_cache(exact_hit=True, semantic_hit=False)
            return strip_legacy_job_reference_source(cached)
        _record_cache(exact_hit=False)
    else:
        _record_cache(exact_hit=False)

    # --- Single-flight request coalescing (Tech-Lead Directive §6) ---
    # When N concurrent turns ask the same uncached question, only one process
    # calls the model; the others await the same result. The single-flight key
    # IS the full cache key (query + sorted project scope + knowledge
    # version), so scoped lookups coalesce safely too — the gate is only the
    # config flag.
    coalesce_enabled = getattr(s, "singleflight_enabled", False)
    if coalesce_enabled:
        result = await _search_knowledge_coalesced(
            cache_key=cache_key,
            compute=lambda: _search_knowledge_compute(
                embedder=embedder,
                query=query,
                repo=repo,
                top_k=top_k,
                project_ids=project_ids,
                project_slug=project_slug,
                cache_key=cache_key,
                s=s,
                metrics=metrics,
                _record_cache=_record_cache,
            ),
        )
        if result is not None:
            return strip_legacy_job_reference_source(result)
        # Single-flight unavailable (Redis down) → fall through to direct compute.

    result = await _search_knowledge_compute(
        embedder=embedder,
        query=query,
        repo=repo,
        top_k=top_k,
        project_ids=project_ids,
        project_slug=project_slug,
        cache_key=cache_key,
        s=s,
        metrics=metrics,
        _record_cache=_record_cache,
    )
    return strip_legacy_job_reference_source(result)


async def _search_knowledge_coalesced(
    *, cache_key: str, compute: Callable[[], Awaitable[str]]
) -> str | None:
    """Try single-flight coalescing around ``compute``. Returns None if unavailable.

    Leader: runs ``compute`` and publishes the result.
    Follower: awaits the leader's result via pub/sub (with a cache re-check).
    Returns ``None`` when Redis is unavailable so the caller falls back to a
    plain ``compute()`` call without coalescing.
    """
    from app.core import singleflight

    # Single-flight key is the same as the cache key — turns asking the same
    # question share one computation. The cache_key already encodes query +
    # project + knowledge_version, so it's the correct coalescing axis.
    sf_key = cache_key
    leader_id = await singleflight.acquire(sf_key)
    if leader_id is not None:
        # We're the leader — compute and publish.
        try:
            return await singleflight.run_as_leader(sf_key, leader_id, compute)
        except Exception:  # noqa: BLE001 — leader error: fall back to direct compute
            logger.warning("singleflight leader compute failed; falling back", exc_info=True)
            return None

    # We're a follower — await the leader's result.
    async def _cache_read():
        cached = await cache_get_json(cache_key)
        return cached if isinstance(cached, str) else None

    try:
        return await singleflight.await_result(sf_key, cache_read=_cache_read, timeout=8.0)
    except asyncio.TimeoutError:
        logger.info("singleflight follower timed out; falling back to direct compute")
        return None
    except singleflight.SingleFlightError:
        logger.info("singleflight leader errored; follower falling back to direct compute")
        return None


async def _search_knowledge_compute(
    *,
    embedder,
    query: str,
    repo,
    top_k: int,
    project_ids: list[str] | None,
    project_slug: str | None,
    cache_key: str,
    s,
    metrics: dict | None,
    _record_cache,
) -> str:
    """The expensive slice of search_knowledge: embed + retrieval + format + cache writes.

    Extracted so it can be wrapped by single-flight coalescing. The leader runs
    this directly; followers await its result via pub/sub.
    """
    # Capture the namespace before provider/retrieval work. If a KB update
    # invalidates it while this read finishes, old evidence stays in the old
    # namespace rather than poisoning the generation of the updated KB.
    sem_enabled = getattr(s, "semantic_cache_enabled", False)
    semantic_generation = (
        await cache_version("semantic_cache") if sem_enabled and not project_slug else None
    )
    raw_emb = await cached_embed(embedder, query)
    emb = vec_literal(raw_emb)

    # Semantic cache (Phase 5): before hitting the DB, check if a *paraphrased*
    # query was recently answered. Only lookups that are not slug-scoped are
    # cached, and the entry is namespaced by the exact retrieval scope (sorted
    # ``project_ids`` + ``top_k``): a Page-scoped conversation arrives here with
    # ``project_slug=None`` but a non-empty ``project_ids``, so "no slug" alone
    # must never be treated as the deployment-wide catalog (REL-07). Conservative
    # threshold.
    sem_scope: str | None = None
    if sem_enabled and not project_slug:
        from app.graph.semantic_cache import scope_key

        sem_scope = f"{_EVIDENCE_CACHE_FORMAT}:{scope_key(project_ids, top_k)}"

    if sem_scope is not None:
        from app.graph.semantic_cache import semantic_cache_get

        sem_hit = await semantic_cache_get(
            raw_emb, scope=sem_scope, namespace_version=semantic_generation
        )
        if sem_hit is not None:
            logger.debug("search_knowledge semantic cache hit (sim=%.3f)", sem_hit.similarity)
            _record_cache(semantic_hit=True, semantic_sim=sem_hit.similarity)
            return sem_hit.result
        _record_cache(semantic_hit=False)
    elif metrics is not None and not sem_enabled:
        # Semantic cache disabled — record the miss explicitly so dashboard
        # queries can distinguish "disabled" from "enabled-and-missed".
        metrics.setdefault("rag_cache", {})["semantic_hit"] = False

    # FAQ-first pre-pass: prepend canonical FAQ answers when a strong match exists.
    faq_rows = await repo.match_faq(emb, top_k=3, project_ids=project_ids)
    faq_ids: set[str] = {str(getattr(r, "id", "")) for r in faq_rows}

    rows = await repo.match_documents(emb, top_k, "{}", project_ids=project_ids, query_text=query)
    # A transient vector failure is not a confirmed absence of project facts.
    # Keep partial FAQ evidence usable, but let the next turn retry retrieval.
    retrieval_complete = getattr(repo, "last_match_degraded", None) is None
    if not rows and not faq_rows:
        result = "Không tìm thấy thông tin phù hợp trong cơ sở dữ liệu."
        if s.rag_cache_enabled and retrieval_complete:
            await cache_set_json(cache_key, result, s.rag_result_cache_ttl_seconds)
        return result
    # Ranked order: FAQ prepass first, then similarity order. Dedupe FAQ chunks
    # out of ``rows`` BEFORE capping so the budget is spent on distinct hits.
    ordered: list[Any] = list(faq_rows)
    for r in rows:
        if faq_ids and str(getattr(r, "id", "")) in faq_ids:
            continue
        ordered.append(r)
    rendered = _render_capped_evidence(ordered)
    logger.debug(
        "search_knowledge: %d rows (project=%s), %d faq rows, %d rendered",
        len(rows),
        project_slug,
        len(faq_rows),
        len(rendered),
    )
    # ``ordered`` is FAQ-first, so the leading rendered lines are the FAQ ones.
    kept_faq = min(len(faq_rows), len(rendered))
    lines: list[str] = []
    if kept_faq:
        lines.append("CÂU HỎI THƯỜNG GẶP (câu trả lời chuẩn):")
        lines.extend(rendered[:kept_faq])
    lines.extend(rendered[kept_faq:])
    result = "\n".join(lines)
    if s.rag_cache_enabled and retrieval_complete:
        await cache_set_json(cache_key, result, s.rag_result_cache_ttl_seconds)
    # Store in the semantic cache for future paraphrased hits (unscoped lookups
    # only), under the same scope namespace the read above used.
    if sem_scope is not None and retrieval_complete:
        from app.graph.semantic_cache import semantic_cache_put

        await semantic_cache_put(
            raw_emb, result, scope=sem_scope, namespace_version=semantic_generation
        )
    return result
