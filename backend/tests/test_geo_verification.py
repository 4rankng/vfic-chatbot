"""Unit tests for the containment check and the verified factory resolver.

No network: the HTTP clients are fakes from ``tests.helpers.http_fake``, and the
durable reverse-lookup cache is stubbed at the two module functions that touch
it. The fixtures carry response shapes captured live from Hải Phòng on
2026-10-03, so these cases fail on the real failure modes rather than on
invented payloads.
"""

from __future__ import annotations

import pytest

from app.services.geo import factory_point as factory_point_module
from app.services.geo import gazetteer as gazetteer_module
from app.services.geo import geocoding, verification
from app.services.geo.providers import KEYED_GEO_HOPS, GeocodeHop, google_reverse
from app.services.integration_settings.providers.geo import GeoRuntimeConfig
from tests.helpers.http_fake import FakeHttpClient, register_fake_client

# --- Ground truth, captured live 2026-10-03 ---------------------------------
# OSM tags these parks, so their coordinates are the yardstick:
#   KCN Tràng Duệ, Phường An Phong ....... 20.8619428, 106.5619529
#   KCN VSIP, Phường Nam Triệu ........... 20.9095671, 106.7231804
#   KCN Đình Vũ, Phường Đông Hải ........ 20.8267968, 106.7744652

ADDRESS_4P = (
    "Tầng 2, Công ty LG Electronics (LGE), KCN Tràng Duệ, An Phong, An Dương, Hải Phòng"
)
ADDRESS_AMTRAN = "Công ty AmTRAN, KCN Vsip, Thủy Nguyên, Hải Phòng"
ADDRESS_RORZE = "KCN Nhật Bản (Nomura), Hồng An, Hải Phòng"
ADDRESS_SAMSUNG = "Công ty Cổ phần liên hợp kho bãi UWG, KCN Đình Vũ, Hải Phòng"

# Nominatim reverse for the CORRECT 4P point: the park itself is named.
NOMINATIM_REVERSE_4P_GOOD = {
    "address": {
        "industrial": "Khu công nghiệp Tràng Duệ",
        "suburb": "Phường An Phong",
        "city": "Thành phố Hải Phòng",
    }
}
# Nominatim reverse for the VIETMAP point that is 6.81 km away: a different ward
# entirely, and the only place name in common with the address is the city.
NOMINATIM_REVERSE_4P_BAD = {
    "address": {
        "road": "Quốc lộ 5",
        "suburb": "Phường Hồng An",
        "city": "Thành phố Hải Phòng",
    }
}
# Google reverse for the same correct point — the post-merger ward name, which is
# where OSM is silent. The union of the two sources is what makes the check hold.
GOOGLE_REVERSE_4P_GOOD = {
    "status": "OK",
    "results": [
        {
            "formatted_address": "VH5C+GWJ, An Phong, Hải Phòng, Việt Nam",
            "address_components": [
                {"long_name": "An Phong"},
                {"long_name": "Hải Phòng"},
                {"long_name": "Việt Nam"},
            ],
        }
    ],
}
GOOGLE_REVERSE_4P_BAD = {
    "status": "OK",
    "results": [
        {
            "formatted_address": "Đại Bản, Hồng An, Hải Phòng, Việt Nam",
            "address_components": [
                {"long_name": "Đại Bản"},
                {"long_name": "Hồng An"},
                {"long_name": "Hải Phòng"},
            ],
        }
    ],
}


# --- geographic_tail ---------------------------------------------------------


def test_geographic_tail_strips_a_floor_and_a_company_and_keeps_the_hierarchy():
    assert verification.geographic_tail(ADDRESS_4P) == (
        "KCN Tràng Duệ, An Phong, An Dương, Hải Phòng"
    )


def test_geographic_tail_returns_an_already_geographic_address_unchanged():
    address = "KCN Đình Vũ, Hải Phòng"
    assert verification.geographic_tail(address) == address


