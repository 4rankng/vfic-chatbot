from __future__ import annotations

import uuid

import pytest
from sqlalchemy.dialects import postgresql

from scripts import plan_legacy_document_release_migration as migration_script
from app.services.knowledge.legacy_document_migration import (
    LegacyDocumentMigrationCandidate,
    LegacyDocumentMigrationPlanError,
    build_legacy_document_migration_plan,
)
from app.services.knowledge.text_ingestion import kb_text_stats


def _candidate(
    *,
    document_id: uuid.UUID | None = None,
    project_id: uuid.UUID | None = None,
    raw_text: str | None = "Thông tin tuyển dụng có nguồn.",
) -> LegacyDocumentMigrationCandidate:
    return LegacyDocumentMigrationCandidate(
        document_id=document_id or uuid.uuid4(),
        project_id=project_id,
        raw_text=raw_text,
    )


def test_plan_groups_project_scoped_documents_and_reports_source_checksums() -> None:
    project_id = uuid.uuid4()
    active_version_id = uuid.uuid4()
    first = _candidate(project_id=project_id, raw_text="Ca ngày")
    second = _candidate(project_id=project_id, raw_text="Xe đưa đón")

    plan = build_legacy_document_migration_plan(
        [second, first],
        active_kb_versions={project_id: active_version_id},
    )

    assert len(plan) == 1
    assert plan[0].project_id == project_id
    assert plan[0].active_kb_version_id == active_version_id
    assert set(plan[0].source_documents) == {
        (first.document_id, kb_text_stats("Ca ngày").content_sha256),
        (second.document_id, kb_text_stats("Xe đưa đón").content_sha256),
    }


def test_plan_uses_the_same_normalized_checksum_as_release_uploads() -> None:
    project_id = uuid.uuid4()
    candidate = _candidate(project_id=project_id, raw_text="\ufeffCa ngày\r\n")

    plan = build_legacy_document_migration_plan(
        [candidate],
        active_kb_versions={project_id: uuid.uuid4()},
    )

    assert plan[0].source_documents[0][1] == kb_text_stats("Ca ngày\n").content_sha256


def test_dry_run_plan_is_deterministic_for_repeated_reads() -> None:
    project_id = uuid.uuid4()
    active_version_id = uuid.uuid4()
    candidates = [
        _candidate(document_id=uuid.uuid4(), project_id=project_id, raw_text="Lương"),
        _candidate(document_id=uuid.uuid4(), project_id=project_id, raw_text="Ca làm việc"),
    ]

    first = build_legacy_document_migration_plan(
        candidates,
        active_kb_versions={project_id: active_version_id},
    )
    second = build_legacy_document_migration_plan(
        reversed(candidates),
        active_kb_versions={project_id: active_version_id},
    )

    assert first == second
    assert migration_script._serialize_plan(first) == migration_script._serialize_plan(second)


@pytest.mark.parametrize(
    "candidate, active_kb_versions, message",
    [
        (_candidate(project_id=None), {}, "has no project"),
        (_candidate(project_id=uuid.uuid4(), raw_text=" "), {}, "has no source text"),
        (_candidate(project_id=uuid.uuid4(), raw_text="\ufeff\x00"), {}, "has no source text"),
        (_candidate(project_id=uuid.uuid4()), {}, "has no active KB version"),
    ],
)
def test_plan_refuses_ambiguous_or_unmigratable_documents(
    candidate: LegacyDocumentMigrationCandidate,
    active_kb_versions: dict[uuid.UUID, uuid.UUID | None],
    message: str,
) -> None:
    with pytest.raises(LegacyDocumentMigrationPlanError, match=message):
        build_legacy_document_migration_plan(
            [candidate],
            active_kb_versions=active_kb_versions,
        )


def test_dry_run_loader_only_executes_reads() -> None:
    project_id = uuid.uuid4()
    active_version_id = uuid.uuid4()
    document_id = uuid.uuid4()

    class _Result:
        def __init__(self, rows: list[object]) -> None:
            self._rows = rows

        def all(self) -> list[object]:
            return self._rows

    class _ReadOnlySession:
        def __init__(self) -> None:
            self.executions = 0

        def execute(self, _statement: object) -> _Result:
            self.executions += 1
            if self.executions == 1:
                return _Result(
                    [
                        type(
                            "DocumentRow",
                            (),
                            {
                                "id": document_id,
                                "project_id": project_id,
                                "raw_text": "Tuyển dụng có nguồn.",
                            },
                        )()
                    ]
                )
            return _Result(
                [
                    type(
                        "ProjectRow",
                        (),
                        {"id": project_id, "active_kb_version_id": active_version_id},
                    )()
                ]
            )

    session = _ReadOnlySession()

    plan = migration_script._load_plan(session)

    assert session.executions == 2
    assert plan[0].source_documents[0][0] == document_id


def test_dry_run_loader_refuses_a_project_without_a_verified_active_release() -> None:
    project_id = uuid.uuid4()

    class _Result:
        def __init__(self, rows: list[object]) -> None:
            self._rows = rows

        def all(self) -> list[object]:
            return self._rows

    class _ReadOnlySession:
        def __init__(self) -> None:
            self.executions = 0

        def execute(self, _statement: object) -> _Result:
            self.executions += 1
            if self.executions == 1:
                return _Result(
                    [
                        type(
                            "DocumentRow",
                            (),
                            {
                                "id": uuid.uuid4(),
                                "project_id": project_id,
                                "raw_text": "Tuyển dụng có nguồn.",
                            },
                        )()
                    ]
                )
            return _Result([])

    with pytest.raises(LegacyDocumentMigrationPlanError, match="has no active KB version"):
        migration_script._load_plan(_ReadOnlySession())


def test_dry_run_queries_select_only_eligible_documents_and_verified_active_releases() -> None:
    document_sql = str(
        migration_script._legacy_document_query().compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )
    project_sql = str(
        migration_script._verified_active_version_query({uuid.uuid4()}).compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )

    assert "knowledge_documents.status = 'PUBLISHED'" in document_sql
    assert "kb_text_files.id IS NULL" in document_sql
    assert "kb_versions.project_id = projects.id" in project_sql
    assert "kb_versions.status = 'ACTIVE'" in project_sql


def test_dry_run_flag_is_required() -> None:
    with pytest.raises(SystemExit):
        migration_script._parse_args([])


def test_apply_flag_is_rejected() -> None:
    with pytest.raises(SystemExit):
        migration_script._parse_args(["--dry-run", "--apply"])
