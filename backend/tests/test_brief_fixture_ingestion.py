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
3. the jobs projection — ``SqlAlchemyCategoryProjectionWriter.apply_for_revision``,
   the same call revision activation makes. It rebuilds ``summary``/``roles``/
   ``location`` and sets ``is_active``, while the create card's highlights
   survive (``setdefault``).

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
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.graph.context import active_projects_index
from app.models.knowledge import (
    KnowledgeBaseMode,
    KnowledgeCategory,
    KnowledgeCategoryRevision,
    KnowledgeCategoryRevisionStatus,
)
from app.schemas.projects import ProjectCreate
from app.services.knowledge.category_contracts import category_checksum, parse_category_yaml
from app.services.knowledge.category_projections import SqlAlchemyCategoryProjectionWriter
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


def _jobs_yaml() -> str:
    """The jobs category document the brief pipeline writes for these roles
    (frontend ``buildJobsYaml(roles, location)`` shape)."""
    lines = ['schema_version: "1.0"', "category: jobs", "jobs:"]
    for job_id, title in zip(_FIXTURE_JOB_IDS, FIXTURE_TARGET_POSITIONS, strict=True):
        lines += [
            f"  - id: {job_id}",
            f'    title: "{title}"',
            f'    location: "{FIXTURE_LOCATION}"',
            "    aliases: []",
            "    keywords: []",
        ]
    return "\n".join(lines) + "\n"


class _FakeScalars:
    def __init__(self, rows: list) -> None:
        self._rows = rows

    def all(self) -> list:
        return list(self._rows)

    def first(self):
        return self._rows[0] if self._rows else None


class _FakeSession:
    """AsyncSession stand-in: entity-routed selects, collected adds.

    Mirrors ``test_category_projections_sibling_batch._RecordingSession`` with
    the persistence verbs the create flow and the projection writer use.
    """

    def __init__(self) -> None:
        self.added: list = []
        self._rows_by_entity: dict[type, list] = {}

    def seed(self, entity: type, rows: list) -> None:
        self._rows_by_entity[entity] = rows

    async def scalars(self, statement, *args, **kwargs):
        entity = statement.column_descriptions[0]["entity"]
        return _FakeScalars(self._rows_by_entity.get(entity, []))

    async def get(self, entity, pk):
        for row in [*self._rows_by_entity.get(entity, []), *self.added]:
            if isinstance(row, entity) and getattr(row, "id", None) == pk:
                return row
        return None

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
    jobs_yaml = _jobs_yaml()
    document = parse_category_yaml("jobs", jobs_yaml)
    revision = KnowledgeCategoryRevision(
        category_id=category.id,
        revision_no=1,
        status=KnowledgeCategoryRevisionStatus.STAGED,
        source_filename="jobs.yaml",
        source_yaml=jobs_yaml,
        normalized_payload=document.model_dump(mode="json"),
        content_sha256=category_checksum(document),
        created_by=admin.id,
    )
    session.add(revision)
    await session.flush()

    # 3. Run the jobs projection — the same call activation makes. It rebuilds
    #    summary/roles/location and sets is_active; the card's highlights
    #    survive untouched.
    await SqlAlchemyCategoryProjectionWriter(session).apply_for_revision(
        project.id, revision, document
    )

    card = project.index_card
    assert project.name == FIXTURE_NAME
    assert FIXTURE_ALIAS in project.aliases
    assert card["roles"] == FIXTURE_TARGET_POSITIONS
    assert FIXTURE_LOCATION in card["location"]
    assert card["highlights"] == FIXTURE_HIGHLIGHTS

    # The projection's own rebuilds prove step 3 ran over the create card.
    assert card["summary"] == project.summary == _PROJECTION_SUMMARY
    assert project.is_active is True
    assert project.discovery_revision == 1


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
