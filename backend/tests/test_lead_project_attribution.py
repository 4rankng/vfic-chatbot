"""Which dự án an ad points at — the cascade that reads Meta's referral.

A Click-to-Messenger ad carries the campaign signal in two places and nowhere
else: the ``ref`` an operator set per project (exact match against
``projects.slug`` / ``projects.aliases``), and ``ads_context_data.ad_title``,
the ad's own creative copy. Meta ships NO ``utm_*`` parameters on this path, so
these two are the whole signal.

``ref`` is exact and operator-typed, so it wins outright. ``ad_title`` is free
text, so it is held to a higher bar: active projects only, and an ambiguous
title resolves to nothing. Attributing a candidate to the wrong dự án is worse
than leaving them unattributed — the chat-focus signal can still pin them.
"""

from __future__ import annotations

import uuid

import pytest

from app.services.lead.interest import (
    resolve_project_from_ad_title,
    resolve_project_from_attribution,
)
from app.shared.domain.text import normalize_vietnamese_text


class _FakeResult:
    """Minimal stand-in for a SQLAlchemy ``.all()`` result of the catalog query."""

    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _FakeScalars:
    def __init__(self, values):
        self._values = values

    def __iter__(self):
        return iter(self._values)


class _Catalog:
    """Fake session serving the two queries the resolver makes.

    ``projects`` are ``(id, slug, name, aliases, is_active)`` tuples. ``execute``
    serves the catalog projection (``id, slug, name, aliases`` — the loader
    selects no ``is_active`` column, it orders by it) and ``scalars`` serves the
    active-id set. Anything raised surfaces as a catalog failure, which is how
    the never-raise contract is tested.
    """

    def __init__(self, projects=(), *, error: Exception | None = None):
        self.projects = list(projects)
        self.error = error

    async def execute(self, _stmt):
        if self.error is not None:
            raise self.error
        return _FakeResult(
            [(pid, slug, name, list(aliases or [])) for pid, slug, name, aliases, _a in self.projects]
        )

    async def scalars(self, _stmt):
        if self.error is not None:
            raise self.error
        return _FakeScalars(
            [pid for pid, _s, _n, _a, active in self.projects if active]
        )


def _project(slug: str, name: str, aliases=None, *, active: bool = True):
    return (uuid.uuid4(), slug, name, list(aliases or []), active)


# ── ad_title matching ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ad_title_matches_project_name_case_and_accent_insensitively() -> None:
    project = _project("rorze", "Rorze", ["Công ty Rorze Việt Nam"])
    db = _Catalog([project])

    # A recruiter-written ad title: different case, diacritics, extra words.
    resolved = await resolve_project_from_ad_title(db, "Tuyển dụng dự án RORZE - Hải Phòng")

    assert resolved == str(project[0])


@pytest.mark.asyncio
async def test_ad_title_matches_alias_and_slug_too() -> None:
    by_alias = _project("slug-a", "Alpha", ["Beta Factory"])
    db = _Catalog([by_alias])

    assert await resolve_project_from_ad_title(db, "Việc làm tại Beta Factory") == str(
        by_alias[0]
    )


@pytest.mark.asyncio
async def test_ad_title_requires_a_whole_word_match() -> None:
    project = _project("rorze", "Rorze")
    db = _Catalog([project])

    # "Rorze2" must not attribute the Rorze ad's traffic to Rorze.
    assert await resolve_project_from_ad_title(db, "Rorze2 tuyển người") is None


@pytest.mark.asyncio
async def test_ambiguous_ad_title_resolves_to_nothing() -> None:
    db = _Catalog([_project("rorze", "Rorze"), _project("lg", "LG Display")])

    assert await resolve_project_from_ad_title(db, "Tuyển dụng Rorze và LG Display") is None


@pytest.mark.asyncio
async def test_ad_title_ignores_inactive_projects() -> None:
    db = _Catalog([_project("old", "Dự án Cũ", active=False)])

    assert await resolve_project_from_ad_title(db, "Dự án Cũ tuyển người") is None


