"""Focused unit tests for the project/knowledge DDD boundaries."""

from __future__ import annotations

import uuid

import importlib
from collections.abc import Callable

import pytest

from app.project_knowledge.application.jobs import (
    DirectContextIndexRequest,
    EnqueueReceiptUnknown,
    ProjectKnowledgeDirectContextJobs,
    ProjectKnowledgeJobKind,
    ProjectKnowledgeJobRequest,
    ProjectKnowledgeJobs,
)
from app.project_knowledge.domain.category import (
    category_payload_checksum,
    category_record_limit_exceeded,
    category_replacement_is_empty,
    unknown_job_references,
)
from app.project_knowledge.domain.ingestion import (
    IllegalIngestionTransition,
    IngestionState,
    ensure_ingestion_transition,
)
from app.project_knowledge.domain.project import (
    ProjectActivationFacts,
    project_activation_error,
)
from app.project_knowledge.infrastructure.cache import RedisProjectKnowledgeCacheRepair
from app.composition.project_knowledge_jobs import (
    WorkerDirectContextIndexAdapter,
)
from app.composition.project_knowledge_jobs import RqProjectKnowledgeJobAdapter
from app.workers.utils import EnqueueStatusUnknown

# Real UUIDs: the job contracts type aggregate ids as uuid.UUID (stdlib),
# matching what production callers hand over.
_KB_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
_PROJECT_ID = uuid.UUID("00000000-0000-0000-0000-000000000002")
_DOC_ID = uuid.UUID("00000000-0000-0000-0000-000000000003")
_AGG_ID = uuid.UUID("00000000-0000-0000-0000-000000000004")


def test_pure_ingestion_lifecycle_accepts_the_full_happy_path() -> None:
    path = [
        IngestionState.RECEIVED,
        IngestionState.STORED,
        IngestionState.PARSED,
        IngestionState.NORMALIZED,
        IngestionState.CLASSIFIED,
        IngestionState.EXTRACTED,
        IngestionState.VALIDATED,
        IngestionState.APPROVED,
        IngestionState.PUBLISHED,
        IngestionState.INDEXED,
    ]

    assert all(
        ensure_ingestion_transition(current, target)
        for current, target in zip(path, path[1:])
    )


def test_pure_ingestion_lifecycle_rejects_an_illegal_transition_with_reason() -> None:
    with pytest.raises(
        IllegalIngestionTransition,
        match=r"illegal transition VALIDATED → STORED \(stale retry\)",
    ):
        ensure_ingestion_transition(
            IngestionState.VALIDATED,
            IngestionState.STORED,
            reason="stale retry",
        )


def test_pure_ingestion_lifecycle_treats_same_state_as_idempotent() -> None:
    assert ensure_ingestion_transition("PARSED", IngestionState.PARSED) is False


def test_category_checksum_is_stable_across_nested_mapping_key_order() -> None:
    first = {
        "category": "jobs",
        "metadata": {"locale": "vi", "schema_version": "1.0"},
        "jobs": [{"id": "operator", "title": "Công nhân"}],
    }
    reordered = {
        "jobs": [{"title": "Công nhân", "id": "operator"}],
        "metadata": {"schema_version": "1.0", "locale": "vi"},
        "category": "jobs",
    }

    assert category_payload_checksum(first) == category_payload_checksum(reordered)


@pytest.mark.parametrize(
    ("record_count", "maximum", "expected"),
    [(1_000, 1_000, False), (1_001, 1_000, True)],
)
def test_category_record_limit_uses_an_exclusive_upper_boundary(
    record_count: int,
    maximum: int,
    expected: bool,
) -> None:
    assert category_record_limit_exceeded(record_count, maximum) is expected


@pytest.mark.parametrize(("record_count", "expected"), [(0, True), (1, False)])
def test_category_empty_replacement_rule(record_count: int, expected: bool) -> None:
    assert category_replacement_is_empty(record_count) is expected


def test_unknown_job_references_collect_only_unknown_unique_ids() -> None:
    references = [
        ["known-job", "missing-a"],
        [],
        ["missing-b", "missing-a", "known-job"],
    ]

    assert unknown_job_references(references, {"known-job"}) == {
        "missing-a",
        "missing-b",
    }


