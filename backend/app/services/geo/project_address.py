"""Resolve a project's work address from its KB brief and geocode it.

The recruiter's brief is the only place the verbatim work address lives:
``ProjectCreate`` shortens it to the city before ``buildJobsMarkdown``, so
``Job.address`` / ``index_card['location']`` carry the short value and the full
brief survives only as ``KnowledgeDocument.raw_text``. This module closes that
gap for the geo-distance feature:

1. the project's LLM extracts the work address from the brief
   (``ADDRESS_EXTRACTION_SYSTEM_PROMPT``),
2. the value is GROUNDED against that same brief — an address the document does
   not actually contain is dropped, never stored (an LLM that "completes" a
   plausible district would otherwise produce a confident wrong distance),
3. the grounded address is geocoded and stored with its coordinates.

Two entry points, split by who authored the address:

* ``refresh_from_kb`` — pipeline-owned. Runs the LLM extraction once per
  project; ``extracted_address`` is the cache, so a re-ingest of an
  already-resolved project costs no model call. ``force`` re-geocodes a stored
  address without re-running the model.
* ``refresh_from_address`` — human-authored addresses (category ``jobs``
  records, the admin discovery card). No LLM and no grounding; it only defers to
  the pipeline while the pipeline has not resolved the project yet.

Everything is best-effort: a geocoder outage, an LLM failure, or a missing
document logs and returns. Ingest and the admin write path must never fail
because of this feature — a project without coordinates simply carries no
``distance_km`` in the catalog tool.
"""

from __future__ import annotations

import logging
import re
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.company import Project
from app.services.geo.geocoding import geocode
from app.services.knowledge.coercion import _parse_json_lenient
from app.services.knowledge.prompts import ADDRESS_EXTRACTION_SYSTEM_PROMPT
from app.shared.domain.text import normalize_vietnamese_text

logger = logging.getLogger(__name__)

# Share of the extracted address's terms that must appear in the brief for the
# address to be trusted. Below this the value reads as invented (or as a
# paraphrase of a different address) and is treated as unresolved.
_GROUNDING_MIN_SHARE = 0.8
_TERM_RE = re.compile(r"[a-z0-9]+")


def ground_address(address: str, raw_text: str) -> str | None:
    """Return ``address`` when the brief actually contains it, else ``None``."""
    terms = tuple(
        term
        for term in dict.fromkeys(_TERM_RE.findall(normalize_vietnamese_text(address)))
        if len(term) > 1
    )
    if not terms:
        return None
    normalized = normalize_vietnamese_text(raw_text)
    hits = sum(1 for term in terms if term in normalized)
    return address if hits / len(terms) >= _GROUNDING_MIN_SHARE else None


async def extract_project_address(llm_json, raw_text: str) -> str | None:
    """Ask the project's LLM for the brief's work address; ``None`` when absent."""
    try:
        raw = await llm_json(ADDRESS_EXTRACTION_SYSTEM_PROMPT, raw_text)
        payload = _parse_json_lenient(raw)
        if not isinstance(payload, dict) or "address" not in payload:
            return None
        value = payload["address"]
        if not isinstance(value, str):
            return None
        return value.strip() or None
    except Exception:  # noqa: BLE001 — extraction must never break ingest
        logger.warning("project address extraction failed", exc_info=True)
        return None


async def _geocode_and_store(db: AsyncSession, project: Project, address: str) -> None:
    """Store ``address`` plus its coordinates; leave the row untouched on a miss."""
    coords = await geocode(address)
    if coords is None:
        logger.warning("project geocode failed project_id=%s", project.id)
        return
    project.extracted_address = address
    project.latitude, project.longitude = coords


async def refresh_from_kb(
    db: AsyncSession,
    project_id: uuid.UUID,
    *,
    llm_json,
    force: bool = False,
) -> None:
    """Resolve + geocode a project's work address from its latest upload brief.

    No-op when the project is already resolved (unless ``force`` re-geocodes the
    stored address). Never raises; does not commit — the caller owns the
    transaction.
    """
    try:
        # Deferred: ``app.services.project`` re-exports ProjectService, which
        # imports this module — a module-level import here is a cycle.
        from app.services.project.repository import ProjectRepository

        project = await db.get(Project, project_id)
        if project is None:
            return
        address = (project.extracted_address or "").strip()
        if address:
            if force:
                await _geocode_and_store(db, project, address)
            return
        doc = await ProjectRepository(db).get_latest_document_with_text(project_id)
        raw_text = (doc.raw_text if doc is not None else "") or ""
        if not raw_text.strip():
            return
        extracted = await extract_project_address(llm_json, raw_text)
        address = ground_address(extracted or "", raw_text)
        if address is None:
            return
        await _geocode_and_store(db, project, address)
    except Exception:  # noqa: BLE001 — never fail the caller's write
        logger.warning("project address refresh failed project_id=%s", project_id, exc_info=True)


async def refresh_from_address(db: AsyncSession, project_id: uuid.UUID, address: str) -> None:
    """Geocode a human-authored address; defer to the pipeline while unresolved.

    ``extracted_address`` is the pipeline's result for the project, so a value
    already there wins: this path must not overwrite an address the LLM grounded
    against the brief with a projection-rendered one.
    """
    try:
        project = await db.get(Project, project_id)
        if project is None:
            return
        if (project.extracted_address or "").strip():
            return
        value = (address or "").strip()
        if not value:
            return
        await _geocode_and_store(db, project, value)
    except Exception:  # noqa: BLE001 — never fail the caller's write
        logger.warning(
            "project address refresh failed project_id=%s", project_id, exc_info=True
        )
