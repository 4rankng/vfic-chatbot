"""Code-owned resource ceilings for generic ingestion.

These limits intentionally accept no administrator-supplied override.  They are
checked before parsers, archive expansion, or LLM fallback work can allocate
unbounded resources.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from typing import TypeVar

MAX_UPLOAD_BYTES = 20 * 1024 * 1024
MAX_EXPANDED_ARCHIVE_BYTES = 200 * 1024 * 1024
MAX_ARCHIVE_MEMBERS = 2_000
MAX_ARCHIVE_COMPRESSION_RATIO = 100
MAX_SHEETS = 32
MAX_ROWS = 50_000
MAX_COLUMNS = 256
MAX_NON_EMPTY_CELLS = 250_000
MAX_CELL_BYTES = 32 * 1024
MAX_NORMALIZED_TEXT_BYTES = 10 * 1024 * 1024
MAX_SOURCE_BLOCKS = 10_000
MAX_RECORDS = 10_000
MAX_FIELDS_PER_RECORD = 128
MAX_ALIASES_PER_FIELD = 16
MAX_UNRESOLVED_LLM_BLOCKS = 100
MAX_BLOCKS_PER_LLM_CALL = 10
MAX_LLM_CALLS_PER_RUN = 10

_Item = TypeVar("_Item")


class IngestionLimitError(ValueError):
    """Raised before an input can consume resources beyond a hard ceiling."""


def _assert_at_most(value: int, limit: int, label: str) -> None:
    if value < 0 or value > limit:
        raise IngestionLimitError(f"{label} exceeds the code-owned limit of {limit}")


def assert_upload_size(size_bytes: int) -> None:
    _assert_at_most(size_bytes, MAX_UPLOAD_BYTES, "upload")


def assert_archive_metadata(*, expanded_bytes: int, members: int, compression_ratio: int) -> None:
    _assert_at_most(expanded_bytes, MAX_EXPANDED_ARCHIVE_BYTES, "expanded archive")
    _assert_at_most(members, MAX_ARCHIVE_MEMBERS, "archive member count")
    _assert_at_most(compression_ratio, MAX_ARCHIVE_COMPRESSION_RATIO, "archive compression ratio")


def assert_tabular_dimensions(*, sheets: int, rows: int, columns: int, non_empty_cells: int) -> None:
    _assert_at_most(sheets, MAX_SHEETS, "sheet count")
    _assert_at_most(rows, MAX_ROWS, "row count")
    _assert_at_most(columns, MAX_COLUMNS, "column count")
    _assert_at_most(non_empty_cells, MAX_NON_EMPTY_CELLS, "non-empty cell count")


def assert_normalized_text_size(size_bytes: int) -> None:
    _assert_at_most(size_bytes, MAX_NORMALIZED_TEXT_BYTES, "normalized text")


def bounded_batches(items: Iterable[_Item], *, batch_size: int) -> Iterator[list[_Item]]:
    """Yield bounded batches for the one-schema-per-batch LLM fallback."""
    if batch_size < 1 or batch_size > MAX_BLOCKS_PER_LLM_CALL:
        raise IngestionLimitError(f"batch size must be between 1 and {MAX_BLOCKS_PER_LLM_CALL}")
    batch: list[_Item] = []
    for item in items:
        batch.append(item)
        if len(batch) == batch_size:
            yield batch
            batch = []
    if batch:
        yield batch
