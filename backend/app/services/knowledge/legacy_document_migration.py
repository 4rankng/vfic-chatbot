"""Fail-closed planning helpers for the legacy document-to-release migration."""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass
from typing import Iterable

from app.services.knowledge.text_ingestion import kb_text_stats


class LegacyDocumentMigrationPlanError(ValueError):
    """The current data cannot be migrated safely without operator intervention."""


@dataclass(frozen=True)
class LegacyDocumentMigrationCandidate:
    """Minimal source metadata required to plan a release migration."""

    document_id: uuid.UUID
    project_id: uuid.UUID | None
    raw_text: str | None


@dataclass(frozen=True)
class LegacyDocumentMigrationProjectPlan:
    """One draft release that a future approved apply step would create."""

    project_id: uuid.UUID
    active_kb_version_id: uuid.UUID
    source_documents: tuple[tuple[uuid.UUID, str], ...]


def build_legacy_document_migration_plan(
    candidates: Iterable[LegacyDocumentMigrationCandidate],
    *,
    active_kb_versions: dict[uuid.UUID, uuid.UUID | None],
) -> tuple[LegacyDocumentMigrationProjectPlan, ...]:
    """Build a read-only, deterministic plan without accepting ambiguous sources."""
    grouped: dict[uuid.UUID, list[tuple[uuid.UUID, str]]] = defaultdict(list)

    for candidate in candidates:
        if candidate.project_id is None:
            raise LegacyDocumentMigrationPlanError(
                f"document {candidate.document_id} has no project and cannot be migrated"
            )
        stats = kb_text_stats(candidate.raw_text or "")
        if not stats.normalized_text:
            raise LegacyDocumentMigrationPlanError(
                f"document {candidate.document_id} has no source text and cannot be migrated"
            )
        grouped[candidate.project_id].append(
            (
                candidate.document_id,
                stats.content_sha256,
            )
        )

    plans: list[LegacyDocumentMigrationProjectPlan] = []
    for project_id in sorted(grouped, key=str):
        active_kb_version_id = active_kb_versions.get(project_id)
        if active_kb_version_id is None:
            raise LegacyDocumentMigrationPlanError(
                f"project {project_id} has no active KB version and cannot be migrated"
            )
        plans.append(
            LegacyDocumentMigrationProjectPlan(
                project_id=project_id,
                active_kb_version_id=active_kb_version_id,
                source_documents=tuple(sorted(grouped[project_id], key=lambda item: str(item[0]))),
            )
        )
    return tuple(plans)
