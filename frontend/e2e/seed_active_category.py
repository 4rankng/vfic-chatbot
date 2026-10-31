"""Seed one ACTIVE `jobs` category into the disposable e2e database.

The Playwright harness owns the backend stack but ships no provider-backed
review worker, so a revision staged through the API stays STAGED and the
knowledge sheet would never render record cards. This script stages the
markdown through the app's own service, activates it with a stub embedder
(the backend integration tests' shape), and flips the project's category
authority so the panel renders the RAG catalog instead of the migration
region.

Run with the backend venv interpreter by
e2e/project-knowledge-sheet.spec.ts. Requires VFIC_E2E_DATABASE_URL (set by
playwright.config.ts) and the harness reset seed (admin@example.org plus the
`e2e-project` RAG project).
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2] / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy import select, update  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from app.models.company import Project  # noqa: E402
from app.models.knowledge import (  # noqa: E402
    KnowledgeCategory,
    KnowledgeCategoryRevision,
    KnowledgeCategoryRevisionStatus,
)
from app.models.user import User  # noqa: E402
from app.schemas.knowledge_categories import KnowledgeCategoryKey  # noqa: E402
from app.services.knowledge.category_contracts import category_checksum  # noqa: E402
from app.services.knowledge.category_markdown import parse_category_markdown  # noqa: E402
from app.services.knowledge.category_service import KnowledgeCategoryService  # noqa: E402

# Two records, one list field each — the shape the knowledge sheet's record
# cards exist for. Content mirrors the production jobs vocabulary (VFIC
# VinFast suppliers) so the screenshot evidence is comparable.
JOBS_SOURCE = """---
schema_version: "1.0"
category: jobs
---

## jobs

### record: bo-phan-lap-rap
title: "Công nhân lắp ráp"
aliases:
- "Lắp ráp"
location: "Supplier Park Factory, Đình Vũ - Cát Hải, TP. Hải Phòng"
summary: "Lắp ráp theo bản vẽ, kiểm tra chi tiết, vận hành máy. Không yêu cầu kinh nghiệm, 18–45 tuổi."
keywords:
- "Chính thức"
- "Sản xuất ghế ô tô xe điện"

### record: bo-phan-may
title: "Công nhân may"
aliases:
- "May"
location: "Supplier Park Factory, Đình Vũ - Cát Hải, TP. Hải Phòng"
summary: "May chi tiết ghế ngồi ô tô theo định mức. Đào tạo tại chỗ, làm việc theo ca."
keywords:
- "Chính thức"
- "VinFast"
"""


class _StubEmbedder:
    """Same contract as the integration tests' embedder (3072-dim vectors)."""

    async def batch(self, texts: list[str]) -> list[list[float]]:
        return [[0.0] * 3072 for _ in texts]


async def main() -> None:
    database_url = os.environ["VFIC_E2E_DATABASE_URL"]
    engine = create_async_engine(database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with session_factory() as session:
            project = await session.scalar(
                select(Project).where(Project.slug == "e2e-project")
            )
            if project is None:
                raise RuntimeError("harness seed missing: project e2e-project")
            actor = await session.scalar(
                select(User).where(User.email == "admin@example.org")
            )
            if actor is None:
                raise RuntimeError("harness seed missing: admin user")

            # The prior run's seed would collide on (project, jobs): the reset
            # fixture truncates per test, but a manual re-run against a live
            # database must stay idempotent.
            existing = await session.scalar(
                select(KnowledgeCategory).where(
                    KnowledgeCategory.project_id == project.id,
                    KnowledgeCategory.category_key == "jobs",
                )
            )
            if existing is not None:
                await session.delete(existing)
                await session.commit()

            service = KnowledgeCategoryService(
                session, enforce_retrieval_selftest=False
            )
            revision, _token = await service.stage_replacement(
                project_id=project.id,
                category_key=KnowledgeCategoryKey.JOBS,
                filename="jobs.md",
                source_markdown=JOBS_SOURCE,
                actor=actor,
                schedule=False,
            )
            await service.activate_revision(revision.id, _StubEmbedder())
            await session.execute(
                update(Project)
                .where(Project.id == project.id)
                .values(category_authority_started=True)
            )
            await session.commit()
    finally:
        await engine.dispose()
    print("seeded: e2e-project/jobs ACTIVE")


if __name__ == "__main__":
    asyncio.run(main())
