"""Persistent transcript cache for the Cloudfone daily insights pass.

One row per call (``cloudfone_call_transcripts``, migration 0076). The pipeline
reads it before downloading a recording and writes it after MiniMax STT, so a
rerun or a later analysis pass never pays the WAV download + STT cost twice.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING, Protocol

from sqlalchemy import select
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
