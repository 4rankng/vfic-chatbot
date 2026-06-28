"""Bus-timetable parser package (pure Python) + repository.

Layering (mirrors the parent ``knowledge`` package):
    models/     frozen dataclasses (stdlib only)
    normalize/  unaccent + route-key port (stdlib only)
    parser/     line-by-line state machine (models + normalize only — no DB)
    repository/ raw-SQL persistence (sqlalchemy + app.core only)
"""
from __future__ import annotations

from app.services.knowledge.bus_timetable.models import (
    BusRoute,
    BusStop,
    ParsedBusTimetable,
    ServiceDay,
)
from app.services.knowledge.bus_timetable.normalize import (
    normalize_bus_route_key,
    normalize_search_text,
)
from app.services.knowledge.bus_timetable.parser import parse_bus_timetable

__all__ = [
    "BusRoute",
    "BusStop",
    "ParsedBusTimetable",
    "ServiceDay",
    "normalize_bus_route_key",
    "normalize_search_text",
    "parse_bus_timetable",
]
