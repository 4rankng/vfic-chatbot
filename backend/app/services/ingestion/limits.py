"""Code-owned ceilings for inbound uploads and webhook bodies.

These limits intentionally accept no administrator-supplied override.  They are
checked before parsers, archive expansion, or LLM fallback work can allocate
unbounded resources. The template-ingestion pipeline that consumed the
remaining ceilings (archive/tabular/LLM-batch limits) was removed with the rest
of this package; only the two ingress gates below have production callers.

The upload gate also owns the *rejection*: every admin multipart route reads
through :func:`read_upload_within_limit`, so one bounded read and one 413
response serve all of them (SEC-05, SEC-10).
"""

from __future__ import annotations

from fastapi import HTTPException, UploadFile, status

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


def upload_too_large_detail() -> str:
    """The single 413 detail every admin upload route returns for an over-size body."""
    return f"Tệp vượt quá giới hạn {MAX_UPLOAD_BYTES // (1024 * 1024)} MB."


def reject_oversized_upload(size_bytes: int) -> None:
    """Map an over-ceiling upload size onto the shared 413 rejection.

    :class:`IngestionLimitError` is a ``ValueError`` subclass so callers that
    only guard with ``except ValueError`` keep working.
    """
    try:
        assert_upload_size(size_bytes)
    except IngestionLimitError as exc:
        raise HTTPException(
            status.HTTP_413_CONTENT_TOO_LARGE,
            upload_too_large_detail(),
        ) from exc


async def read_upload_within_limit(upload: UploadFile) -> bytes:
    """Read a multipart upload without ever materializing more than the ceiling.

    ``UploadFile.read()`` with no argument pulls the whole part into one
    allocation before any size check can run; Starlette only spools the *disk*
    copy. The bounded read stops at ``MAX_UPLOAD_BYTES + 1`` bytes, which is
    enough to tell "at the ceiling" from "over it" and nothing more.

    A ``Content-Length`` precheck (the pattern ``api/webhooks.py`` uses on the
    raw-body surface) is deliberately NOT applied here: a multipart
    Content-Length also counts the part headers and boundaries, so rejecting on
    it would turn an exactly-at-the-ceiling file into a 413.
    """
    data = await upload.read(MAX_UPLOAD_BYTES + 1)
    reject_oversized_upload(len(data))
    return data
