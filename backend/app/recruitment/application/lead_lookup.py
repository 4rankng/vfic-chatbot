"""Distinguish a lead lookup that missed from one that has not run yet."""

from __future__ import annotations

from enum import Enum
from typing import Any, TypeAlias


class UnresolvedLead(Enum):
    VALUE = "unresolved"


UNRESOLVED_LEAD = UnresolvedLead.VALUE
LeadRecord: TypeAlias = dict[str, Any]
LeadLookup: TypeAlias = LeadRecord | None | UnresolvedLead


__all__ = ["LeadLookup", "LeadRecord", "UNRESOLVED_LEAD", "UnresolvedLead"]
