"""Canonical-Markdown bus-route parser.

Lifts ``BusRoute`` / ``ServiceDay`` records out of the ``Bus Routes`` section of a
canonical knowledge document (the admin-authored Markdown contract). This is
distinct from :mod:`bus_timetable.parser`, which extracts routes from free-form
LG-Display HTML. Depends only on the bus-timetable data models / normalize / repair
constants plus a few shared text primitives — no DB, no LLM.
"""

from __future__ import annotations

import re
from datetime import time
from typing import Any

from app.services.knowledge._canonical_helpers import _is_empty, _parse_scalar, _subsections
from app.services.knowledge.bus_timetable.models import (
    BusRoute,
    BusStop,
    ParsedBusTimetable,
    ServiceDay,
)
from app.services.knowledge.bus_timetable.normalize import normalize_bus_route_key
from app.services.knowledge.bus_timetable.repair import (
    SERVICE_FLAG_RE as _SERVICE_FLAG_RE,
    SERVICE_LINE_RE as _SERVICE_RE,
    VALID_DAY_GROUPS as _VALID_DAY_GROUPS,
    VALID_SERVICE_TYPES as _VALID_SERVICE_TYPES,
)

_TIME_RE = re.compile(r"^\d{2}:\d{2}$")
_ROUTE_FIELD_RE = re.compile(r"^([a-zA-Z_][a-zA-Z0-9_]*):\s*(.*)$")


def parse_bus_routes(
    metadata: dict[str, Any], section: str, errors: list[str]
) -> ParsedBusTimetable:
    if not section.strip():
        return ParsedBusTimetable()
    blocks = _subsections(section)
    routes: list[BusRoute] = []
    service_days: list[ServiceDay] = []
    for title, block in blocks:
        if not title.lower().startswith("bus route:"):
            continue
        route_errors: list[str] = []
        fields, table_rows = _route_fields_and_rows(block, route_errors, title)
        mode = str(fields.get("mode") or "")
        status_only = mode == "status_only"
        required = ("route_id", "route_group", "route_name")
        if not status_only:
            required = (*required, "shift", "direction")
        for key in required:
            if _is_empty(fields.get(key)):
                route_errors.append(f"{title}: {key} is required")
        shift = str(fields.get("shift") or "")
        direction = str(fields.get("direction") or "")
        if shift and not status_only and shift not in {"day", "night", "admin"}:
            route_errors.append(f"{title}: shift must be day, night, or admin")
        if direction and not status_only and direction not in {"outbound", "return"}:
            route_errors.append(f"{title}: direction must be outbound or return")
        route_name = str(fields.get("route_name") or fields.get("route_group") or "")
        route_group = str(fields.get("route_group") or route_name)
        parsed_service_days = _parse_service_days(fields, route_group, route_errors, title)
        if status_only:
            if route_errors:
                continue
            service_days.extend(parsed_service_days)
            continue
        if not table_rows:
            route_errors.append(f"{title}: stops table is required")
        stops = [_parse_stop(row, route_errors, title) for row in table_rows]
        if route_errors:
            continue
        service_days.extend(parsed_service_days)
        route_id = str(fields.get("route_id") or normalize_bus_route_key(route_name))
        routes.append(
            BusRoute(
                route_name=route_name,
                route_no=_optional_str(fields.get("route_no")),
                route_variant=str(fields.get("route_variant") or ""),
                route_group_key=normalize_bus_route_key(route_group),
                shift=shift or "day",
                direction=direction or "outbound",
                area=_optional_str(fields.get("area")),
                mode=_optional_str(fields.get("mode")),
                source_page=str(metadata.get("doc_id") or ""),
                notes=_optional_str(fields.get("notes")),
                metadata={"route_id": route_id, "route_text": route_name, "canonical": True},
                stops=stops,
            )
        )
    return ParsedBusTimetable(routes=routes, service_days=service_days)