def test_geographic_tail_keeps_everything_after_the_first_place_component():
    """Stopping at the first NON-organisation component is what keeps a proper
    noun safe: "An Dương" contains the same characters as "đường" and any
    lexical 'looks like a place' test would mis-handle it."""
    assert verification.geographic_tail(ADDRESS_RORZE) == ADDRESS_RORZE


# --- place_anchors -----------------------------------------------------------


def test_place_anchors_drops_the_city_which_matches_everything_in_the_city():
    """Kept, the city would admit the 10 km-off centroid that caused the
    incident — every point in Hải Phòng reports it."""
    anchors = verification.place_anchors(ADDRESS_4P)
    assert "hai phong" not in anchors
    assert "trang due" in anchors  # the KCN abbreviation is expanded away
    assert "an phong" in anchors  # the ward that actually distinguishes it


def test_place_anchors_keeps_a_ward_that_carries_no_marker_word():
    """`Hồng An` names no kind of place, only a place. A closed vocabulary would
    drop it and leave Rorze unverifiable."""
    assert "hong an" in verification.place_anchors(ADDRESS_RORZE)


def test_place_anchors_is_empty_for_a_single_component_address():
    """A bare city cannot justify a factory point — that is the incident."""
    assert verification.place_anchors("Hải Phòng") == ()


def test_place_anchors_drops_organisation_components():
    anchors = verification.place_anchors(ADDRESS_4P)
    assert not any("cong ty" in anchor for anchor in anchors)
    assert not any("tang" in anchor for anchor in anchors)


# --- place_matches -----------------------------------------------------------


def test_place_matches_uses_whole_names_not_a_bag_of_words():
    """The regression that matters: "an phong" must not match a point whose
    reported names are "Hồng An" and "Hải Phòng" — one word from each."""
    names = frozenset({"quoc lo 5", "phuong hong an", "thanh pho hai phong"})
    assert verification.place_matches(names, "an phong") is False
    assert verification.place_matches(names, "hong an") is True


def test_place_matches_expands_the_kcn_abbreviation():
    """OSM writes "Khu Công Nghiệp Đình Vũ" for what the address calls
    "KCN Đình Vũ"."""
    names = frozenset({"khu cong nghiep dinh vu", "phuong dong hai"})
    assert verification.place_matches(names, "dinh vu") is True


def test_place_matches_matches_whole_words_only():
    """A fragment is not a word: "ong" must not be found inside "phong", or a
    partial overlap would read as a confirmed place."""
    names = frozenset({"phuong an phong"})
    assert verification.place_matches(names, "ong") is False
    assert verification.place_matches(names, "phong") is True
    assert verification.place_matches(names, "an phong") is True
    # Both words of a two-word anchor must appear in the SAME reported name.
    split = frozenset({"phuong an", "thanh pho hai phong"})
    assert verification.place_matches(split, "an phong") is False


def test_place_matches_rejects_a_composite_that_mixes_two_places():
    """A composite string's words are a bag, so two DIFFERENT places inside one
    name satisfy an anchor built from both — "an" from "Đại Bản" and "phong"
    from "Hải Phòng" are enough for "an phong".

    Pinned deliberately, because it is the mechanism behind the defect: at this
    layer a composite is indistinguishable from a genuine "Phường An Phong", so
    the comma split in ``google_reverse`` is the only thing standing between
    "Đại Bản, Hồng An, Hải Phòng, Việt Nam" and a false match. Split into one
    name per place, the same set matches nothing.
    """
    composite = frozenset({"dai ban hong an hai phong viet nam"})
    assert verification.place_matches(composite, "an phong") is True
    split = frozenset({"dai ban", "hong an", "hai phong", "viet nam"})
    assert verification.place_matches(split, "an phong") is False


# --- google_reverse: the formatted address is a composite, not a name --------


COMPOSITE_FORMATTED_ADDRESS = {
    "status": "OK",
    "results": [
        {
            "formatted_address": "Đại Bản, Hồng An, Hải Phòng, Việt Nam",
            "address_components": [{"long_name": "Hồng An"}],
        }
    ],
}


