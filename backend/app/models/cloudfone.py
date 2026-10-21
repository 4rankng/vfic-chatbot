"""Cloudfone call transcripts — one row per transcribed call.

Written by the daily insights pass after MiniMax STT so reruns and later
analysis never re-download the WAV recording or re-run STT. Additive table
(migration 0076); rows are append-only, keyed by the vendor call id.

``CloudfoneTranscriptDay`` is the companion marker (migration 0077): one row
per call day that was already fetched from Cloudfone. It is what tells the
admin viewer that a day is known — checked and empty — instead of fetching it
from the vendor again.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class CloudfoneCallTranscript(Base):
    __tablename__ = "cloudfone_call_transcripts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    call_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    day: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    started_at: Mapped[str] = mapped_column(String(40), nullable=False)
    caller: Mapped[str] = mapped_column(String(64), nullable=False)
    talk_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    transcript: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )


class CloudfoneTranscriptDay(Base):
    """One inspected Cloudfone call day — the marker that says "fetched".

    The daily insights pass writes it for the day it processed and the viewer
    backfill writes it for a day it pulled on demand. ``status`` is ``checked``
    (the day was fetched, ``transcript_count`` says whether it held anything)
    or ``error`` (the fetch failed, so a later attempt may retry).
    """

    __tablename__ = "cloudfone_transcript_days"

    day: Mapped[date] = mapped_column(Date, primary_key=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    call_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    recordable_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    transcript_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    checked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
