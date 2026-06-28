"""Pure dataclasses for the bus-timetable parser output (stdlib only)."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import time


@dataclass(frozen=True)
class BusStop:
    stop_order: int
    stop_name: str | None
    stop_aliases: tuple[str, ...]
    scheduled_time: time | None
    raw_stop_text: str


@dataclass(frozen=True)
class BusRoute:
    route_name: str | None
    route_no: str | None
    route_variant: str
    route_group_key: str
    shift: str
    direction: str
    area: str | None
    mode: str | None
    source_page: str | None
    notes: str | None
    metadata: dict
    stops: list[BusStop] = field(default_factory=list)


@dataclass(frozen=True)
class ServiceDay:
    route_group_key: str
    route_group_name: str
    day_group: str | None
    day_label: str
    service_type: str
    availability_code: str
    metadata: dict


@dataclass(frozen=True)
class ParsedBusTimetable:
    routes: list[BusRoute] = field(default_factory=list)
    service_days: list[ServiceDay] = field(default_factory=list)