@pytest.mark.asyncio
async def test_google_reverse_splits_the_formatted_address():
    """One string can name several places, so it must never become ONE name.

    Stored whole, the composite is a bag of words in which the anchor "an
    phong" matches — which is how both the 6.81 km Vietmap error and the city
    centroid got through the containment check. Each comma-separated segment is
    added as its own name instead, so no member mixes two places, while
    ``KCN Đình Vũ`` stays usable because it is its own segment.
    """
    register_fake_client(
        "geocoder-google",
        FakeHttpClient(side_effect=lambda _request: COMPOSITE_FORMATTED_ADDRESS),
    )

    names = await google_reverse(20.9, 106.5, api_key="gk")

    assert names is not None
    assert {"dai ban", "hong an", "hai phong", "viet nam"} <= names
    # No member holds the words of two different places.
    assert not any({"an", "phong"} <= set(name.split()) for name in names)
    assert verification.place_matches(names, "an phong") is False
    assert verification.place_matches(names, "hong an") is True


# --- the durable reverse cache ----------------------------------------------


@pytest.mark.asyncio
async def test_cached_names_round_trips_whole_names(monkeypatch):
    """Storing space-joined and reading back with split() turned every reported
    name into single words, after which no multi-word anchor could ever match
    again — so every project would go silent on the second resolution. One name
    per line is what keeps the boundary."""
    stored: dict[str, str] = {}

    async def fake_store(point, names):
        stored[verification.coord_key(point)] = "\n".join(sorted(names))

    async def fake_lookup(point):
        value = stored.get(verification.coord_key(point))
        if value is None:
            return None
        return frozenset(line for line in value.split("\n") if line)

    monkeypatch.setattr(verification, "_store_names", fake_store)
    monkeypatch.setattr(verification, "_cached_names", fake_lookup)

    point = (20.858837, 106.572268)
    await verification._store_names(point, frozenset({"phuong an phong", "hai phong"}))
    reloaded = await verification._cached_names(point)

    assert reloaded == frozenset({"phuong an phong", "hai phong"})
    assert verification.place_matches(reloaded, "an phong") is True


@pytest.mark.asyncio
async def test_cached_names_separates_a_row_from_a_missing_one(monkeypatch):
    monkeypatch.setattr(verification, "_cached_names", _no_cache)
    result = await verification._cached_names((1.0, 2.0))
    assert result is None


def test_coord_key_is_versioned():
    """The stored answer is the union of whatever reverse sources were
    configured under the parsing rules of the day, so the key carries the
    version — the same retirement trick ``geocoding._DB_KEY_VERSION`` uses, and
    for the same reason: a row written before the sources or the parsing changed
    no longer means the same thing. No data migration; the column is opaque
    text."""
    assert verification.coord_key((20.85884, 106.57227)) == "v6:20.85884,106.57227"


async def _never():  # pragma: no cover - only reached on an unexpected call
    raise AssertionError("should not be called")


async def _no_cache(_point):
    """No durable row for this point, so the lookup goes to the network."""
    return None


async def _no_store(_point, _names):
    """Accept the row without persisting it."""


# --- check_point: the union of both reverse sources --------------------------


@pytest.mark.asyncio
async def test_check_point_accepts_on_either_reverse_source(monkeypatch):
    """Nominatim names the park, Google names the post-merger ward. Either alone
    can be silent about the thing the address used, so the union is what holds."""

    async def nominatim_only(*_args, **_kwargs):
        return frozenset({"khu cong nghiep trang due", "phuong an phong"})

    async def never_called(*_args, **_kwargs):  # pragma: no cover
        raise AssertionError("only the stubbed source should be consulted")

    monkeypatch.setattr(verification, "_cached_names", _no_cache)
    monkeypatch.setattr(verification, "_store_names", _no_store)
    monkeypatch.setattr(verification, "nominatim_reverse", nominatim_only)
    monkeypatch.setattr(verification, "google_reverse", never_called)

    check = await verification.check_point(
        (20.858837, 106.572268),
        verification.place_anchors(ADDRESS_4P),
        providers=GeoRuntimeConfig(google_maps_api_key="k"),
    )

    assert check is not None
    assert check.matched == "trang due"