def _route_fields_and_rows(
    block: str, errors: list[str], title: str
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    fields: dict[str, Any] = {}
    lines = block.splitlines()
    table_start = next((i for i, line in enumerate(lines) if line.strip().startswith("|")), None)
    meta_lines = lines[: table_start if table_start is not None else len(lines)]
    current = None
    for raw in meta_lines:
        line = raw.strip()
        if not line:
            continue
        if line == "service_days:":
            current = "service_days"
            fields[current] = []
            continue
        if current == "service_days" and line.startswith("-"):
            fields[current].append(line)
            continue
        match = _ROUTE_FIELD_RE.match(line)
        if match:
            fields[match.group(1)] = _parse_scalar(match.group(2))
            current = None
    rows = (
        _parse_markdown_table(lines[table_start:], errors, title) if table_start is not None else []
    )
    return fields, rows


def _parse_markdown_table(lines: list[str], errors: list[str], title: str) -> list[dict[str, str]]:
    table = [line.strip() for line in lines if line.strip().startswith("|")]
    if len(table) < 3:
        errors.append(f"{title}: stops table is required")
        return []
    headers = _table_cells(table[0])
    required = ["stop_order", "stop_name", "aliases", "scheduled_time", "notes"]
    if headers != required:
        errors.append(f"{title}: stops table columns must be {' | '.join(required)}")
        return []
    rows = []
    for raw in table[2:]:
        cells = _table_cells(raw)
        if len(cells) != len(headers):
            errors.append(f"{title}: malformed stops table row {raw!r}")
            continue
        rows.append(dict(zip(headers, cells, strict=True)))
    return rows


def _table_cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _parse_stop(row: dict[str, str], errors: list[str], title: str) -> BusStop:
    raw_order = row.get("stop_order", "")
    try:
        order = int(raw_order)
    except ValueError:
        errors.append(f"{title}: stop_order must be an integer")
        order = 0
    scheduled = None
    raw_time = (row.get("scheduled_time") or "").strip()
    if raw_time:
        if not _TIME_RE.match(raw_time):
            errors.append(f"{title}: scheduled_time must use HH:MM")
        else:
            try:
                scheduled = time.fromisoformat(raw_time)
            except ValueError:
                errors.append(f"{title}: scheduled_time is not valid")
    aliases = tuple([row.get("stop_name", "").strip()] + _split_aliases(row.get("aliases", "")))
    return BusStop(
        stop_order=order,
        stop_name=row.get("stop_name", "").strip(),
        stop_aliases=aliases,
        scheduled_time=scheduled,
        raw_stop_text=" @".join([row.get("stop_name", "").strip(), raw_time]).strip(" @"),
    )


def _parse_service_days(
    fields: dict[str, Any], route_group_name: str, errors: list[str], title: str
) -> list[ServiceDay]:
    rows: list[ServiceDay] = []
    route_group_key = normalize_bus_route_key(route_group_name)
    for raw in fields.get("service_days") or []:
        match = _SERVICE_RE.match(raw)
        if match is None:
            errors.append(f"{title}: malformed service_days line {raw!r}")
            continue
        day_group, flags = match.groups()
        if day_group not in _VALID_DAY_GROUPS:
            errors.append(f"{title}: unknown service day {day_group!r}")
            continue
        for flag in flags.split(","):
            flag_match = _SERVICE_FLAG_RE.match(flag)
            if flag_match is None:
                errors.append(f"{title}: malformed service flag {flag.strip()!r}")
                continue
            service_type, code = flag_match.groups()
            if service_type not in _VALID_SERVICE_TYPES:
                errors.append(f"{title}: unknown service type {service_type!r}")
                continue
            rows.append(
                ServiceDay(
                    route_group_key=route_group_key,
                    route_group_name=route_group_name,
                    day_group=day_group,
                    day_label=day_group,
                    service_type=service_type,
                    availability_code=code,
                    metadata={"parsed_from": "canonical_markdown"},
                )
            )
    return rows


def _split_aliases(value: str) -> list[str]:
    return [part.strip() for part in re.split(r"[,;]", value or "") if part.strip()]


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