@pytest.mark.parametrize(
    ("facts", "expected"),
    [
        (ProjectActivationFacts(None), "Project has no owned knowledge base"),
        (
            ProjectActivationFacts("DIRECT_CONTEXT"),
            "Single-page Project needs a discovery card before activation",
        ),
        (
            ProjectActivationFacts("DIRECT_CONTEXT", has_discovery_card=True),
            "Single-page Project needs its page before activation",
        ),
        (
            ProjectActivationFacts(
                "DIRECT_CONTEXT",
                has_discovery_card=True,
                has_direct_file=True,
            ),
            None,
        ),
        (ProjectActivationFacts("RAG"), None),
    ],
)
def test_project_activation_policy_is_framework_free_and_preserves_errors(
    facts: ProjectActivationFacts,
    expected: str | None,
) -> None:
    assert project_activation_error(facts) == expected


async def test_cache_repair_preserves_knowledge_then_jobs_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    async def bump_knowledge() -> None:
        calls.append("knowledge")

    async def bump_namespace(namespace: str) -> None:
        calls.append(namespace)

    monkeypatch.setattr(
        "app.project_knowledge.infrastructure.cache.bump_kb_caches",
        bump_knowledge,
    )
    monkeypatch.setattr(
        "app.project_knowledge.infrastructure.cache.bump_cache_version",
        bump_namespace,
    )

    await RedisProjectKnowledgeCacheRepair().repair_knowledge_and_jobs()

    assert calls == ["knowledge", "jobs"]


class _RecordingJobPort:
    def __init__(self, receipt: str | None) -> None:
        self.receipt = receipt
        self.requests: list[ProjectKnowledgeJobRequest] = []

    def enqueue(self, request: ProjectKnowledgeJobRequest) -> str | None:
        self.requests.append(request)
        return self.receipt


class _RecordingDirectContextPort:
    def __init__(self) -> None:
        self.requests: list[DirectContextIndexRequest] = []

    def enqueue(self, request: DirectContextIndexRequest) -> None:
        self.requests.append(request)


def test_project_knowledge_jobs_document_ingest_is_fire_and_forget() -> None:
    port = _RecordingJobPort("ignored-worker-receipt")
    jobs = ProjectKnowledgeJobs(port)

    assert jobs.ingest_document(_DOC_ID) is None
    assert port.requests == [
        ProjectKnowledgeJobRequest(ProjectKnowledgeJobKind.DOCUMENT_INGEST, _DOC_ID)
    ]


def test_project_knowledge_direct_context_jobs_preserve_enqueue_arguments() -> None:
    port = _RecordingDirectContextPort()
    jobs = ProjectKnowledgeDirectContextJobs(port)

    assert jobs.index_direct_context(_KB_ID, _PROJECT_ID, "raw text") is None
    assert port.requests == [
        DirectContextIndexRequest(
            knowledge_base_id=_KB_ID,
            project_id=_PROJECT_ID,
            text_blob="raw text",
        )
    ]


@pytest.mark.parametrize(
    ("method_name", "kind"),
    [
        ("ingest_version", ProjectKnowledgeJobKind.VERSION_INGEST),
        ("process_category_revision", ProjectKnowledgeJobKind.CATEGORY_REVISION),
    ],
)
def test_project_knowledge_jobs_required_receipt_operations_return_the_receipt(
    method_name: str,
    kind: ProjectKnowledgeJobKind,
) -> None:
    port = _RecordingJobPort("rq-receipt")
    jobs = ProjectKnowledgeJobs(port)

    assert getattr(jobs, method_name)(_AGG_ID) == "rq-receipt"
    assert port.requests == [ProjectKnowledgeJobRequest(kind, _AGG_ID)]


@pytest.mark.parametrize(
    ("method_name", "message"),
    [
        ("ingest_version", "knowledge version enqueue failed"),
        ("process_category_revision", "category revision enqueue failed"),
    ],
)
def test_project_knowledge_jobs_required_receipt_operations_reject_no_receipt(
    method_name: str,
    message: str,
) -> None:
    jobs = ProjectKnowledgeJobs(_RecordingJobPort(None))

    with pytest.raises(RuntimeError, match=message):
        getattr(jobs, method_name)(_AGG_ID)


@pytest.mark.parametrize(
    ("method_name", "kind"),
    [
        ("sync_external_source", ProjectKnowledgeJobKind.EXTERNAL_SOURCE_SYNC),
        ("sync_single_page_source", ProjectKnowledgeJobKind.SINGLE_PAGE_SOURCE_SYNC),
    ],
)
@pytest.mark.parametrize("receipt", [None, "source-sync-receipt"])
def test_project_knowledge_jobs_source_sync_preserves_optional_receipt_and_job_id(
    method_name: str,
    kind: ProjectKnowledgeJobKind,
    receipt: str | None,
) -> None:
    port = _RecordingJobPort(receipt)
    jobs = ProjectKnowledgeJobs(port)

    assert getattr(jobs, method_name)(_AGG_ID, job_id="requested-id") == receipt
    assert port.requests == [
        ProjectKnowledgeJobRequest(kind, _AGG_ID, requested_job_id="requested-id")
    ]