@pytest.mark.asyncio
async def test_check_point_rejects_the_6_81_km_error(monkeypatch):
    """The whole reason this module exists: the wrong point is a confident,
    well-formed coordinate in a ward the address never mentions."""

    async def wrong_place(*_args, **_kwargs):
        return frozenset({"quoc lo 5", "phuong hong an", "thanh pho hai phong"})

    monkeypatch.setattr(verification, "_cached_names", _no_cache)
    monkeypatch.setattr(verification, "_store_names", _no_store)
    monkeypatch.setattr(verification, "nominatim_reverse", wrong_place)
    monkeypatch.setattr(verification, "google_reverse", wrong_place)

    check = await verification.check_point(
        (20.923086, 106.559131),
        verification.place_anchors(ADDRESS_4P),
        providers=GeoRuntimeConfig(google_maps_api_key="k"),
    )

    assert check is not None
    assert check.matched is None


@pytest.mark.asyncio
async def test_check_point_decides_nothing_when_every_source_fails(monkeypatch):
    """Distinct from a rejection: an unlooked-up point is retried, not denied."""
    monkeypatch.setattr(verification, "_cached_names", _no_cache)
    monkeypatch.setattr(verification, "_store_names", _no_store)
    monkeypatch.setattr(verification, "nominatim_reverse", lambda *a, **k: _never())
    monkeypatch.setattr(verification, "google_reverse", lambda *a, **k: _never())

    assert (
        await verification.check_point(
            (20.9, 106.7), verification.place_anchors(ADDRESS_4P),
            providers=GeoRuntimeConfig(google_maps_api_key="k"),
        )
        is None
    )


@pytest.mark.asyncio
async def test_check_point_refuses_an_address_with_no_anchors():
    assert await verification.check_point((20.9, 106.7), ()) is None


# --- the gazetteer -----------------------------------------------------------


def test_gazetteer_matching_is_token_subset_not_substring():
    words = frozenset(verification.place_tokens("KCN Tràng Duệ, An Phong, An Dương"))
    assert frozenset(verification.place_tokens("KCN Tràng Duệ")) <= words
    assert not frozenset(verification.place_tokens("KCN Đình Vũ")) <= words
    assert not frozenset(verification.place_tokens("An Dương")) <= frozenset(
        verification.place_tokens("An Phong")
    )


@pytest.mark.asyncio
async def test_gazetteer_returns_none_when_nothing_matches(monkeypatch):
    monkeypatch.setattr(gazetteer_module, "async_session", _empty_session_factory([]))
    assert await gazetteer_module.lookup(ADDRESS_4P) is None


def _empty_session_factory(rows):
    class _Result:
        def scalars(self):
            return self

        def all(self):
            return rows

    class _Session:
        async def __aenter__(self_inner):
            return self_inner

        async def __aexit__(self_inner, *_exc):
            return False

        async def execute(self_inner, _stmt):
            return _Result()

    return lambda: _Session()


# --- hop order ---------------------------------------------------------------


def test_google_is_the_first_hop_and_vietmap_the_fallback():
    names = [hop.name for hop in KEYED_GEO_HOPS]
    assert names == ["google", "vietmap"]
    assert isinstance(KEYED_GEO_HOPS[0], GeocodeHop)


def test_every_hop_names_a_credential_field_that_exists():
    for hop in KEYED_GEO_HOPS:
        assert hasattr(GeoRuntimeConfig(), hop.key_field)


# --- resolve_factory_point ---------------------------------------------------


def _stub_gaetteer_empty(monkeypatch):
    async def no_hit(_address):
        return None

    monkeypatch.setattr(factory_point_module, "gazetteer_lookup", no_hit)


