"""The sibling-reapply path batches its revision fetch into one query.

Regression guard for the io-in-loop fix in
``SqlAlchemyCategoryProjectionWriter._reapply_active_sibling_projections``:
one ``select ... in_`` replaces the per-sibling ``db.get`` round-trips, and a
revision that vanishes between the sibling fetch and the batch read is
skipped, not a crash.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

from app.models.knowledge import KnowledgeCategory, KnowledgeCategoryRevision
from app.models.job import Job
from app.services.knowledge.category_markdown import parse_category_markdown
from app.services.knowledge.category_projections import SqlAlchemyCategoryProjectionWriter

_BENEFITS_MARKDOWN = (
    "---\n"
    'schema_version: "1.0"\n'
    "category: benefits\n"
    "---\n"
    "\n"
    "## benefits\n"
    "\n"
    "### record: health-check\n"
    'name: "Khám sức khỏe định kỳ"\n'
)
_MEALS_MARKDOWN = (
    "---\n"
    'schema_version: "1.0"\n'
    "category: meals\n"
    "---\n"
    "\n"
    "## meals\n"
    "\n"
    "### record: lunch\n"
    "provided: true\n"
)


class _FakeScalars:
    def __init__(self, rows: list) -> None:
        self._rows = rows

    def all(self) -> list:
        return list(self._rows)


class _RecordingSession:
    """Routes scalars() by selected entity and records every statement.

    ``get`` is instrumented because the point of the fix is that the sibling
    path must never issue per-sibling ``db.get`` round-trips again.
    """

    def __init__(self) -> None:
        self.statements: list = []
        self.selects: list[type] = []
        self.gets: list[tuple] = []
        self._rows_by_entity: dict[type, list] = {}

    def seed(self, entity: type, rows: list) -> None:
        self._rows_by_entity[entity] = rows

    async def scalars(self, statement, *args, **kwargs):
        entity = statement.column_descriptions[0]["entity"]
        self.statements.append(statement)
        self.selects.append(entity)
        return _FakeScalars(self._rows_by_entity[entity])

    async def get(self, entity, pk):
        self.gets.append((entity, pk))
        raise AssertionError(
            "sibling reapply must batch-fetch revisions, not db.get per sibling"
        )


def _revision_row(revision_id: uuid.UUID, payload: dict) -> SimpleNamespace:
    return SimpleNamespace(id=revision_id, normalized_payload=payload)


async def test_sibling_reapply_batch_fetches_revisions_and_skips_vanished() -> None:
    session = _RecordingSession()
    project_id = uuid.uuid4()
    benefits_payload = parse_category_markdown("benefits", _BENEFITS_MARKDOWN).model_dump(
        mode="json"
    )
    meals_payload = parse_category_markdown("meals", _MEALS_MARKDOWN).model_dump(mode="json")
    benefits_revision_id = uuid.uuid4()
    meals_revision_id = uuid.uuid4()
    vanished_revision_id = uuid.uuid4()
    session.seed(
        KnowledgeCategory,
        [
            SimpleNamespace(
                category_key="benefits",
                active_revision_id=benefits_revision_id,
            ),
            SimpleNamespace(
                category_key="meals",
                active_revision_id=meals_revision_id,
            ),
            SimpleNamespace(
                category_key="requirements",
                active_revision_id=vanished_revision_id,
            ),
        ],
    )
    session.seed(
        KnowledgeCategoryRevision,
        [
            _revision_row(benefits_revision_id, benefits_payload),
            _revision_row(meals_revision_id, meals_payload),
        ],
    )
    session.seed(Job, [])
    writer = SqlAlchemyCategoryProjectionWriter(session)
    applied: list[tuple[str, uuid.UUID]] = []

    async def _record(project_id, document, revision):
        applied.append((document.category, revision.id))

    writer._apply_projection_records = _record

    await writer._reapply_active_sibling_projections(project_id)

    assert session.gets == []
    # One categories select, one batched revision select — never one revision
    # query per sibling.
    assert session.selects == [KnowledgeCategory, KnowledgeCategoryRevision]
    revision_select = session.statements[1]
    compiled = revision_select.compile()
    in_params: set = set()
    for value in compiled.params.values():
        if isinstance(value, (list, tuple, set)):
            in_params.update(value)
        else:
            in_params.add(value)
    assert in_params == {
        benefits_revision_id,
        meals_revision_id,
        vanished_revision_id,
    }
    assert applied == [
        ("benefits", benefits_revision_id),
        ("meals", meals_revision_id),
    ]


async def test_sibling_reapply_with_no_siblings_issues_no_revision_query() -> None:
    session = _RecordingSession()
    session.seed(KnowledgeCategory, [])
    writer = SqlAlchemyCategoryProjectionWriter(session)
    await writer._reapply_active_sibling_projections(uuid.uuid4())
    assert session.gets == []
    assert session.selects == [KnowledgeCategory]
