"""Pure-Python port of the ``rebuild_bus_timetable_from_documents`` parser.

Authoritative spec: the PL/pgSQL in ``alembic/versions/0001_baseline.py:616-1079``.
This is a *behaviour-identical* port, not a redesign — every branch, regex, and
reset below mirrors the SQL line loop so the golden-gate test can prove
byte-identical output on the canonical corpus (``kb/LGDisplay/LGDisplay.txt``).

POSIX-ARE → Python ``re`` notes baked in here:
  * lines split on the literal ``\n`` (``str.split`` — NOT ``splitlines``); per-line
    ``.strip()`` == PG ``btrim`` (also strips a trailing ``\r``).
  * ``regexp_replace(x, '^- ', '')`` without the ``g`` flag is first-match-only →
    ``re.sub(..., count=1)``.
  * ``ilike '%X%'`` → ``X.casefold() in s.casefold()`` substring test.
"""
from __future__ import annotations

import datetime
import re

from app.services.knowledge.bus_timetable.models import (
    BusRoute,
    BusStop,
    ParsedBusTimetable,
    ServiceDay,
)
from app.services.knowledge.bus_timetable.normalize import normalize_bus_route_key

# Verbatim alias literals from the SQL (routes section: 10, admin section: 2).
# Aliases are appended (order preserved, NO dedup — mirrors array_remove(..., null)).
_ROUTE_STOP_ALIASES = (
    "Kiến An",
    "Quán Toan",
    "An Dương",
    "Đồ Sơn",
    "An Lão",
    "Kiến Thụy",
    "Vĩnh Bảo",
    "Thái Bình",
    "Hải Dương",
    "Quảng Yên",
)
_ADMIN_STOP_ALIASES = ("Hà Nội", "Gia Lâm")

_DAY_GROUPS = {
    "Thứ Hai đến Thứ Năm": "mon_thu",
    "Thứ Sáu": "fri",
    "Thứ Bảy": "sat",
    "Chủ Nhật": "sun",
}

_RE_WEEKLY_ROUTE = re.compile(r"^\d+\.\s+(.+)$")
_RE_DAY_GROUP = re.compile(r"^-?\s*(Thứ Hai đến Thứ Năm|Thứ Sáu|Thứ Bảy|Chủ Nhật):\s+(.+)$")
_RE_FLAG = re.compile(r"^\s*([a-z_]+)\s*=\s*([AMX])\s*$")
_RE_HEADER = re.compile(
    r"^### Tuyến\s+([^:]+):\s+([^|\n]+)\s+\|\s+Khu vực:\s+([^|\n]+)\s+\|\s+"
    r"Chế độ:\s+([^|\n]+)\s+\|\s+Trang\s+(\d+)"
)
_RE_NOTE_PREFIX = re.compile(r"^(Ghi chú|Điều kiện):")
_RE_ROUTE = re.compile(r"^- Lộ trình\s+([^:]+):\s+(.+)$")
_RE_ADMIN_NOTE = re.compile(r"^- Ghi chú")
_RE_ADMIN_ROUTE = re.compile(r"^- .*@\d{2}:\d{2}.*LGD")
_RE_STOP_SPLIT = re.compile(r"\s*->\s*")
_RE_TIME_SUFFIX = re.compile(r"@\d{2}:\d{2}$")
_RE_TIME_CAPTURE = re.compile(r"@(\d{2}:\d{2})$")
_LEADING_DASH = re.compile(r"^- ")


def _concat_ws(sep_first: str | None, sep_second: str | None) -> str | None:
    """``concat_ws(E'\\n', a, b)``: join non-NULL args (empty strings ARE kept)."""
    parts = [x for x in (sep_first, sep_second) if x is not None]
    return "\n".join(parts) if parts else None


def _build_aliases(stop_name: str, literals: tuple[str, ...]) -> tuple[str, ...]:
    """Mirror ``array_remove(array[stop_name, <ilike cases>], null)``.

    Order preserved, duplicates kept (SQL array_remove only drops NULLs).
    """
    lowered = stop_name.casefold()
    out = [stop_name]
    for lit in literals:
        if lit.casefold() in lowered:
            out.append(lit)
    return tuple(out)


def _parse_stops(stops_text: str, aliases: tuple[str, ...]) -> list[BusStop]:
    stops: list[BusStop] = []
    for idx, stop_part in enumerate(_RE_STOP_SPLIT.split(stops_text), start=1):
        stop_name = _RE_TIME_SUFFIX.sub("", stop_part).strip()
        time_match = _RE_TIME_CAPTURE.search(stop_part)
        scheduled = None
        if time_match is not None:
            h, m = time_match.group(1).split(":")
            scheduled = datetime.time(int(h), int(m))
        stops.append(
            BusStop(
                stop_order=idx,
                stop_name=stop_name,
                stop_aliases=_build_aliases(stop_name, aliases),
                scheduled_time=scheduled,
                raw_stop_text=stop_part.strip(),
            )
        )
    return stops