@pytest.mark.asyncio
async def test_resolve_returns_none_when_a_verified_candidate_cannot_be_found(monkeypatch):
    _stub_gaetteer_empty(monkeypatch)

    async def one_candidate(query, **_kwargs):
        return (20.923086, 106.559131)  # the 6.81 km-off point, whatever the text

    for name in ("google_geocode", "vietmap_geocode"):
        monkeypatch.setattr(factory_point_module, name, one_candidate, raising=False)
    monkeypatch.setattr(factory_point_module, "geocode", one_candidate)
    monkeypatch.setattr(factory_point_module, "check_point", _reject_all)
    monkeypatch.setattr(factory_point_module, "KEYED_GEO_HOPS", _fake_hops())

    result = await factory_point_module.resolve_factory_point(
        ADDRESS_4P, providers=GeoRuntimeConfig(google_maps_api_key="k")
    )

    assert result is None


async def _reject_all(_point, _anchors, **_kwargs):
    return verification.PlaceCheck(point=(0.0, 0.0), matched=None, names=frozenset())


def _fake_hops():
    async def fetch(_query, *, api_key, **_kwargs):
        return (20.923086, 106.559131)

    return (GeocodeHop("google", "google_maps_api_key", fetch),)


@pytest.mark.asyncio
async def test_resolve_returns_the_first_verified_candidate_in_hop_order(monkeypatch):
    _stub_gaetteer_empty(monkeypatch)
    monkeypatch.setattr(factory_point_module, "KEYED_GEO_HOPS", _fake_hops())
    monkeypatch.setattr(factory_point_module, "geocode", lambda *a, **k: _never())
    monkeypatch.setattr(factory_point_module, "check_point", _accept_all)

    result = await factory_point_module.resolve_factory_point(
        ADDRESS_4P, providers=GeoRuntimeConfig(google_maps_api_key="k")
    )

    assert result is not None
    assert result.provider == "google"
    assert result.matched_anchor == "trang due"


async def _accept_all(point, anchors, **_kwargs):
    return verification.PlaceCheck(point=point, matched="trang due", names=frozenset())


@pytest.mark.asyncio
async def test_resolve_prefers_the_gazetteer_over_a_verified_provider(monkeypatch):
    """A human-asserted coordinate costs no API call and is not re-litigated.

    The row IS the verification, so the seeded coordinate is returned verbatim
    and not one provider request is made — not even a reverse lookup to check a
    point nobody disputed.
    """

    async def hit(_address):
        return gazetteer_module.GazetteerHit(
            point=(20.8619428, 106.5619529), name="KCN Tràng Duệ", source="osm"
        )

    async def must_not_run(*_a, **_k):  # pragma: no cover
        raise AssertionError("a gazetteer hit must short-circuit every provider")

    monkeypatch.setattr(factory_point_module, "gazetteer_lookup", hit)
    monkeypatch.setattr(factory_point_module, "KEYED_GEO_HOPS", _fake_hops())
    monkeypatch.setattr(factory_point_module, "geocode", must_not_run)
    google = register_fake_client("geocoder-google", FakeHttpClient(responses=[]))
    vietmap = register_fake_client("geocoder-vietmap", FakeHttpClient(responses=[]))
    nominatim = register_fake_client("geocoder", FakeHttpClient(responses=[]))

    result = await factory_point_module.resolve_factory_point(
        ADDRESS_4P, providers=GeoRuntimeConfig(google_maps_api_key="k")
    )

    assert result is not None
    assert result.point == (20.8619428, 106.5619529)
    assert result.provider == "gazetteer:osm"
    assert result.matched_anchor == "KCN Tràng Duệ"
    assert google.calls == [] and vietmap.calls == [] and nominatim.calls == []


@pytest.mark.asyncio
async def test_resolve_of_a_blank_address_is_none_without_any_call(monkeypatch):
    monkeypatch.setattr(
        factory_point_module, "gazetteer_lookup", lambda *a, **k: _never()
    )
    assert await factory_point_module.resolve_factory_point("   ", providers=None) is None


# --- payload shapes the fakes must be able to carry --------------------------


def test_google_reverse_payload_shape_is_understood():
    """Guards the fixture itself: if Google's response shape changes, the
    verification fixtures silently stop proving anything."""
    payload = GOOGLE_REVERSE_4P_GOOD
    assert payload["status"] == "OK"
    assert payload["results"][0]["address_components"][0]["long_name"] == "An Phong"


