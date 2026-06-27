"""Worker product-feature ORM models (mirror Alembic migration 0004).

``WorkerFeatureCatalog`` is the seeded list of 16 worker-interest product features.
``JobFeatureValue`` holds the per-project, LLM-extracted value (text + structured JSON)
the chatbot grounds answers on via the ``get_product_features`` tool.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class WorkerFeatureCatalog(Base):
    __tablename__ = "worker_feature_catalog"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    feature_key: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    name_vi: Mapped[str] = mapped_column(String, nullable=False)
    category: Mapped[str] = mapped_column(String, nullable=False)
    worker_question_vi: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    default_importance_score: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), nullable=False, default=Decimal("0.50"), server_default=text("0.50")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))


class JobFeatureValue(Base):
    __tablename__ = "job_feature_values"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    feature_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("worker_feature_catalog.id", ondelete="CASCADE"), nullable=False
    )
    value_text: Mapped[str] = mapped_column(Text, nullable=False)
    value_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb"))
    strength_score: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), nullable=False, default=Decimal("0.50"), server_default=text("0.50")
    )
    display_priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100, server_default=text("100"))
    is_highlight: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    is_missing: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    needs_clarification: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    evidence_text: Mapped[str | None] = mapped_column(Text)
    source_document_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("knowledge_documents.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
