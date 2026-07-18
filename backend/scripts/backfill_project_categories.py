#!/usr/bin/env python3
"""Backfill a legacy RAG Project's category authorities from current DB facts.

Dry-run reports the categories and row counts that can be migrated. Apply creates
validated revisions, embeds them, rebuilds derived jobs/bus projections, and
switches authority only after every supported category is active.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from collections import defaultdict

import yaml
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import bump_kb_caches
from app.core.db import async_session, engine
from app.models.bus import BusRoute, BusStop
from app.models.company import Project
from app.models.knowledge import (
    KnowledgeCategory,
    KnowledgeCategoryRevision,
    KnowledgeCategoryRevisionStatus,
    KnowledgeChunk,
)
from app.models.user import Role, User
from app.models.worker_feature import JobFeatureValue, WorkerFeatureCatalog
from app.schemas.knowledge_categories import CategoryDocument, KnowledgeCategoryKey
from app.services.audit_service import record_audit
from app.services.integration_settings import IntegrationSettingsService
from app.services.knowledge.category_contracts import (
    CATEGORY_DEFINITIONS,
    MAX_CATEGORY_YAML_BYTES,
    category_checksum,
)
from app.services.knowledge.category_service import KnowledgeCategoryService
from app.services.knowledge.legacy_category_backfill import (
    LegacyCategorySnapshot,
    LegacyFaq,
    LegacyFeature,
    LegacyRoute,
    LegacyStop,
    build_legacy_category_documents,
)
from app.services.project.mapping import _faq_answer_from_content


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-slug", required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    parser.add_argument(
        "--activate-authority",
        action="store_true",
        help="Hide legacy chunks after a successful apply; omit during parity validation.",
    )
    args = parser.parse_args(argv)
    if args.activate_authority and not args.apply:
        parser.error("--activate-authority requires --apply")
    return args


async def _load_snapshot(db: AsyncSession, project: Project) -> LegacyCategorySnapshot:
    feature_rows = (
        await db.execute(
            select(JobFeatureValue, WorkerFeatureCatalog)
            .join(WorkerFeatureCatalog, WorkerFeatureCatalog.id == JobFeatureValue.feature_id)
            .where(
                JobFeatureValue.project_id == project.id,
                WorkerFeatureCatalog.is_active.is_(True),
                JobFeatureValue.is_missing.is_(False),
                JobFeatureValue.needs_clarification.is_(False),
                func.length(func.trim(JobFeatureValue.value_text)) > 0,
            )
            .order_by(JobFeatureValue.display_priority, WorkerFeatureCatalog.feature_key)
        )
    ).all()
    features = tuple(
        LegacyFeature(
            key=catalog.feature_key,
            value_text=value.value_text,
            value_json=value.value_json or {},
            evidence_text=value.evidence_text,
        )
        for value, catalog in feature_rows
    )

    route_rows = list(
        (
            await db.scalars(
                select(BusRoute)
                .where(BusRoute.project_id == project.id)
                .order_by(
                    BusRoute.route_name,
                    BusRoute.shift,
                    BusRoute.direction,
                    BusRoute.id,
                )
            )
        ).all()
    )
    stops_by_route: dict[uuid.UUID, list[BusStop]] = defaultdict(list)
    if route_rows:
        stop_rows = (
            await db.scalars(
                select(BusStop)
                .where(BusStop.route_id.in_([route.id for route in route_rows]))
                .order_by(BusStop.route_id, BusStop.stop_order, BusStop.id)
            )
        ).all()
        for stop in stop_rows:
            stops_by_route[stop.route_id].append(stop)
    routes = tuple(
        LegacyRoute(
            source_id=str(route.id),
            route_key=route.route_group_key or route.route_no or route.route_name,
            name=route.route_name,
            shift=route.shift,
            direction=route.direction,
            service_days=tuple(
                str(item) for item in (route.metadata_ or {}).get("service_days", [])
            ),
            fee_vnd=(route.metadata_ or {}).get("fee_vnd"),
            notes=route.notes,
            stops=tuple(
                LegacyStop(
                    order=index,
                    name=stop.stop_name,
                    scheduled_time=stop.scheduled_time,
                    address=stop.raw_stop_text,
                )
                for index, stop in enumerate(stops_by_route[route.id], start=1)
            ),
        )
        for route in route_rows
    )

    visible_chunks = [
        KnowledgeChunk.project_id == project.id,
        KnowledgeChunk.category_revision_id.is_(None),
    ]
    if project.active_kb_version_id is not None:
        visible_chunks.append(KnowledgeChunk.kb_version_id == project.active_kb_version_id)
    faq_chunks = (
        await db.scalars(
            select(KnowledgeChunk)
            .where(*visible_chunks, KnowledgeChunk.category == "faq")
            .order_by(KnowledgeChunk.created_at.desc(), KnowledgeChunk.id)
        )
    ).all()
    faqs = tuple(
        LegacyFaq(
            question=chunk.questions[0],
            answer=_faq_answer_from_content(chunk.content, chunk.questions[0]),
            variants=tuple(chunk.questions[1:]),
            required_terms=tuple(chunk.required_terms or []),
            forbidden_terms=tuple(chunk.forbidden_terms or []),
        )
        for chunk in faq_chunks
        if chunk.questions and chunk.questions[0].strip()
    )

    job_chunks = (
        await db.scalars(
            select(KnowledgeChunk)
            .where(*visible_chunks, KnowledgeChunk.category == "job")
            .order_by(KnowledgeChunk.created_at.desc(), KnowledgeChunk.id)
        )
    ).all()
    titles = tuple(
        dict.fromkeys(
            str(chunk.entities.get("job_title") or "").strip()
            for chunk in job_chunks
            if str(chunk.entities.get("job_title") or "").strip()
        )
    )
    evidence = tuple(
        dict.fromkeys(
            str(chunk.summary or chunk.content).strip()
            for chunk in job_chunks
            if str(chunk.summary or chunk.content).strip()
            and (
                "tuyển" in str(chunk.summary or chunk.content).casefold()
                or "công việc" in str(chunk.summary or chunk.content).casefold()
            )
        )
    )
    return LegacyCategorySnapshot(
        project_name=project.name,
        project_aliases=tuple(project.aliases),
        job_titles=titles,
        job_evidence=evidence,
        features=features,
        routes=routes,
        faqs=faqs,
    )


def _source_yaml(document: CategoryDocument) -> str:
    return yaml.safe_dump(
        document.model_dump(mode="json", exclude_none=True),
        allow_unicode=True,
        sort_keys=False,
        width=100,
    )


def _report(documents: dict[KnowledgeCategoryKey, CategoryDocument]) -> dict[str, object]:
    rows = {}
    yaml_bytes = {}
    for definition in CATEGORY_DEFINITIONS:
        document = documents.get(definition.key)
        rows[definition.key.value] = (
            len(getattr(document, definition.list_field)) if document is not None else 0
        )
        yaml_bytes[definition.key.value] = (
            len(_source_yaml(document).encode("utf-8")) if document is not None else 0
        )
        if yaml_bytes[definition.key.value] > MAX_CATEGORY_YAML_BYTES:
            raise RuntimeError(
                f"generated {definition.key.value} YAML exceeds the 500 KB category limit"
            )
    return {
        "supported_category_count": len(documents),
        "unsupported_categories": [key for key, count in rows.items() if count == 0],
        "rows": rows,
        "yaml_bytes": yaml_bytes,
    }


async def _apply(
    db: AsyncSession,
    project: Project,
    documents: dict[KnowledgeCategoryKey, CategoryDocument],
    *,
    activate_authority: bool,
) -> None:
    admin = await db.scalar(
        select(User)
        .where(User.role == Role.admin, User.disabled.is_(False))
        .order_by(User.created_at, User.id)
        .limit(1)
    )
    if admin is None:
        raise RuntimeError("no active administrator exists to own the migration revisions")

    openrouter = await IntegrationSettingsService(db).resolve_openrouter()
    from app.graph.clients import build_embedder

    embedder = build_embedder(openrouter_api_key=openrouter.api_key)
    service = KnowledgeCategoryService(db)
    categories = {
        row.category_key: row
        for row in (
            await db.scalars(
                select(KnowledgeCategory).where(KnowledgeCategory.project_id == project.id)
            )
        ).all()
    }

    for definition in CATEGORY_DEFINITIONS:
        document = documents.get(definition.key)
        if document is None:
            continue
        category = categories.get(definition.key.value)
        if category is None:
            raise RuntimeError(f"missing category slot: {definition.key.value}")
        expected_checksum = category_checksum(document)
        if category.active_revision_id is not None:
            active = await db.get(KnowledgeCategoryRevision, category.active_revision_id)
            if active is not None and active.content_sha256 == expected_checksum:
                continue
            raise RuntimeError(
                f"category {definition.key.value} already has different active content"
            )
        latest = await db.scalar(
            select(func.max(KnowledgeCategoryRevision.revision_no)).where(
                KnowledgeCategoryRevision.category_id == category.id
            )
        )
        revision = KnowledgeCategoryRevision(
            category_id=category.id,
            revision_no=int(latest or 0) + 1,
            status=KnowledgeCategoryRevisionStatus.STAGED,
            source_filename=f"legacy-db-{definition.template_filename}",
            source_yaml=_source_yaml(document),
            normalized_payload=document.model_dump(mode="json"),
            content_sha256=expected_checksum,
            created_by=admin.id,
        )
        db.add(revision)
        await db.flush()
        await record_audit(
            db,
            action="backfill_project_knowledge_category",
            actor_id=admin.id,
            target_type="knowledge_category_revision",
            target_id=str(revision.id),
            payload={"project_id": str(project.id), "category": definition.key.value},
        )
        await db.commit()
        await service.activate_revision(
            revision.id,
            embedder,
            start_category_authority=False,
        )

    if activate_authority:
        project = await db.get(Project, project.id)
        if project is None:
            raise RuntimeError("project disappeared during category migration")
        project.category_authority_started = True
        await db.commit()
    await bump_kb_caches()


async def _run(args: argparse.Namespace) -> int:
    async with async_session() as db:
        project = await db.scalar(select(Project).where(Project.slug == args.project_slug))
        if project is None:
            print(f"project not found: {args.project_slug}", file=sys.stderr)
            return 2
        snapshot = await _load_snapshot(db, project)
        documents = build_legacy_category_documents(snapshot)
        report = {"project": project.slug, **_report(documents)}
        if args.dry_run:
            print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
            return 0
        await _apply(
            db,
            project,
            documents,
            activate_authority=args.activate_authority,
        )
        print(
            json.dumps(
                {
                    "applied": True,
                    "category_authority_started": args.activate_authority,
                    **report,
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
        return 0


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        return asyncio.run(_run(args))
    finally:
        asyncio.run(engine.dispose())


if __name__ == "__main__":
    raise SystemExit(main())