def test_nominatim_reverse_payload_shape_is_understood():
    assert NOMINATIM_REVERSE_4P_GOOD["address"]["industrial"] == "Khu công nghiệp Tràng Duệ"
    assert NOMINATIM_REVERSE_4P_BAD["address"]["suburb"] == "Phường Hồng An"


def test_fake_http_client_is_wired_for_all_three_provider_names():
    for name in ("geocoder", "geocoder-google", "geocoder-vietmap"):
        register_fake_client(name, FakeHttpClient(responses=[[]]))


# --- End-to-end through the real provider adapters ---------------------------
#
# The cases above stub the provider coroutines. These do not: they drive the
# real `google_geocode` / `vietmap_geocode` / `nominatim_reverse` adapters over
# the fake HTTP harness, with payloads captured live from Hải Phòng, so the hop
# order, the reverse union and the containment rule are all exercised through the
# code that actually runs in production.

PROVIDERS = GeoRuntimeConfig(vietmap_api_key="vk", google_maps_api_key="gk")


def _google_geocode_payload(lat, lng, formatted="Hải Phòng, Việt Nam"):
    return {
        "status": "OK",
        "results": [
            {
                "formatted_address": formatted,
                "geometry": {"location": {"lat": lat, "lng": lng}},
                "address_components": [{"long_name": formatted.split(",")[0]}],
            }
        ],
    }


def _vietmap_payloads(lat, lng):
    """Vietmap is two calls: search yields a ref_id, place resolves it."""
    return [{"ref_id": "geocode:x"}], {"lat": lat, "lng": lng}


class _E2ESettings:
    """The Settings subset the geocoding client reads."""

    geocoder_enabled = True
    geocoder_base_url = "https://nominatim.example"
    geocoder_user_agent = "tingting-crm-test/1.0"
    geocoder_timeout_seconds = 3.0
    geocoder_cache_ttl_seconds = 2_592_000
    geocoder_negative_ttl_seconds = 21_600
    geocoder_min_interval_seconds = 0.0


async def _none_pair(_query):
    return None, False


async def _none_value(_key):
    return None


async def _no_store_any(*_args, **_kwargs):
    """`_db_store` and `cache_set_json` have different arities; ignore both."""


@pytest.fixture
def no_reverse_db(monkeypatch):
    """The end-to-end cases exercise the HTTP path, not the durable cache.

    Left real, ``_cached_names`` opens the application's asyncpg pool, which
    belongs to a different event loop than the test's — a pool error that looks
    like a product failure and is not one.
    """
    monkeypatch.setattr(verification, "_cached_names", _no_cache)
    monkeypatch.setattr(verification, "_store_names", _no_store)
    # `geocode()` also persists (durable map + Redis) and reads Settings. Those
    # are storage concerns with their own tests; here they would open a real
    # pool and a real client against a different event loop.
    monkeypatch.setattr(geocoding, "_db_lookup", _none_pair)
    monkeypatch.setattr(geocoding, "_db_store", _no_store_any)
    monkeypatch.setattr(geocoding, "cache_get_json", _none_value)
    monkeypatch.setattr(geocoding, "cache_set_json", _no_store_any)
    monkeypatch.setattr(geocoding, "get_settings", lambda: _E2ESettings())


def _ladder(queued: list):
    """A Nominatim search payload source: consume the queue, then keep the last.

    The ladder's attempt count is not fixed (``geocode`` walks up to
    ``_MAX_QUERY_ATTEMPTS`` relaxations), so the fake must not run out and fall
    back to a wrong-shaped default — it repeats its final payload instead.
    """
    return lambda: queued.pop(0) if len(queued) > 1 else queued[0]


