"""Persistent transcript cache for the Cloudfone daily insights pass.

One row per call (``cloudfone_call_transcripts``, migration 0076). The pipeline
reads it before downloading a recording and writes it after MiniMax STT, so a
rerun or a later analysis pass never pays the WAV download + STT cost twice.
The admin transcripts screen reads the same rows through the list/get queries
below.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING, Protocol

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.cloudfone import CloudfoneCallTranscript

if TYPE_CHECKING:
    from app.services.cloudfone import CallRecord


class TranscriptStore(Protocol):
    """Seam over the transcript cache; ``run_cloudfone_insights`` accepts any impl."""

    async def load(self, call_id: str) -> str | None: ...

    async def save(self, call: CallRecord, transcript: str, day: date) -> None: ...


class DbTranscriptStore:
    """SQLAlchemy-backed :class:`TranscriptStore`."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def load(self, call_id: str) -> str | None:
        row = await self._db.execute(
            select(CloudfoneCallTranscript.transcript).where(
                CloudfoneCallTranscript.call_id == call_id
            )
        )
        return row.scalar_one_or_none()

    async def save(self, call: CallRecord, transcript: str, day: date) -> None:
        self._db.add(
            CloudfoneCallTranscript(
                call_id=call.call_id,
                day=day,
                started_at=call.started_at,
                caller=call.caller,
                talk_seconds=call.talk_seconds,
                transcript=transcript,
            )
        )
        try:
            await self._db.commit()
        except Exception:
            # Keep the session usable after a failed write (e.g. a unique-constraint
            # race): the caller fail-softs and the letter must still go out.
            await self._db.rollback()
            raise


async def list_call_transcripts(
    db: AsyncSession,
    *,
    day: date | None = None,
    caller: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[CloudfoneCallTranscript], int]:
    """One page of stored transcripts, newest call first, plus the filtered total.

    ``caller`` matches anywhere in the phone number (admin lookup habit: paste
    a fragment); ``day`` filters on the call day the pipeline stored.
    """
    filters = []
    if day is not None:
        filters.append(CloudfoneCallTranscript.day == day)
    if caller:
        filters.append(CloudfoneCallTranscript.caller.contains(caller, autoescape=True))
    total = await db.scalar(select(func.count()).select_from(CloudfoneCallTranscript).where(*filters))
    rows = (
        await db.scalars(
            select(CloudfoneCallTranscript)
            .where(*filters)
            .order_by(
                CloudfoneCallTranscript.started_at.desc(),
                CloudfoneCallTranscript.id.desc(),
            )
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    return list(rows), int(total or 0)


async def get_call_transcript(
    db: AsyncSession, call_id: str
) -> CloudfoneCallTranscript | None:
    """One stored transcript by the vendor call id, or ``None``."""
    return await db.scalar(
        select(CloudfoneCallTranscript).where(
            CloudfoneCallTranscript.call_id == call_id
        )
    )
