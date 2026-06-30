"""Backward-compat shim — import from ``app.services.lead`` instead.

.. deprecated::
   ``from app.services.lead_service import LeadConflict`` — use
   ``ConflictError`` from ``app.services.errors`` instead.
"""

from app.services.errors import ConflictError as LeadConflict  # noqa: F401
from app.services.lead.normalizers import (
    _pick,  # noqa: F401
    lead_profile_text,  # noqa: F401 — re-exported from __init__ too
    normalize_integer,  # noqa: F401
    normalize_lead,  # noqa: F401
    normalize_lead_score,  # noqa: F401
    normalize_phone,  # noqa: F401
    parse_lead_json,  # noqa: F401
)
from app.services.lead.service import LeadExtractionService, LeadService

__all__ = [
    "LeadConflict",
    "LeadExtractionService",
    "LeadService",
    "_pick",
    "lead_profile_text",
    "normalize_integer",
    "normalize_lead",
    "normalize_lead_score",
    "normalize_phone",
    "parse_lead_json",
]
