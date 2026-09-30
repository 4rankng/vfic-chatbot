"""Agent-facing proof: a fixture brief ingestion lands its front-matter facts
in the project ``index_card`` that feeds the bot's active-project index.

Golden facts come from the Amtran fixture
``frontend/src/components/atomic-crm/projects/domain/fixtures/amtran-vsip-hai-phong.md``:
the project name and partner alias, the seven ``target_positions`` as roles,
the workplace city as location, and the brief's "Những điểm nổi bật" bullets as
highlights.

The chain drives the real backend ingest code at every step:

1. create — ``ProjectService.create`` with a ``ProjectCreate`` carrying the
   name/aliases plus ``discovery_card``, the create-time card that holds the
   brief facts (the ``ProjectDiscoveryCardPatch`` shape the panel saves).
2. the jobs category revision — the exact row the per-category replace API
   (``replace_project_category`` → ``KnowledgeCategoryService.stage_replacement``)
   writes: parsed document → ``normalized_payload`` → ``content_sha256`` →
   STAGED ``KnowledgeCategoryRevision``.
3. the real revision activation — ``KnowledgeCategoryService.activate_revision``,
   the entry the category worker runs (``run_category_revision_job`` →
   ``activate_revision``). It claims the STAGED revision, embeds it, and —
   because a fresh project is category-authoritative — applies the jobs
   projection itself, without anyone calling it by hand: ``summary``/``roles``/
   ``location`` are rebuilt, while the create card's
   highlights survive (``setdefault``), ``is_active`` keeps its seeded value
   (admin activation is the only switch), and ``quality_result["projection"]``
   reports "complete".

Step 2 writes the revision row directly instead of calling ``stage_replacement``
because the two gates are mutually exclusive today: ``ProjectCreate`` admits a
``discovery_card`` only on DIRECT_CONTEXT projects ("RAG discovery cards are
derived from active categories") while ``stage_replacement``'s
``require_rag_project`` admits RAG projects only. The create-time card is the
brief-facts carrier, so the revision write — not the create — is expressed at
row level, exactly as the tests around
``tests/integration/test_project_category_activation.py`` write theirs.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

from sqlalchemy import Update
from sqlalchemy.orm import InstrumentedAttribute
from sqlalchemy.sql.elements import BindParameter
from sqlalchemy.sql.functions import FunctionElement

from app.graph.context import active_projects_index
from app.models.company import Project
from app.models.knowledge import (
    KnowledgeBaseMode,
    KnowledgeCategory,
    KnowledgeCategoryRevision,
    KnowledgeCategoryRevisionStatus,
)
from app.schemas.projects import ProjectCreate
from app.schemas.knowledge_categories import KnowledgeCategoryKey
from app.services.knowledge.category_contracts import category_checksum
from app.services.knowledge.category_markdown import (
    build_source_markdown,
    parse_category_markdown,
)
from app.services.knowledge.category_projections import SqlAlchemyCategoryProjectionWriter
from app.services.knowledge.category_service import (
    MAX_CATEGORY_PROCESSING_ATTEMPTS,
    KnowledgeCategoryService,
)
from app.services.project import ProjectService
from app.services.project import service as project_service

# --- Golden facts, verbatim from the Amtran fixture. ---
FIXTURE_NAME = "Dự án Amtran Vsip Hải Phòng"
FIXTURE_SLUG = "du-an-amtran-vsip-hai-phong"
FIXTURE_ALIAS = "Công ty Amtran (AmTRAN Technology)"
FIXTURE_LOCATION = "Hải Phòng"
FIXTURE_TARGET_POSITIONS = [
    "Nhân viên lắp ráp linh kiện điện tử",
    "QA",
    "SMT",
    "UI",
    "Nhựa",
    "Tivi hành chính",
    "MV",
]
FIXTURE_HIGHLIGHTS = [
    "Nhận ứng viên có hình xăm, không phân biệt kích thước hay vị trí.",
    "Hoàn toàn không yêu cầu bằng cấp.",
    "Thu nhập phụ cấp và trợ cấp thêm từ 3.000.000 – 4.000.000 VNĐ/tháng.",
    "Được đào tạo chuyên môn bài bản từ đầu cho người chưa từng có kinh nghiệm.",
]
# Stable ASCII ids, the same rule the brief pipeline's ``toEntryId`` applies.
_FIXTURE_JOB_IDS = [
    "nhan-vien-lap-rap-linh-kien-dien-tu",
    "qa",
    "smt",
    "ui",
    "nhua",
    "tivi-hanh-chinh",
    "mv",
]

# The create-time card: exactly the ``ProjectDiscoveryCardPatch.discovery_card``
# shape (summary/location/roles/eligibility/highlights). The fixture states no
# "Tóm tắt" line, so the summary stays empty until the jobs projection writes it.
_BRIEF_CARD = {
    "summary": "",
    "location": FIXTURE_LOCATION,
    "roles": list(FIXTURE_TARGET_POSITIONS),
    "eligibility": [],
    "highlights": list(FIXTURE_HIGHLIGHTS),
}

# The summary formula the jobs projection applies (category_projections
# ``_replace_jobs``): first three unique roles, joined, at the location.
_PROJECTION_SUMMARY = (
    f"{FIXTURE_NAME} đang tuyển {', '.join(dict.fromkeys(FIXTURE_TARGET_POSITIONS[:3]))} "
    f"tại {FIXTURE_LOCATION}."
)


def _jobs_markdown() -> str:
    """The jobs Category Markdown v1 document the brief pipeline writes for
    these roles, rendered with the canonical renderer (front-matter, one
    ``## jobs`` section, one ``### record:`` block per role)."""
    payload = {
        "schema_version": "1.0",
        "category": "jobs",
        "jobs": [
            {
                "id": job_id,
                "title": title,
                "location": FIXTURE_LOCATION,
                "aliases": [],
                "keywords": [],
            }
            for job_id, title in zip(_FIXTURE_JOB_IDS, FIXTURE_TARGET_POSITIONS, strict=True)
        ],
    }
    return build_source_markdown(payload)


class _FakeScalars:
    def __init__(self, rows: list) -> None:
        self._rows = rows

    def __iter__(self):
        # Real ScalarResult iterates row-by-row (``list(scalars(...))``).
        return iter(self._rows)

    def all(self) -> list:
        return list(self._rows)

    def first(self):
        return self._rows[0] if self._rows else None


def _claimable_revision(row) -> bool:
    """The activation claim's WHERE over row state: attempt cap, claimable status."""
    return (row.attempt_count or 0) < MAX_CATEGORY_PROCESSING_ATTEMPTS and (
        row.status
        in (KnowledgeCategoryRevisionStatus.STAGED, KnowledgeCategoryRevisionStatus.FAILED)
        or (
            row.status is KnowledgeCategoryRevisionStatus.PROCESSING
            and row.lease_expires_at is not None
            and row.lease_expires_at < datetime.now(UTC)
        )
    )


class _UnitEmbedder:
    """Mechanics-only embedder (models no semantics): one identical vector per text."""

    async def batch(self, texts: list[str]) -> list[list[float]]:
        return [[0.0] * 8 for _ in texts]


class _FakeSession:
    """AsyncSession stand-in: entity-routed selects, collected adds.

    Mirrors ``test_category_projections_sibling_batch._RecordingSession`` with
    the persistence verbs the create flow, the activation chain and the
    projection writer use. The claim UPDATE gets what a real one supplies: its
    SET values land on every claimable row.
    """

    def __init__(self) -> None:
        self.added: list = []
        self._rows_by_entity: dict[type, list] = {}

    def seed(self, entity: type, rows: list) -> None:
        self._rows_by_entity[entity] = rows

    def _rows_of(self, entity: type) -> list:
        return [
            row
            for row in [*self._rows_by_entity.get(entity, []), *self.added]
            if isinstance(row, entity)
        ]

    async def scalars(self, statement, *args, **kwargs):
        description = statement.column_descriptions[0]
        rows = self._rows_of(description["entity"])
        expr = description["expr"]
        if isinstance(expr, InstrumentedAttribute):
            # Column select (e.g. select(Company.id)): return the column value,
            # not the entity row.
            return _FakeScalars([getattr(row, expr.key) for row in rows])
        return _FakeScalars(rows)

    async def scalar(self, statement, *args, **kwargs):
        """Single-row lookups (locked_project/locked_category) plus the one
        aggregate the activation chain runs: select(func.max(revision_no))."""
        description = statement.column_descriptions[0]
        if isinstance(description["expr"], FunctionElement):
            revisions = self._rows_of(KnowledgeCategoryRevision)
            return max((row.revision_no for row in revisions), default=None)
        rows = self._rows_of(description["entity"])
        return rows[0] if rows else None

    async def get(self, entity, pk):
        for row in self._rows_of(entity):
            if getattr(row, "id", None) == pk:
                return row
        return None

    async def execute(self, statement, params=None, **kwargs):
        if isinstance(statement, Update):
            values = dict(statement._values)
            claimed = 0
            for row in self._rows_of(KnowledgeCategoryRevision):
                if not _claimable_revision(row):
                    continue
                for column, value in values.items():
                    if column.key == "attempt_count":
                        row.attempt_count = (row.attempt_count or 0) + 1  # SQL-side increment
                    else:
                        # Update._values wraps literals in BindParameter; the
                        # database stores the bound value, so the row does too.
                        setattr(
                            row,
                            column.key,
                            value.value if isinstance(value, BindParameter) else value,
                        )
                claimed += 1
            return SimpleNamespace(rowcount=claimed)
        # text() statements: the category chunk INSERTs; no result rows needed.
        return SimpleNamespace(rowcount=0)

    def add(self, obj) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        """Give added rows what a real INSERT supplies: generated ids and the
        ``discovery_revision`` row default the projection increments."""
        for row in self.added:
            if getattr(row, "id", None) is None:
                row.id = uuid.uuid4()
            if hasattr(row, "discovery_revision") and row.discovery_revision is None:
                row.discovery_revision = 0

    async def commit(self) -> None:
        pass

    async def rollback(self) -> None:
        pass

    async def refresh(self, obj) -> None:
        pass


async def test_amtran_fixture_brief_ingestion_lands_front_matter_facts_in_index_card(
    monkeypatch,
) -> None:
    session = _FakeSession()
    monkeypatch.setattr(project_service, "record_audit", AsyncMock())
    monkeypatch.setattr(project_service, "bump_cache_version", AsyncMock())
    admin = SimpleNamespace(id=uuid.uuid4())

    # 1. Create as the create flow does: ProjectCreate carries the name, the
    #    alias and the create-time card (discovery_card) holding the brief facts.
    body = ProjectCreate(
        slug=FIXTURE_SLUG,
        name=FIXTURE_NAME,
        knowledge_mode=KnowledgeBaseMode.DIRECT_CONTEXT,
        aliases=[FIXTURE_ALIAS],
        discovery_card=dict(_BRIEF_CARD),
    )
    project = await ProjectService(session).create(body, admin)

    # 2. The jobs category revision, written exactly as the per-category
    #    replace API writes it.
    category = KnowledgeCategory(project_id=project.id, category_key="jobs")
    session.add(category)
    await session.flush()
    jobs_markdown = _jobs_markdown()
    document = parse_category_markdown("jobs", jobs_markdown)
    revision = KnowledgeCategoryRevision(
        category_id=category.id,
        revision_no=1,
        status=KnowledgeCategoryRevisionStatus.STAGED,
        source_filename="jobs.md",
        source_yaml=jobs_markdown,
        normalized_payload=document.model_dump(mode="json"),
        content_sha256=category_checksum(document),
        created_by=admin.id,
    )
    session.add(revision)
    await session.flush()

    # 3. Drive the real revision activation — the category worker's entry point
    #    (run_category_revision_job → activate_revision). It claims the STAGED
    #    revision, embeds it, and — because the fresh project is category
    #    authoritative — applies the jobs projection itself: summary/roles/
    #    location rebuilt; the card's highlights survive
    #    untouched. Nobody calls the projection by hand.
    monkeypatch.setattr(KnowledgeCategoryService, "_repair_caches", AsyncMock())
    await KnowledgeCategoryService(
        session, enforce_retrieval_selftest=False
    ).activate_revision(revision.id, _UnitEmbedder())

    card = project.index_card
    assert project.name == FIXTURE_NAME
    assert FIXTURE_ALIAS in project.aliases
    assert card["roles"] == FIXTURE_TARGET_POSITIONS
    assert FIXTURE_LOCATION in card["location"]
    assert card["highlights"] == FIXTURE_HIGHLIGHTS

    # The projection's own rebuilds prove the real activation projected over
    # the create card — and left the admin-owned is_active switch at its
    # seeded value (the fresh draft is created inactive).
    assert card["summary"] == project.summary == _PROJECTION_SUMMARY
    assert project.is_active is False
    assert project.discovery_revision == 1

    # Activation reports reality: nothing deferred, and the card is now
    # category-owned.
    assert revision.quality_result["projection"] == "complete"
    assert project.category_authority_started is True

    # The knowledge base is attached; the catalog's is_active switch stays
    # with the admin (ProjectEdit's toggle / Tạo dự án) — no projection flips
    # it, so the draft is not listed until the admin activates it.
    assert project.is_active is False and project.knowledge_base_id is not None

    # ... and the master index gives the agent a substantive line for it.
    prompt = await active_projects_index(
        SimpleNamespace(
            active_projects_with_card=AsyncMock(
                return_value=[
                    SimpleNamespace(
                        slug=project.slug,
                        name=project.name,
                        aliases=project.aliases,
                        summary=project.summary,
                        index_card=project.index_card,
                    )
                ]
            )
        )
    )
    assert f"{FIXTURE_SLUG} ({FIXTURE_NAME}): {_PROJECTION_SUMMARY}" in prompt
    assert f"vị trí: {', '.join(FIXTURE_TARGET_POSITIONS)}" in prompt
    assert f"địa điểm: {FIXTURE_LOCATION}" in prompt

    # Clearing the jobs scope removes only the scope: the derived rows go and
    # the card drops `roles`, while the preserved highlights and the
    # admin-owned is_active flag survive untouched.
    await SqlAlchemyCategoryProjectionWriter(session).clear(
        project.id, KnowledgeCategoryKey.JOBS
    )
    assert "roles" not in project.index_card
    assert project.index_card["highlights"] == FIXTURE_HIGHLIGHTS
    assert project.is_active is False


async def test_active_projects_index_advertises_the_amtran_brief_facts() -> None:
    """The directory line carries the name, the alias, the roles, the location
    and the highlights, rendered from the same card shape the chain derives.
    """

    class _Repo:
        async def active_projects_with_card(self):
            return [
                SimpleNamespace(
                    slug=FIXTURE_SLUG,
                    name=FIXTURE_NAME,
                    aliases=[FIXTURE_ALIAS],
                    summary=_PROJECTION_SUMMARY,
                    index_card={
                        "roles": FIXTURE_TARGET_POSITIONS,
                        "location": FIXTURE_LOCATION,
                        "highlights": FIXTURE_HIGHLIGHTS,
                    },
                )
            ]

    prompt = await active_projects_index(_Repo())

    assert f"{FIXTURE_SLUG} ({FIXTURE_NAME})" in prompt
    assert f"bí danh: {FIXTURE_ALIAS}" in prompt
    assert f"vị trí: {', '.join(FIXTURE_TARGET_POSITIONS)}" in prompt
    assert f"địa điểm: {FIXTURE_LOCATION}" in prompt
    assert f"nổi bật: {', '.join(FIXTURE_HIGHLIGHTS)}" in prompt


async def test_legacy_carded_project_defers_projection_until_cutover(monkeypatch) -> None:
    """A legacy project's pre-built card stays untouched at revision activation.

    Legacy cards are owned by their pre-built data until
    ``cutover_category_authority`` replaces them wholesale, so activation
    defers the projection (``quality_result`` says so) and the card, summary
    and authority flag are all preserved.
    """
    session = _FakeSession()
    monkeypatch.setattr(KnowledgeCategoryService, "_repair_caches", AsyncMock())
    legacy_card = {
        "summary": "Tóm tắt nhà máy cũ",
        "roles": ["Thợ máy"],
        "location": "Bắc Ninh",
        "highlights": ["Có xe đưa đón"],
    }
    project = Project(
        slug="legacy-nha-may",
        name="Nhà máy cũ",
        is_active=True,
        summary="Tóm tắt nhà máy cũ",
        index_card=dict(legacy_card),
        category_authority_started=False,
    )
    session.add(project)
    await session.flush()

    category = KnowledgeCategory(project_id=project.id, category_key="jobs")
    session.add(category)
    await session.flush()
    jobs_markdown = _jobs_markdown()
    document = parse_category_markdown("jobs", jobs_markdown)
    revision = KnowledgeCategoryRevision(
        category_id=category.id,
        revision_no=1,
        status=KnowledgeCategoryRevisionStatus.STAGED,
        source_filename="jobs.md",
        source_yaml=jobs_markdown,
        normalized_payload=document.model_dump(mode="json"),
        content_sha256=category_checksum(document),
    )
    session.add(revision)
    await session.flush()

    await KnowledgeCategoryService(
        session, enforce_retrieval_selftest=False
    ).activate_revision(revision.id, _UnitEmbedder())

    # Activation ran to completion but deferred the projection.
    assert revision.status is KnowledgeCategoryRevisionStatus.ACTIVE
    assert revision.quality_result["projection"] == "deferred_until_cutover"

    # The legacy card is fully preserved: nothing projected over it.
    assert project.index_card == legacy_card
    assert project.summary == "Tóm tắt nhà máy cũ"
    assert project.discovery_revision == 0
    assert project.category_authority_started is False