def _register_all(
    *,
    google_geo=None,
    vietmap_lat_lng=(1.0, 2.0),
    nominatim_search=None,
    nominatim_reverse_payloads=None,
    google_reverse_payload=None,
):
    """Wire all three providers, routing each fake on the REQUEST it receives.

    Every client serves more than one endpoint: Google's forward and reverse
    both hit ``/maps/api/geocode/json`` (``address`` vs ``latlng``), Vietmap's
    two-step lookup hits ``/api/search/v4`` then ``/api/place/v4``, and the
    shared ``geocoder`` client serves the Nominatim ladder (``/search``) and the
    reverse verification (``/reverse``). A positional queue therefore
    desynchronises the moment the number of ladder attempts changes, and hands a
    forward payload to a reverse call — which fails as "no names", i.e. as a
    product bug that is not one. Routing on the request removes the coupling.
    """
    forward_google = (
        google_geo
        if google_geo is not None
        else {"status": "ZERO_RESULTS", "results": []}
    )
    reverse_google = (
        google_reverse_payload
        if google_reverse_payload is not None
        else {"status": "ZERO_RESULTS", "results": []}
    )
    register_fake_client(
        "geocoder-google",
        FakeHttpClient(
            side_effect=lambda request: (
                reverse_google
                if "latlng" in (request.get("params") or {})
                else forward_google
            )
        ),
    )
    search, place = _vietmap_payloads(*vietmap_lat_lng)
    register_fake_client(
        "geocoder-vietmap",
        FakeHttpClient(
            side_effect=lambda request: (
                place if request["url"].endswith("/api/place/v4") else search
            )
        ),
    )
    ladder = _ladder(list(nominatim_search) if nominatim_search else [[]])
    reverse_payload = (
        nominatim_reverse_payloads[0] if nominatim_reverse_payloads else {}
    )
    register_fake_client(
        "geocoder",
        FakeHttpClient(
            side_effect=lambda request: (
                reverse_payload if request["url"] == "/reverse" else ladder()
            )
        ),
    )


@pytest.mark.asyncio
async def test_end_to_end_google_point_is_verified_and_kept(monkeypatch, no_reverse_db):
    """The real 4P scenario: Google puts the plant at the park, the reverse
    lookup confirms the park name, and the resolver returns that point."""
    _stub_gaetteer_empty(monkeypatch)
    _register_all(
        google_geo=_google_geocode_payload(20.858837, 106.572268),
        google_reverse_payload=GOOGLE_REVERSE_4P_GOOD,
        nominatim_reverse_payloads=[NOMINATIM_REVERSE_4P_GOOD],
    )

    point = await factory_point_module.resolve_factory_point(ADDRESS_4P, providers=PROVIDERS)

    assert point is not None
    assert round(point.point[0], 4) == 20.8588
    assert round(point.point[1], 4) == 106.5723
    assert point.provider == "google"


@pytest.mark.asyncio
async def test_end_to_end_the_vietmap_error_is_rejected(monkeypatch, no_reverse_db):
    """Google is unreachable, Vietmap answers — and answers with the 6.81 km-off
    point. Containment must reject it, so the factory gets no coordinates rather
    than a confident wrong one. This is the incident, as a test.

    The REASON is asserted, not just the outcome. ``point is None`` alone would
    also pass if the candidate had never been collected, or if the fakes had run
    out of payloads and answered "nothing" — so the Vietmap point must be
    observed reaching ``check_point`` and being refused there, by containment
    rather than by an unlooked-up point.
    """
    _stub_gaetteer_empty(monkeypatch)
    _register_all(
        google_geo={"status": "OVER_QUERY_LIMIT", "results": []},
        vietmap_lat_lng=(20.923086, 106.559131),
        nominatim_reverse_payloads=[NOMINATIM_REVERSE_4P_BAD],
        google_reverse_payload=GOOGLE_REVERSE_4P_BAD,
    )
    checked: list[tuple[tuple[float, float], str | None]] = []

    async def spy_check_point(point, anchors, *, providers=None):
        check = await verification.check_point(point, anchors, providers=providers)
        checked.append((point, "unlooked" if check is None else check.matched))
        return check

    monkeypatch.setattr(factory_point_module, "check_point", spy_check_point)

    point = await factory_point_module.resolve_factory_point(ADDRESS_4P, providers=PROVIDERS)

    assert point is None
    # The wrong point was a candidate, and containment is what killed it.
    assert checked == [((20.923086, 106.559131), None)]


