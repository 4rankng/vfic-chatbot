"""Pure-Python port of the DB normalizers used by the bus-timetable parser.

Byte-identical to the SQL ``public.normalize_search_text`` /
``public.normalize_bus_route_key`` (alembic 0001_baseline.py:490-537), validated
against the live DB over the real Vietnamese corpus by the golden gate's T-0
parity test.

Key fidelity point: Postgres ``unaccent`` maps ``đ``/``Đ`` to ``d`` (the default
``unaccent.rules`` covers them), but ``unicodedata.NFD`` does NOT decompose
``đ`` (U+0111). So an explicit ``đ/Đ`` translation must run BEFORE NFD, or every
``đ``-bearing name (Hà Nội, Đông Triều, Hưng Hà, …) would mis-normalise.
"""

from __future__ import annotations

import re
import unicodedata

# đ (U+0111) / Đ (U+0110) have no canonical NFD decomposition; unaccent maps both
# to d. Translate up-front so NFD + Mn-strip reproduce unaccent exactly.
_DIACRITIC_TABLE = str.maketrans({"đ": "d", "Đ": "d"})

_COMBINING_MARKS = re.compile(r"[̀-ͯ]")  # Mn block (combining diacritics)
_NON_ALNUM = re.compile(r"[^a-zA-Z0-9]+")
_WS_RUNS = re.compile(r"\s+")


def normalize_search_text(value: str | None) -> str:
    """Lowercase, unaccent, collapse non-alphanumeric → single spaces.

    Mirrors: ``lower(regexp_replace(unaccent(coalesce(value, '')), '[^a-zA-Z0-9]+', ' ', 'g'))``.
    """
    s = (value or "").translate(_DIACRITIC_TABLE)
    s = unicodedata.normalize("NFD", s)
    s = _COMBINING_MARKS.sub("", s)
    s = _NON_ALNUM.sub(" ", s)
    return s.lower()


def normalize_bus_route_key(name: str | None) -> str:
    """``normalize_search_text`` + whitespace tidy + a few canonical alias rewrites.

    Mirrors ``public.normalize_bus_route_key`` (alembic 0001_baseline.py:503-537).
    """
    v = normalize_search_text(name)
    v = _WS_RUNS.sub(" ", v)
    v = v.strip()
    if v == "":
        return ""
    if v in ("ktx cd bac bo", "ktx cao dang bac bo"):
        return "ktx cao dang bac bo"
    if v == "cau rao 1":
        return "cau rao"
    if v == "tl cau dam":
        return "tien lang cau dam"
    if v == "tl hung thang":
        return "tien lang hung thang"
    return v