def parse_bus_timetable(content: str) -> ParsedBusTimetable:
    """Parse LGDisplay-style bus-timetable markdown into routes + service-days.

    Mirrors the ``for rec in select ... loop`` of the PL/pgSQL fn over one document
    (the caller fetches the single ``LGDisplay.txt`` document content).
    """
    routes: list[BusRoute] = []
    service_days: list[ServiceDay] = []

    current_route_no: str | None = None
    current_route_name: str | None = None
    current_area: str | None = None
    current_mode: str | None = None
    current_page: str | None = None
    current_shift: str | None = None
    current_section: str | None = None
    current_weekly_route_name: str | None = None
    current_weekly_route_key: str | None = None
    pending_notes: str | None = None
    current_admin_block: str | None = None

    for _line_no, raw in enumerate(content.split("\n"), start=1):
        line_text = raw.strip()
        if line_text == "":
            continue

        # --- section headers ---
        if line_text.startswith("## 1. Bảng hoạt động theo tuần"):
            current_section = "weekly"
            current_weekly_route_name = None
            current_weekly_route_key = None
            continue
        if line_text.startswith("## 2. Ca ngày"):
            current_section = "routes"
            current_shift = "day"
            current_route_name = None
            pending_notes = None
            continue
        if line_text.startswith("## 3. Ca hành chính"):
            current_section = "admin"
            current_shift = "admin"
            current_admin_block = None
            current_route_name = None
            pending_notes = None
            continue
        if line_text.startswith("## 4. Ca đêm"):
            current_section = "routes"
            current_shift = "night"
            current_route_name = None
            pending_notes = None
            continue
        if line_text.startswith("## 5. Mục cần giữ nguyên"):
            current_section = "done"
            continue

        # --- weekly matrix ---
        if current_section == "weekly":
            weekly_match = _RE_WEEKLY_ROUTE.match(line_text)
            if weekly_match is not None:
                current_weekly_route_name = weekly_match.group(1).strip()
                current_weekly_route_key = normalize_bus_route_key(current_weekly_route_name)
                continue

            day_match = _RE_DAY_GROUP.match(line_text)
            if day_match is not None and current_weekly_route_key is not None:
                day_label = day_match.group(1)
                day_group = _DAY_GROUPS.get(day_label)
                for flag in re.split(r"\s*,\s*", day_match.group(2)):
                    flag_match = _RE_FLAG.match(flag)
                    if flag_match is None:
                        continue
                    service_days.append(
                        ServiceDay(
                            route_group_key=current_weekly_route_key,
                            route_group_name=current_weekly_route_name,  # type: ignore[arg-type]
                            day_group=day_group,
                            day_label=day_label,
                            service_type=flag_match.group(1),
                            availability_code=flag_match.group(2),
                            metadata={"parsed_from": "weekly_matrix"},
                        )
                    )
            continue

        # --- routes (day / night shifts) ---
        if current_section == "routes":
            header_match = _RE_HEADER.match(line_text)
            if header_match is not None:
                current_route_no = header_match.group(1).strip()
                current_route_name = header_match.group(2).strip()
                current_area = header_match.group(3).strip()
                current_mode = header_match.group(4).strip()
                current_page = header_match.group(5).strip()
                pending_notes = None
                continue

            if _RE_NOTE_PREFIX.match(line_text) is not None:
                pending_notes = _concat_ws(pending_notes, line_text)
                continue

            route_match = _RE_ROUTE.match(line_text)
            if route_match is not None and current_route_name is not None:
                stops_text = route_match.group(2).strip()
                routes.append(
                    BusRoute(
                        route_name=current_route_name,
                        route_no=current_route_no,
                        route_variant=route_match.group(1).strip(),
                        route_group_key=normalize_bus_route_key(current_route_name),
                        shift=current_shift,  # type: ignore[arg-type]
                        direction="outbound",
                        area=current_area,
                        mode=current_mode,
                        source_page=current_page,
                        notes=pending_notes,
                        metadata={"route_text": stops_text},
                        stops=_parse_stops(stops_text, _ROUTE_STOP_ALIASES),
                    )
                )
                pending_notes = None
            continue

        # --- admin (Hà Nội outbound) ---
        if current_section == "admin":
            if line_text.startswith("### Lượt đi tuyến Hà Nội"):
                current_admin_block = "hanoi_outbound"
                pending_notes = None
                continue

            if _RE_ADMIN_NOTE.match(line_text) is not None:
                pending_notes = _concat_ws(pending_notes, _LEADING_DASH.sub("", line_text, count=1))
                continue

            if current_admin_block == "hanoi_outbound" and _RE_ADMIN_ROUTE.match(line_text) is not None:
                route_text = _LEADING_DASH.sub("", line_text, count=1)
                routes.append(
                    BusRoute(
                        route_name="Hà Nội",
                        route_no="18",
                        route_variant="1",
                        route_group_key=normalize_bus_route_key("Hà Nội"),
                        shift="admin",
                        direction="outbound",
                        area="Hà Nội",
                        mode="standard",
                        source_page="6",
                        notes=pending_notes,
                        metadata={"route_text": route_text},
                        stops=_parse_stops(route_text, _ADMIN_STOP_ALIASES),
                    )
                )
                pending_notes = None
            # (no `continue` in the SQL admin branch — falls through to next line)

    return ParsedBusTimetable(routes=routes, service_days=service_days)