@pytest.mark.asyncio
async def test_end_to_end_vietmap_is_used_when_google_cannot_answer(monkeypatch, no_reverse_db):
    """The fallback earns its place: with Google down, a Vietmap answer that
    VERIFIES is still a good answer."""
    _stub_gaetteer_empty(monkeypatch)
    _register_all(
        google_geo={"status": "OVER_QUERY_LIMIT", "results": []},
        vietmap_lat_lng=(20.8619428, 106.5619529),
        nominatim_reverse_payloads=[NOMINATIM_REVERSE_4P_GOOD],
    )

    point = await factory_point_module.resolve_factory_point(ADDRESS_4P, providers=PROVIDERS)

    assert point is not None
    assert point.provider == "vietmap"
    assert round(point.point[0], 4) == 20.8619


@pytest.mark.asyncio
async def test_end_to_end_gazetteer_short_circuits_without_any_http(monkeypatch):
    """No API call may be made when a human has already verified the place."""

    async def hit(_address):
        return gazetteer_module.GazetteerHit(
            point=(20.8619428, 106.5619529), name="KCN Tràng Duệ", source="osm"
        )

    monkeypatch.setattr(factory_point_module, "gazetteer_lookup", hit)
    google = register_fake_client("geocoder-google", FakeHttpClient(responses=[]))
    vietmap = register_fake_client("geocoder-vietmap", FakeHttpClient(responses=[]))
    nominatim = register_fake_client("geocoder", FakeHttpClient(responses=[]))

    point = await factory_point_module.resolve_factory_point(ADDRESS_4P, providers=PROVIDERS)

    assert point is not None
    assert point.provider == "gazetteer:osm"
    assert google.calls == [] and vietmap.calls == [] and nominatim.calls == []


@pytest.mark.asyncio
async def test_end_to_end_the_city_centroid_can_never_be_returned(monkeypatch, no_reverse_db):
    """Nominatim alone answering with the Hải Phòng centroid — the exact value
    that produced "1.5 km" — must not survive resolution."""
    _stub_gaetteer_empty(monkeypatch)
    _register_all(
        google_geo={"status": "ZERO_RESULTS", "results": []},
        vietmap_lat_lng=(1.0, 2.0),
        nominatim_search=[{"lat": "20.8830967", "lon": "106.6790381", "addresstype": "city"}],
        nominatim_reverse_payloads=[
            {"address": {"city": "Thành phố Hải Phòng"}}
        ],
    )

    point = await factory_point_module.resolve_factory_point(ADDRESS_4P, providers=PROVIDERS)

    assert point is None


@pytest.mark.asyncio
async def test_end_to_end_the_city_centroid_is_rejected_by_the_google_source(
    monkeypatch, no_reverse_db
):
    """The 2026-10-03 value, with GOOGLE as the source this time.

    Google's forward geocode answers the 4P address with the city centroid
    (20.8830967, 106.6790381) and its reverse reports the composite "Phường An
    Biên, Quận Lê Chân, Hải Phòng, Việt Nam"; Nominatim reports only "Thành phố
    Hải Phòng". None of those is a place the address names, so the point that
    produced "1.5 km" must never come back. With the composite stored whole, the
    anchor "an phong" matched inside it — the ward name "An Phong" pulled out of
    "Hải Phòng" plus the "an" of "An Biên" — and this returned a coordinate.
    """
    _stub_gaetteer_empty(monkeypatch)
    _register_all(
        google_geo=_google_geocode_payload(20.8830967, 106.6790381),
        google_reverse_payload={
            "status": "OK",
            "results": [
                {
                    "formatted_address": "Phường An Biên, Quận Lê Chân, Hải Phòng, Việt Nam",
                    "address_components": [
                        {"long_name": "Phường An Biên"},
                        {"long_name": "Hải Phòng"},
                    ],
                }
            ],
        },
        nominatim_reverse_payloads=[{"address": {"city": "Thành phố Hải Phòng"}}],
    )

    point = await factory_point_module.resolve_factory_point(ADDRESS_4P, providers=PROVIDERS)

    assert point is None
