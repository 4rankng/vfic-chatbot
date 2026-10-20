"""Cloudfone call transcripts — one row per transcribed call.

Written by the daily insights pass after MiniMax STT so reruns and later
analysis never re-download the WAV recording or re-run STT. Additive table
(migration 0076); rows are append-only, keyed by the vendor call id.
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
