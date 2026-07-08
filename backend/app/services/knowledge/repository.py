"""Data-access layer for the knowledge training pipeline — compatibility barrel.

The four per-table repositories now live in their own modules:

- :class:`KnowledgeChunkRepo` → :mod:`.chunk_repository`
- :class:`KnowledgeDocumentRepo` (+ the sync ingest-failure markers) → :mod:`.document_repository`
- :class:`JobFeatureValueRepo` → :mod:`.job_feature_repository`
- :class:`ProjectIndexRepo` (+ :func:`rebuild_bus_timetable`) → :mod:`.project_index_repository`

They are re-exported here so existing ``from app.services.knowledge.repository import ...``
callers keep working unchanged. New code should import from the specific module.

These modules encapsulate raw SQL the ORM cannot express cleanly (vector-column
writes, ``jsonb_set`` mutations, the bus-timetable rebuild). No business logic, no
LLM calls — repositories take a ``db: AsyncSession`` and execute SQL; coercion /
orchestration live in ``coercion.py`` / ``pipeline.py``.
"""

from app.services.knowledge.chunk_repository import KnowledgeChunkRepo
from app.services.knowledge.document_repository import (
    KnowledgeDocumentRepo,
    mark_document_failed_sync,
    mark_version_failed_sync,
)
from app.services.knowledge.job_feature_repository import JobFeatureValueRepo
from app.services.knowledge.project_index_repository import (
    ProjectIndexRepo,
    rebuild_bus_timetable,
)

__all__ = [
    "JobFeatureValueRepo",
    "KnowledgeChunkRepo",
    "KnowledgeDocumentRepo",
    "ProjectIndexRepo",
    "rebuild_bus_timetable",
    "mark_document_failed_sync",
    "mark_version_failed_sync",
]
