"""Code-owned ceilings for inbound uploads and webhook bodies.

These limits intentionally accept no administrator-supplied override.  They are
checked before parsers, archive expansion, or LLM fallback work can allocate
unbounded resources. The template-ingestion pipeline that consumed the
remaining ceilings (archive/tabular/LLM-batch limits) was removed with the rest
of this package; only the two ingress gates below have production callers.
"""

from __future__ import annotations

MAX_UPLOAD_BYTES = 20 * 1024 * 1024
# Inbound webhook bodies are provider event envelopes (a few KB); 1 MiB is
# generous headroom. The cap exists so a hostile/unauthenticated POST cannot make
# the ASGI layer buffer an arbitrarily large body before any check runs (SEC-05).
MAX_WEBHOOK_BODY_BYTES = 1 * 1024 * 1024


class IngestionLimitError(ValueError):
    """Raised before an input can consume resources beyond a hard ceiling."""


def _assert_at_most(value: int, limit: int, label: str) -> None:
    if value < 0 or value > limit:
        raise IngestionLimitError(f"{label} exceeds the code-owned limit of {limit}")


def assert_upload_size(size_bytes: int) -> None:
    _assert_at_most(size_bytes, MAX_UPLOAD_BYTES, "upload")


def assert_webhook_body_size(size_bytes: int) -> None:
    _assert_at_most(size_bytes, MAX_WEBHOOK_BODY_BYTES, "webhook body")
