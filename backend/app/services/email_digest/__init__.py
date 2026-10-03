"""Candidate email digest service package."""

from app.services.email_digest.service import (
    DigestRunResult,
    TestDigestResult,
    is_due,
    run_digest,
    send_test_digest,
)

__all__ = [
    "DigestRunResult",
    "TestDigestResult",
    "is_due",
    "run_digest",
    "send_test_digest",
]
