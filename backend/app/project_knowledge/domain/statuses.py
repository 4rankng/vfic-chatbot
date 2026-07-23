"""Knowledge lifecycle value types owned by the project-knowledge domain."""

from __future__ import annotations

from enum import Enum


class KnowledgeStatus(str, Enum):
    UPLOADED = "UPLOADED"
    PROCESSING = "PROCESSING"
    PUBLISHED = "PUBLISHED"
    ARCHIVED = "ARCHIVED"
    FAILED = "FAILED"


class KBVersionStatus(str, Enum):
    DRAFT = "DRAFT"
    INDEXING = "INDEXING"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    READY = "READY"
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"
    FAILED = "FAILED"


class KnowledgeBaseMode(str, Enum):
    RAG = "RAG"
    DIRECT_CONTEXT = "DIRECT_CONTEXT"


class KnowledgeCategoryRevisionStatus(str, Enum):
    STAGED = "STAGED"
    PROCESSING = "PROCESSING"
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"
    FAILED = "FAILED"
    CLEARED = "CLEARED"

