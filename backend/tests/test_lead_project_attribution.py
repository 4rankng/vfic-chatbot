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

@pytest.mark.asyncio
async def test_ad_id_resolves_through_the_project_aliases() -> None:
    """Meta's own ad id is curated into a project's aliases, so an ad that sets
    no ``ref`` still names its project.

    This is the live LG-DISPLAY case: the ads running today carry Meta's asset
    name ("album_xanh") as their title, so title matching cannot resolve them.
    """
    project = _project("lg-display", "LG-DISPLAY", ["LGD", "120255397858310496"])
    db = _Catalog([project])

    resolved = await resolve_project_from_attribution(
        db, {"ad_id": "120255397858310496", "ad_title": "album_xanh"}
    )

    assert resolved == str(project[0])


@pytest.mark.asyncio
async def test_an_unmapped_ad_id_falls_through_to_the_title() -> None:
    """An ad id nobody curated must not block a title that does resolve."""
    project = _project("rorze", "Rorze")
    db = _Catalog([project])

    resolved = await resolve_project_from_attribution(
        db, {"ad_id": "120255327713950496", "ad_title": "Tuyển dụng Rorze"}
    )

    assert resolved == str(project[0])


@pytest.mark.asyncio
async def test_an_unmapped_ad_id_and_an_asset_name_resolve_to_nothing() -> None:
    """Neither signal names a project — the ad stays unattributed rather than
    being guessed onto one. The digest prints the ad id itself in that case."""
    db = _Catalog([_project("lg-display", "LG-DISPLAY", ["LGD"])])

    assert (
        await resolve_project_from_attribution(
            db, {"ad_id": "120255327713950496", "ad_title": "album_xanh"}
        )
        is None
    )


@pytest.mark.asyncio
async def test_ref_still_outranks_a_curated_ad_id() -> None:
    """``ref`` is the field an ad is written for; it wins outright."""
    by_ref = _project("rorze", "Rorze")
    by_ad = _project("lg-display", "LG-DISPLAY", ["120255397858310496"])
    db = _Catalog([by_ref, by_ad])

    resolved = await resolve_project_from_attribution(
        db, {"post_code": "Rorze", "ad_id": "120255397858310496"}
    )

    assert resolved == str(by_ref[0])


def test_the_ad_mapping_migration_is_additive_and_idempotent() -> None:
    """The mapping lives in project aliases: appending can never overwrite an
    operator's own alias, and the guard keeps a replay from duplicating it."""
    import importlib.util
    from pathlib import Path

    migration_path = (
        Path(__file__).resolve().parents[1]
        / "alembic"
        / "versions"
        / "0073_map_lgd_messenger_ad.py"
    )
    spec = importlib.util.spec_from_file_location("map_0073", migration_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert module.MESSENGER_AD_ID == "120255397858310496"
    assert module.PROJECT_SLUG == "lg-display"
    assert module.down_revision == "0072_tingting_hotline_number"

    captured: list[str] = []
    real_execute = module.op.execute
    module.op.execute = lambda sql: captured.append(str(sql))
    try:
        module.upgrade()
        module.downgrade()
    finally:
        module.op.execute = real_execute
    add, remove = captured

    assert "array_append" in add  # additive: an operator alias survives
    assert "NOT (" in add and "@>" in add  # idempotent: no duplicate on replay
    assert "array_remove" in remove  # downgrade drops only what it added
    assert "120255397858310496" in add and "120255397858310496" in remove


def test_the_ten_du_an_migration_is_idempotent_and_non_destructive() -> None:
    """The catch-all project is inserted only when absent and each ad id is
    appended only when missing, so a replay duplicates nothing and an operator's
    own aliases survive. Downgrade removes only the ad ids — deleting a project
    that may have gained a knowledge base would be destructive."""
    import importlib.util
    from pathlib import Path

    migration_path = (
        Path(__file__).resolve().parents[1]
        / "alembic"
        / "versions"
        / "0074_ten_du_an_project.py"
    )
    spec = importlib.util.spec_from_file_location("ten_du_an_0074", migration_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert module.PROJECT_NAME == "Ten Du An"
    assert module.PROJECT_SLUG == "du-an-muoi"
    assert module.down_revision == "0073_map_lgd_messenger_ad"
    assert len(module.MESSENGER_AD_IDS) == 5
    assert len(set(module.MESSENGER_AD_IDS)) == len(module.MESSENGER_AD_IDS)
    assert "120255397858310496" not in module.MESSENGER_AD_IDS  # that is LG-DISPLAY

    captured: list[str] = []
    real_execute = module.op.execute
    module.op.execute = lambda sql: captured.append(str(sql))
    try:
        module.upgrade()
        module.downgrade()
    finally:
        module.op.execute = real_execute
    insert, add, remove = captured

    assert "INSERT INTO public.projects" in insert
    assert "WHERE NOT EXISTS" in insert  # an existing project is never replaced
    assert "Ten Du An" in insert and "du-an-muoi" in insert
    # Appends only what is missing, and skips the write when nothing is.
    assert "@>" in add
    assert "m.ids <> ARRAY[]::text[]" in add
    for ad_id in module.MESSENGER_AD_IDS:
        assert ad_id in add
        assert ad_id in remove
    assert "array_agg(value)" in remove  # rebuilds the array minus these ids
    assert "DELETE" not in remove  # the project itself is never dropped


@pytest.mark.asyncio
async def test_the_catch_all_does_not_swallow_an_unmapped_future_ad() -> None:
    """A new ad that matches nothing must stay visibly unmapped.

    Filing it silently into the catch-all would hide the fact that no one has
    mapped it, and the digest would stop printing the very id an operator needs
    in order to map it. The catch-all is a curated list, not a wildcard.
    """
    project = _project("du-an-muoi", "Ten Du An", ["Dự án Mười"])
    db = _Catalog([project])

    assert (
        await resolve_project_from_attribution(
            db, {"ad_id": "120255999999999999", "ad_title": "album_xanh"}
        )
        is None
    )
