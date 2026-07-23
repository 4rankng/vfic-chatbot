"""Compatibility facade for recruitment-owned provider scope policy."""

from __future__ import annotations

from app.recruitment.domain.provider import provider_from_conversation

__all__ = ["provider_from_conversation"]