@pytest.mark.asyncio
async def test_ad_title_below_the_two_character_guard_is_ignored() -> None:
    # A one-character project name would match essentially any ad title, so the
    # in-chat resolver's min-2-chars rule is applied here too.
    db = _Catalog([_project("a", "A")])

    assert await resolve_project_from_ad_title(db, "A tuyển người") is None
    # A missing or empty title is never a project signal.
    assert await resolve_project_from_ad_title(db, "") is None
    assert await resolve_project_from_ad_title(db, None) is None


@pytest.mark.asyncio
async def test_two_character_project_name_is_still_matched() -> None:
    # The guard is "fewer than two characters", not "two or more excluded".
    project = _project("ab", "AB")
    db = _Catalog([project])

    assert await resolve_project_from_ad_title(db, "Tuyển AB") == str(project[0])


@pytest.mark.asyncio
async def test_ad_title_catalog_failure_degrades_to_no_project() -> None:
    db = _Catalog(error=RuntimeError("catalog down"))

    assert await resolve_project_from_ad_title(db, "Tuyển dụng Rorze") is None


@pytest.mark.asyncio
async def test_ad_title_matching_uses_the_same_normalizer_as_in_chat_resolution() -> None:
    # Pins the contract that ad-title matching and the in-chat project resolver
    # (graph/adapters.py) agree on how a Vietnamese name is compared: both route
    # through normalize_vietnamese_text, so an accent never decides attribution.
    assert normalize_vietnamese_text("RORZE") == normalize_vietnamese_text("Rorze")

    project = _project("rorze", "Rorze")
    db = _Catalog([project])

    assert await resolve_project_from_ad_title(db, "Rorze") == str(project[0])


# ── cascade precedence ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_post_code_wins_over_a_disagreeing_ad_title() -> None:
    by_code = _project("rorze", "Rorze")
    by_title = _project("lg", "LG Display")
    db = _Catalog([by_code, by_title])

    resolved = await resolve_project_from_attribution(
        db, {"post_code": "Rorze", "ad_title": "Tuyển dụng LG Display"}
    )

    assert resolved == str(by_code[0])


@pytest.mark.asyncio
async def test_ad_title_is_the_fallback_when_no_ref_resolves() -> None:
    project = _project("rorze", "Rorze")
    db = _Catalog([project])

    resolved = await resolve_project_from_attribution(
        db, {"post_code": "some-code-nobody-registered", "ad_title": "Tuyển dụng Rorze"}
    )

    assert resolved == str(project[0])


@pytest.mark.asyncio
async def test_an_already_resolved_project_is_never_replaced() -> None:
    resolved_already = _project("rorze", "Rorze")
    other = _project("lg", "LG Display")
    db = _Catalog([resolved_already, other])

    resolved = await resolve_project_from_attribution(
        db, {"project_id": str(resolved_already[0]), "ad_title": "Tuyển dụng LG Display"}
    )

    assert resolved == str(resolved_already[0])


@pytest.mark.asyncio
async def test_blank_and_missing_signals_resolve_to_nothing() -> None:
    db = _Catalog([_project("rorze", "Rorze")])

    assert await resolve_project_from_attribution(db, None) is None
    assert await resolve_project_from_attribution(db, {}) is None
    assert await resolve_project_from_attribution(db, {"kind": "referral"}) is None
    assert (
        await resolve_project_from_attribution(db, {"post_code": "  ", "ad_title": "  "})
        is None
    )


@pytest.mark.asyncio
async def test_post_code_matches_case_and_whitespace_insensitively() -> None:
    project = _project("rorze", "Rorze", ["Công ty Rorze Việt Nam"])
    db = _Catalog([project])

    assert await resolve_project_from_attribution(db, {"post_code": "  RORZE "}) == str(
        project[0]
    )
    assert await resolve_project_from_attribution(
        db, {"post_code": "công ty rorze việt nam"}
    ) == str(project[0])


@pytest.mark.asyncio
async def test_catalog_failure_never_raises_on_the_inbound_path() -> None:
    db = _Catalog(error=RuntimeError("catalog down"))

    assert await resolve_project_from_attribution(db, {"post_code": "rorze"}) is None
    assert await resolve_project_from_attribution(db, {"ad_title": "Rorze"}) is None