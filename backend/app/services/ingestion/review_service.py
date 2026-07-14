"""Review API service + bundle assembly (Tech-Lead Directive §9 stage 9).

Assembles the review bundle (original fragments + extracted envelopes +
validation issues + audit) for the recruiter review screen. The API endpoints
+ frontend ship in a follow-up — this module is the data layer.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.provenance import (
    SourceDocument,
    SourceFragment,
)
from app.services.ingestion.validation import ValidationIssue, validate_envelope


@dataclass(frozen=True)
class ReviewBundle:
    """The data bundle shown on the review screen."""

    document: dict
    fragments: list[dict]
    validation_issues: list[dict]
    audit: list[dict]


async def assemble_review_bundle(
    db: AsyncSession, doc_id: int, envelopes: list = None
) -> ReviewBundle | None:
    """Build the review bundle for ``doc_id``. Returns None when not found."""
    doc = await db.get(SourceDocument, doc_id)
    if doc is None:
        return None
    fragments = (
        await db.execute(
            select(SourceFragment)
            .where(SourceFragment.document_id == doc_id)
            .order_by(SourceFragment.block_order)
        )
    ).scalars().all()
    fragment_dicts = [
        {
            "id": f.id,
            "page": f.page_number,
            "section_path": f.section_path,
            "block_type": f.block_type,
            "section_type": f.section_type,
            "original_text": f.original_text,
            "normalized_text": f.normalized_text,
        }
        for f in fragments
    ]
    # Validate envelopes (if provided by the caller) to surface issues.
    issues: list[ValidationIssue] = []
    if envelopes:
        for env in envelopes:
            issues.extend(validate_envelope(env))
    return ReviewBundle(
        document={
            "id": doc.id,
            "filename": doc.filename,
            "status": doc.status,
            "mime_type": doc.mime_type,
        },
        fragments=fragment_dicts,
        validation_issues=[
            {"severity": i.severity, "code": i.code, "message": i.message, "field_path": i.field_path}
            for i in issues
        ],
        audit=[],  # populated from audit table in a follow-up
    )


# Outcomes (directive §9 stage 9)
REVIEW_OUTCOMES = ("AUTO_PUBLISH", "HUMAN_REVIEW", "QUARANTINE")

# Critical fields requiring human sign-off (directive §9).
CRITICAL_FIELDS = (
    "data.value",  # benefit/salary amounts
    "data.trips",  # bus times
    "data.start_time",  # working hours
    "data.eligibility",  # eligibility constraints
)


def classify_outcome(issues: list[ValidationIssue], has_critical_field: bool) -> str:
    """Decide AUTO_PUBLISH / HUMAN_REVIEW / QUARANTINE from validation issues."""
    if any(i.severity == "error" for i in issues):
        if has_critical_field:
            return "HUMAN_REVIEW"
        return "HUMAN_REVIEW"
    if has_critical_field:
        return "HUMAN_REVIEW"
    return "AUTO_PUBLISH"
