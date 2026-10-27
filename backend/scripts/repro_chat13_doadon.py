"""Repro for CHAT-13: "cho hỏi dự án Lear có đưa đón không" must reach the LLM
with the KB route — all four fixed stops plus the ≥5-people Ghi chú.

Seeds the production-shaped fixture (import-placeholder company name, time-less
KB stops, notes on the route) into the DEV database, then drives the same
retrieval + formatting path the agent's search_bus_timetable tool uses.

Usage (from backend/):
    uv run python scripts/repro_chat13_doadon.py [--seed]

``--seed`` inserts the fixture project (slug prefixed ``chat13-repro-``) before
probing; without it the script only probes an existing fixture. Exit code 0 =
the answer context carries every expected point; 1 = the bug is live.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import sys
import uuid
from typing import cast

from sqlalchemy import delete, select

from app.core.config import get_settings
from app.core.db import get_session_factory
from app.graph.ports import GraphRetrievalPort
from app.graph.tools.catalog import search_bus_timetable as format_timetable
from app.models.bus import BusRoute, BusStop
from app.models.company import Company, Project
from app.models.knowledge import (
    KnowledgeCategory,
    KnowledgeCategoryRevision,
    KnowledgeCategoryRevisionStatus,
)
from app.schemas.knowledge_categories import KnowledgeCategoryKey
from app.services.retrieval.timetable_repository import TimetableRepository

FIXTURE_SLUG_PREFIX = "chat13-repro-"
COMPANY_NAME = "Dự án mới"
PROJECT_NAME = "Lear Cát Hải"
ROUTE_NAME = "Xe đưa đón"
STOPS = (
    "Đồ sơn",
    "Thư viện thành phố",
    "Nhà thi đấu kiến thụy",
    "Bến xe thượng lý",
)
GHI_CHU = (
    "Các địa điểm khác như an lão, an dương, tiên lãng phải gom đủ 5 người trở lên "
    "mới điều xe đón."
)
QUESTION = "cho hỏi dự án Lear có đưa đón không"


async def seed_fixture() -> str:
    async with get_session_factory()() as db:
        stale = (
            await db.scalars(
                select(Project.id).where(Project.slug.like(f"{FIXTURE_SLUG_PREFIX}%"))
            )
        ).all()
        for project_id in stale:
            await db.execute(delete(Project).where(Project.id == project_id))
        await db.commit()
        project = Project(
            name=PROJECT_NAME,
            slug=f"{FIXTURE_SLUG_PREFIX}{uuid.uuid4().hex[:8]}",
            category_authority_started=True,
            index_card={},
        )
        db.add(project)
        await db.flush()
        company = Company(project_id=project.id, name=COMPANY_NAME)
        db.add(company)
        await db.flush()
        category = KnowledgeCategory(
            project_id=project.id,
            category_key=KnowledgeCategoryKey.TRANSPORTATION.value,
        )
        db.add(category)
        await db.flush()
        revision = KnowledgeCategoryRevision(
            category_id=category.id,
            revision_no=1,
            status=KnowledgeCategoryRevisionStatus.ACTIVE,
            source_filename="transportation.md",
            source_markdown="## transportation",
            normalized_payload={},
            content_sha256=hashlib.sha256(uuid.uuid4().bytes).hexdigest(),
        )
        db.add(revision)
        await db.flush()
        route = BusRoute(
            project_id=project.id,
            company_id=company.id,
            source_category_revision_id=revision.id,
            route_name=ROUTE_NAME,
            route_no=revision.id.hex,
            route_variant=f"auto-transportation-{uuid.uuid4().hex[:24]}",
            shift="day",
            direction="outbound",
            mode="company_bus",
            source_page="category_markdown",
            notes=GHI_CHU,
            route_group_key=revision.id.hex,
        )
        db.add(route)
        await db.flush()
        for index, stop in enumerate(STOPS, start=1):
            db.add(BusStop(route_id=route.id, stop_order=index, stop_name=stop))
        await db.commit()
        return project.slug


async def probe() -> tuple[bool, str]:
    async with get_session_factory()() as db:
        repo = TimetableRepository(db)
        rows = await repo.search_bus_timetable(PROJECT_NAME, QUESTION, 50)
        if not rows:
            return False, "repository returned no rows for the Lear question"
        # The tool only touches the timetable method on the port here.
        context = await format_timetable(
            retrieval=cast(GraphRetrievalPort, repo), company=PROJECT_NAME, question=QUESTION
        )
    ok = True
    problems: list[str] = []
    for stop in STOPS:
        if stop not in context:
            ok = False
            problems.append(f"missing stop: {stop}")
    if "Ghi chú:" not in context or "5 người" not in context:
        ok = False
        problems.append("missing the ≥5-people Ghi chú")
    return ok, "\n".join(problems) if problems else context


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", action="store_true", help="insert the fixture project first")
    args = parser.parse_args()
    if get_settings().app_env == "production" and args.seed:
        print("refusing to seed the CHAT-13 fixture into a production database")
        return 2
    if args.seed:
        slug = await seed_fixture()
        print(f"seeded fixture project: {slug}")
    ok, detail = await probe()
    print("--- tool context returned to the LLM ---")
    print(detail if ok else detail)
    if ok:
        print("PASS: the Lear answer context carries all 4 stops + the ≥5-people Ghi chú")
        return 0
    print("FAIL: the bug is live — the answer context is missing required points")
    return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