_WORKER_FACADES = {
    ProjectKnowledgeJobKind.DOCUMENT_INGEST: (
        "app.workers.ingest_worker",
        "enqueue_ingest",
    ),
    ProjectKnowledgeJobKind.VERSION_INGEST: (
        "app.workers.ingest_worker",
        "enqueue_ingest_version",
    ),
    ProjectKnowledgeJobKind.CATEGORY_REVISION: (
        "app.workers.category_worker",
        "enqueue_category_revision",
    ),
    ProjectKnowledgeJobKind.EXTERNAL_SOURCE_SYNC: (
        "app.workers.external_source_sync_worker",
        "enqueue_one_shot",
    ),
    ProjectKnowledgeJobKind.SINGLE_PAGE_SOURCE_SYNC: (
        "app.workers.single_page_external_source_sync_worker",
        "enqueue_one_shot",
    ),
}


def _patch_worker_facades(
    monkeypatch: pytest.MonkeyPatch,
    replacement_factory: Callable[[ProjectKnowledgeJobKind], Callable[..., str]],
) -> None:
    for kind, (module_name, function_name) in _WORKER_FACADES.items():
        module = importlib.import_module(module_name)
        monkeypatch.setattr(module, function_name, replacement_factory(kind))


@pytest.mark.parametrize("kind", list(ProjectKnowledgeJobKind))
def test_rq_adapter_delegates_to_the_exact_existing_worker_facade(
    monkeypatch: pytest.MonkeyPatch,
    kind: ProjectKnowledgeJobKind,
) -> None:
    calls: list[tuple[ProjectKnowledgeJobKind, tuple[object, ...], dict[str, object]]] = []

    def replacement_factory(
        facade_kind: ProjectKnowledgeJobKind,
    ) -> Callable[..., str]:
        def replacement(*args: object, **kwargs: object) -> str:
            calls.append((facade_kind, args, kwargs))
            return "worker-receipt"

        return replacement

    _patch_worker_facades(monkeypatch, replacement_factory)
    requested_job_id = "caller-job-id"
    request = ProjectKnowledgeJobRequest(
        kind,
        _AGG_ID,
        requested_job_id=requested_job_id,
    )

    receipt = RqProjectKnowledgeJobAdapter().enqueue(request)

    expected_kwargs = (
        {"job_id": requested_job_id}
        if kind
        in {
            ProjectKnowledgeJobKind.EXTERNAL_SOURCE_SYNC,
            ProjectKnowledgeJobKind.SINGLE_PAGE_SOURCE_SYNC,
        }
        else {}
    )
    assert calls == [(kind, (_AGG_ID,), expected_kwargs)]
    expected_receipt = None if kind is ProjectKnowledgeJobKind.DOCUMENT_INGEST else "worker-receipt"
    assert receipt == expected_receipt


@pytest.mark.parametrize("kind", list(ProjectKnowledgeJobKind))
def test_rq_adapter_maps_unknown_worker_receipt_to_application_error(
    monkeypatch: pytest.MonkeyPatch,
    kind: ProjectKnowledgeJobKind,
) -> None:
    def replacement_factory(
        _facade_kind: ProjectKnowledgeJobKind,
    ) -> Callable[..., str]:
        def replacement(*_args: object, **_kwargs: object) -> str:
            raise EnqueueStatusUnknown("ambiguous-job-id")

        return replacement

    _patch_worker_facades(monkeypatch, replacement_factory)

    with pytest.raises(EnqueueReceiptUnknown) as exc_info:
        RqProjectKnowledgeJobAdapter().enqueue(
            ProjectKnowledgeJobRequest(kind, _AGG_ID, "ambiguous-job-id")
        )

    assert isinstance(exc_info.value.__cause__, EnqueueStatusUnknown)


def test_direct_context_index_adapter_delegates_to_worker_facade(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[object, object, str]] = []
    monkeypatch.setattr(
        "app.workers.direct_context_worker.enqueue_direct_context_index",
        lambda knowledge_base_id, project_id, text_blob: calls.append(
            (knowledge_base_id, project_id, text_blob)
        ),
    )

    WorkerDirectContextIndexAdapter().enqueue(
        DirectContextIndexRequest(
            knowledge_base_id=_KB_ID,
            project_id=_PROJECT_ID,
            text_blob="raw text",
        )
    )

    assert calls == [(_KB_ID, _PROJECT_ID, "raw text")]
