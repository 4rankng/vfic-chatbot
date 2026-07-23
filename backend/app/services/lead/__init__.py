"""Lead service package.

Public API — import from here:
    from app.services.lead import LeadService, lead_profile_text
"""

from app.services.lead.service import LeadService
from app.services.lead.normalizers import (
    extract_self_reported_name,
    high_confidence_profile_name,
    lead_profile_text,
)

__all__ = [
    "LeadService",
    "extract_self_reported_name",
    "high_confidence_profile_name",
    "lead_profile_text",
]
