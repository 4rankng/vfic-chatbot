"""Unit tests for the keyed geocoding client and the haversine helper.

No network: each hop's httpx client comes from the process-scoped registry, so a
``FakeHttpClient`` is injected under its provider name. The cache is an in-memory
dict so TTLs and hit/miss behavior are observable.

The chain under test is Google then Vietmap, on the caller's exact text. There is
no keyless provider and no relaxation ladder any more (Nominatim was removed
2026-10-03), so the cases that used to pin ladder behaviour — how many variants
were tried, which ``addresstype`` was refused, how the throttle spaced calls —
are gone with the code. What replaces them pins the invariant that made the
ladder unacceptable in the first place: a hop is asked once, with the verbatim
query, and a coarse answer is refused rather than stored.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.recruitment.domain.recommendation import haversine_km
from app.services.geo import geocoding
from app.services.integration_settings.providers.geo import GeoRuntimeConfig
from tests.helpers.http_fake import FakeHttpClient, register_fake_client


class _Settings:
    """The subset of Settings the geocoding client reads."""

    geocoder_enabled = True
    geocoder_timeout_seconds = 3.0
    geocoder_cache_ttl_seconds = 2_592_000
    geocoder_negative_ttl_seconds = 21_600


class _Cache:
    def __init__(self) -> None:
        self.data: dict[str, Any] = {}
        self.writes: list[tuple[str, Any, int]] = []


@pytest.fixture
def geo_env(monkeypatch):
    """Fake settings + in-memory cache + a durable mapping that always misses."""
    cache = _Cache()
    settings = _Settings()

    async def _get(key: str) -> Any:
        return cache.data.get(key)

    async def _set(key: str, value: Any, ttl_seconds: int) -> None:
        cache.data[key] = value
        cache.writes.append((key, value, ttl_seconds))

    monkeypatch.setattr(geocoding, "get_settings", lambda: settings)
    monkeypatch.setattr(geocoding, "cache_get_json", _get)
    monkeypatch.setattr(geocoding, "cache_set_json", _set)

    async def _noop_lookup(_query):
        return None, False

    async def _noop_store(_query, _coords, _provider):
        return None

    monkeypatch.setattr(geocoding, "_db_lookup", _noop_lookup)
    monkeypatch.setattr(geocoding, "_db_store", _noop_store)
    return cache, settings


def _google_payload(lat: float, lng: float, types: list[str] | None = None) -> dict:
    """A Google Geocoding response with one result, as the API returns it."""
    return {
        "status": "OK",
        "results": [
            {
                "geometry": {"location": {"lat": lat, "lng": lng}},
                "types": types if types is not None else ["street_address", "premise"],
            }
        ],
    }


def _register_google(
    payload: Any = None,
    *,
    status: int = 200,
    side_effect: BaseException | None = None,
):
    return register_fake_client(
        "geocoder-google",
        FakeHttpClient(
            responses=[payload] if payload is not None else None,
            status_codes=[status],
            side_effect=side_effect,
        ),
    )


def _register_vietmap(
    *,
    search_payload: Any = None,
    place_payload: Any = None,
    status_codes: list[int] | None = None,
    side_effect: BaseException | None = None,
):
    """Register the fake ``geocoder-vietmap`` client.

    Vietmap needs two calls (search yields a ``ref_id``, place resolves it), so
    a resolving client needs two canned responses in order.
    """
    responses = []
    if search_payload is not None:
        responses.append(search_payload)
    if place_payload is not None:
        responses.append(place_payload)
    return register_fake_client(
        "geocoder-vietmap",
        FakeHttpClient(responses=responses, status_codes=status_codes, side_effect=side_effect),
    )


def _vietmap_hit(lat: float = 10.8, lng: float = 106.7):
    return _register_vietmap(
        search_payload=[{"ref_id": "geocode:x"}], place_payload={"lat": lat, "lng": lng}
    )


def _google_miss():
    return _register_google({"status": "ZERO_RESULTS", "results": []})


# --- the cache, the switch, and the empty query -------------------------------


@pytest.mark.asyncio
async def test_geocode_caches_a_hop_hit_under_the_normalized_query(geo_env):
    cache, _settings = geo_env
    fake = _register_google(_google_payload(20.865, 106.683))

    assert await geocoding.geocode(
        "KCN Tràng Duệ, An Dương", providers=GeoRuntimeConfig(google_maps_api_key="k")
    ) == (20.865, 106.683)

    assert fake.calls[0]["url"] == "/maps/api/geocode/json"
    assert fake.calls[0]["params"]["address"] == "KCN Tràng Duệ, An Dương"
    key, value, ttl = cache.writes[-1]
    assert key.startswith("geo:geocode:v8:")
    assert value == {"lat": 20.865, "lng": 106.683}
    assert ttl == 2_592_000


@pytest.mark.asyncio
async def test_geocode_warm_cache_skips_http(geo_env):
    cache, _settings = geo_env
    fake = _register_google(_google_payload(20.0, 106.0))
    providers = GeoRuntimeConfig(google_maps_api_key="k")
    await geocoding.geocode("Hải Phòng", providers=providers)
    await geocoding.geocode("Hải Phòng", providers=providers)

    assert len(fake.calls) == 1

    # Accent/whitespace-insensitive: the same place spelled differently is one
    # cache entry (the HTTP query still carries the raw text).
    await geocoding.geocode("  HAI   PHONG ", providers=providers)
    assert len(fake.calls) == 1


@pytest.mark.asyncio
async def test_geocode_non_200_is_a_cached_miss(geo_env):
    cache, _settings = geo_env
    fake = _register_google({"error": "nope"}, status=503)
    providers = GeoRuntimeConfig(google_maps_api_key="k")

    assert await geocoding.geocode("Không tồn tại", providers=providers) is None
    assert cache.writes[-1][1] == {"miss": True}
    assert cache.writes[-1][2] == 21_600

    assert await geocoding.geocode("Không tồn tại", providers=providers) is None
    assert len(fake.calls) == 1


@pytest.mark.asyncio
async def test_geocode_timeout_is_a_cached_miss(geo_env):
    cache, _settings = geo_env
    _register_google(side_effect=TimeoutError("geocoder slow"))

    assert await geocoding.geocode(
        "Hải Phòng", providers=GeoRuntimeConfig(google_maps_api_key="k")
    ) is None
    assert cache.writes[-1][1] == {"miss": True}


@pytest.mark.asyncio
async def test_geocode_empty_query_is_none_without_http(geo_env):
    cache, _settings = geo_env
    fake = _register_google(_google_payload(1.0, 2.0))

    assert await geocoding.geocode(
        "   ", providers=GeoRuntimeConfig(google_maps_api_key="k")
    ) is None
    assert fake.calls == []
    assert cache.writes == []


@pytest.mark.asyncio
async def test_geocode_disabled_writes_miss_without_http(geo_env, monkeypatch):
    cache, settings = geo_env
    settings.geocoder_enabled = False
    fake = _register_google(_google_payload(1.0, 2.0))

    assert await geocoding.geocode(
        "Hải Phòng", providers=GeoRuntimeConfig(google_maps_api_key="k")
    ) is None
    assert fake.calls == []
    assert cache.writes[-1][1] == {"miss": True}


@pytest.mark.asyncio
async def test_geocode_with_no_configured_key_is_a_miss_without_any_call(geo_env):
    """There is no keyless provider any more.

    Nominatim was the always-available fallback and it is what answered a
    factory address with the city centroid; the price of removing it is that an
    installation with no key reports no coordinates at all. A miss is the
    documented degradation — the catalog then omits ``distance_km`` instead of
    quoting a number measured from the middle of a city.
    """
    cache, _settings = geo_env
    google = _register_google(_google_payload(1.0, 2.0))
    vietmap = _vietmap_hit()

    assert await geocoding.geocode("Núi Đèo", providers=GeoRuntimeConfig()) is None

    assert google.calls == []
    assert vietmap.calls == []
    assert cache.writes[-1][1] == {"miss": True}


def test_haversine_km_measures_a_known_province_pair():
    # Hà Nội → Hải Phòng (city centres) is ~100 km straight-line.
    distance = haversine_km((21.028, 105.834), (20.865, 106.683))
    assert 90 <= distance <= 110


def test_haversine_km_is_zero_for_the_same_point():
    assert haversine_km((20.865, 106.683), (20.865, 106.683)) == pytest.approx(0.0)


# --- the hop chain ------------------------------------------------------------


@pytest.mark.asyncio
async def test_google_first_returns_before_vietmap(geo_env):
    """Google is the primary hop and Vietmap the fallback — the order came out of
    the 12-case study against OSM ground truth (median positional error 0.92 km
    against 2.74 km; the decisive case, a work address carrying a company name,
    was 6.81 km off on Vietmap and 1.13 km on Google). With both keys configured
    Google must therefore answer and Vietmap must not be called at all."""
    _cache, _settings = geo_env
    google = _register_google(_google_payload(10.8, 106.7))
    vietmap = _vietmap_hit()

    result = await geocoding.geocode(
        "An Dương, Hải Phòng",
        providers=GeoRuntimeConfig(vietmap_api_key="vk", google_maps_api_key="gk"),
    )

    assert result == (10.8, 106.7)
    assert google.calls[0]["params"]["address"] == "An Dương, Hải Phòng"
    assert vietmap.calls == []


@pytest.mark.asyncio
async def test_vietmap_answers_when_google_misses(geo_env):
    """The fallback is the reason Vietmap is still in the chain: a chain whose
    only hop is over quota or down has no answer left."""
    _cache, _settings = geo_env
    google = _google_miss()
    vietmap = _vietmap_hit()

    result = await geocoding.geocode(
        "An Dương, Hải Phòng",
        providers=GeoRuntimeConfig(vietmap_api_key="vk", google_maps_api_key="gk"),
    )

    assert result == (10.8, 106.7)
    assert google.calls
    assert vietmap.calls


@pytest.mark.asyncio
async def test_vietmap_resolves_through_search_then_place(geo_env):
    """Text→coordinates is two calls; the ref_id passes through verbatim."""
    _cache, _settings = geo_env
    vietmap = _register_vietmap(
        search_payload=[{"ref_id": "geocode:RAkPci", "display": "Núi Đèo"}],
        place_payload={"lat": 20.9624, "lng": 106.7149},
    )
    google = _google_miss()

    result = await geocoding.geocode(
        "Núi Đèo",
        providers=GeoRuntimeConfig(vietmap_api_key="vk", google_maps_api_key="gk"),
    )

    assert result == (20.9624, 106.7149)
    assert google.calls
    assert vietmap.calls[0]["url"] == "/api/search/v4"
    assert vietmap.calls[0]["params"]["text"] == "Núi Đèo"
    assert vietmap.calls[0]["params"]["display_type"] == "5"
    assert vietmap.calls[1]["url"] == "/api/place/v4"
    assert vietmap.calls[1]["params"]["refid"] == "geocode:RAkPci"


@pytest.mark.asyncio
async def test_every_hop_is_asked_once_with_the_verbatim_query(geo_env):
    """No relaxation, ever — this is the invariant that replaced the ladder.

    The removed ladder retried suffixes with leading components dropped, which is
    how a full work address became a city centroid. Both keyed providers answer a
    partial query with a confident WRONG match rather than nothing ("tran phu" →
    Phường Trần Phú, Hà Tĩnh), so the query must reach each hop exactly as the
    caller wrote it, exactly once, and a miss must stay a miss.
    """
    _cache, _settings = geo_env
    query = "Tầng 2, Công ty LG, KCN Tràng Duệ, An Phong, An Dương, Hải Phòng"
    google = _google_miss()
    vietmap = _register_vietmap(search_payload=[], place_payload=None)

    assert await geocoding.geocode(
        query,
        providers=GeoRuntimeConfig(vietmap_api_key="vk", google_maps_api_key="gk"),
    ) is None

    assert [call["params"]["address"] for call in google.calls] == [query]
    assert [call["params"]["text"] for call in vietmap.calls] == [query]


@pytest.mark.asyncio
async def test_vietmap_converts_the_viewbox_into_a_focus_centre(geo_env):
    """Vietmap takes no viewbox, only a single ranking point: the project box is
    handed over as its centre so the candidate's region still steers the
    ranking."""
    _cache, _settings = geo_env
    _google_miss()
    vietmap = _vietmap_hit()

    await geocoding.geocode(
        "Núi Đèo",
        viewbox="106.1500,21.3500,107.2500,20.4500",
        providers=GeoRuntimeConfig(vietmap_api_key="vk", google_maps_api_key="gk"),
    )

    lat, lng = vietmap.calls[0]["params"]["focus"].split(",")
    assert float(lat) == pytest.approx(20.9)
    assert float(lng) == pytest.approx(106.7)


@pytest.mark.asyncio
async def test_vietmap_omits_focus_when_there_is_no_viewbox(geo_env):
    _cache, _settings = geo_env
    _google_miss()
    vietmap = _vietmap_hit()

    await geocoding.geocode(
        "An Dương, Hải Phòng",
        providers=GeoRuntimeConfig(vietmap_api_key="vk", google_maps_api_key="gk"),
    )

    assert "focus" not in vietmap.calls[0]["params"]


@pytest.mark.asyncio
async def test_vietmap_error_is_fail_open(geo_env):
    """Every hop is fail-open and the chain never raises."""
    _cache, _settings = geo_env
    register_fake_client(
        "geocoder-vietmap", FakeHttpClient(side_effect=RuntimeError("vietmap down"))
    )
    google = _google_miss()

    assert await geocoding.geocode(
        "Núi Đèo",
        providers=GeoRuntimeConfig(vietmap_api_key="vk", google_maps_api_key="gk"),
    ) is None
    assert len(google.calls) == 1


@pytest.mark.asyncio
async def test_a_hop_without_a_key_is_never_called(geo_env):
    """An unset key must cost no request and no quota."""
    _cache, _settings = geo_env
    _register_google(_google_payload(20.9, 106.7))
    vietmap = _vietmap_hit()

    result = await geocoding.geocode(
        "Núi Đèo", providers=GeoRuntimeConfig(google_maps_api_key="k")
    )

    assert result == (20.9, 106.7)
    assert vietmap.calls == []


@pytest.mark.asyncio
async def test_vietmap_hit_is_recorded_under_its_provider(geo_env, monkeypatch):
    """The durable mapping must remember WHICH hop won, so the ordering can be
    measured later."""
    _cache, _settings = geo_env
    stored: list = []

    async def capture_store(_query, coords, provider):
        stored.append((coords, provider))

    monkeypatch.setattr(geocoding, "_db_store", capture_store)
    _google_miss()
    _vietmap_hit(10.8, 106.7)

    await geocoding.geocode(
        "An Dương, Hải Phòng",
        providers=GeoRuntimeConfig(vietmap_api_key="vk", google_maps_api_key="gk"),
    )

    assert stored == [((10.8, 106.7), "vietmap")]


@pytest.mark.asyncio
async def test_vietmap_warm_cache_skips_http(geo_env):
    _cache, _settings = geo_env
    _google_miss()
    vietmap = _vietmap_hit()
    providers = GeoRuntimeConfig(vietmap_api_key="vk", google_maps_api_key="gk")

    first = await geocoding.geocode("An Dương, Hải Phòng", providers=providers)
    calls_after_first = len(vietmap.calls)
    second = await geocoding.geocode("An Dương, Hải Phòng", providers=providers)

    assert first == second == (10.8, 106.7)
    assert calls_after_first == 2
    assert len(vietmap.calls) == calls_after_first


# --- the durable mapping and the cache version --------------------------------


@pytest.mark.asyncio
async def test_geocode_answers_from_the_durable_mapping_before_any_call(geo_env, monkeypatch):
    """The DB mapping must answer before any provider HTTP call (owner rule)."""
    _cache, _settings = geo_env

    async def db_hit(_query):
        return (20.9, 106.7), True

    monkeypatch.setattr(geocoding, "_db_lookup", db_hit)
    google = _register_google(_google_payload(1.0, 2.0))
    vietmap = _vietmap_hit()

    result = await geocoding.geocode(
        "Núi Đèo",
        providers=GeoRuntimeConfig(vietmap_api_key="vk", google_maps_api_key="gk"),
    )

    assert result == (20.9, 106.7)
    assert google.calls == []
    assert vietmap.calls == []


@pytest.mark.asyncio
async def test_geocode_records_provider_hits_and_misses_in_the_mapping(geo_env, monkeypatch):
    _cache, _settings = geo_env
    stored: list = []

    async def capture_store(_query, coords, provider):
        stored.append((coords, provider))

    async def no_mapping_hit(_query):
        return None, False

    monkeypatch.setattr(geocoding, "_db_lookup", no_mapping_hit)
    monkeypatch.setattr(geocoding, "_db_store", capture_store)
    _google_miss()
    _vietmap_hit(20.8, 106.6)

    assert await geocoding.geocode(
        "Núi Đèo",
        providers=GeoRuntimeConfig(vietmap_api_key="vk", google_maps_api_key="gk"),
    ) == (20.8, 106.6)
    assert stored == [((20.8, 106.6), "vietmap")]

    # A chain-wide miss is recorded as a miss row too.
    register_fake_client("geocoder-vietmap", FakeHttpClient(side_effect=RuntimeError("down")))

    assert await geocoding.geocode(
        "Chẳng có đâu",
        providers=GeoRuntimeConfig(vietmap_api_key="vk", google_maps_api_key="gk"),
    ) is None
    assert stored[-1] == (None, None)


def test_cache_prefix_retired_the_previous_chain_entries():
    """Every semantic change to the chain retires what it produced.

    v3→v4 was the Vietmap reorder, v4→v5 the ``precision="point"`` gate, v5→v6
    the measured reorder that put Google ahead of Vietmap, v6→v7 the keyed-only
    chain, and v7→v8 the point-precision cross-check: a v7 entry was resolved
    by a single hop with no second opinion, so it does not mean what a
    cross-checked v8 entry means. A coordinate is only as good as the chain
    that produced it, so an entry from the old chain must not be served for
    another 30 days.
    """
    assert geocoding._CACHE_PREFIX == "geo:geocode:v8:"


def test_the_durable_mapping_is_versioned_too():
    """The Redis prefix bump alone is not enough: ``geocode_cache`` is keyed by
    raw query text with no version, so a coordinate admitted by the old chain
    would survive every prefix bump and keep answering. The durable key carries
    the same version."""
    assert geocoding._DB_KEY_VERSION == "v8:"


# --- precision: what an answer is allowed to be -------------------------------


@pytest.mark.asyncio
async def test_point_precision_refuses_the_city_centroid_the_incident_used(geo_env):
    """The 2026-10-03 value, refused.

    Google answers a street address it cannot place with the Hải Phòng centroid
    (``types: ["locality", "political"]`` — measured live, and it also answers
    the same centroid for a bogus street). Stored as a factory origin, that put
    KCN Tràng Duệ — 13.6 km away by road — "1.5 km" from a candidate in Phường
    An Biên. A ``point`` lookup must report the miss instead of the centroid, and
    the miss is cached so the lie is never stored.
    """
    cache, _settings = geo_env
    _register_google(_google_payload(20.8449115, 106.6880841, ["locality", "political"]))
    # The fallback is reachable but also misses, so the only coordinate on offer
    # was the centroid.
    vietmap = _register_vietmap(search_payload=[], place_payload=None)

    assert await geocoding.geocode(
        "999 Đường Không Tồn Tại XYZ, Hải Phòng",
        providers=GeoRuntimeConfig(vietmap_api_key="vk", google_maps_api_key="gk"),
        precision="point",
    ) is None

    # The refusal happened at Google, and Vietmap was still tried — the gate
    # must not turn a refused first hop into a chain-wide stop.
    assert vietmap.calls
    assert cache.writes[-1][1] == {"miss": True}
    assert cache.writes[-1][2] == 21_600


@pytest.mark.asyncio
async def test_area_precision_keeps_a_coarse_google_answer(geo_env):
    """The gate is scoped, not global: a candidate's own area only has to RANK
    projects, so a ward/city answer stays acceptable there."""
    _cache, _settings = geo_env
    _register_google(_google_payload(20.8316711, 106.6767633, ["locality", "political"]))

    assert await geocoding.geocode(
        "An Biên, Hải Phòng",
        providers=GeoRuntimeConfig(google_maps_api_key="k"),
        precision="area",
    ) == (20.8316711, 106.6767633)


@pytest.mark.asyncio
async def test_point_precision_keeps_a_real_street_address(geo_env):
    """The gate must not delete the answers this bot needs.

    Measured live: the correct street address answers ``["premise",
    "street_address"]`` and the correct factory answers ``["establishment",
    "point_of_interest"]`` — both carry ``partial_match: true``, which is exactly
    why the gate reads ``types`` instead of ``partial_match``.
    """
    _cache, _settings = geo_env
    _register_google(_google_payload(20.8454332, 106.6690782, ["premise", "street_address"]))

    assert await geocoding.geocode(
        "312 Nguyễn Công Hòa, An Biên, Hải Phòng",
        providers=GeoRuntimeConfig(google_maps_api_key="k"),
        precision="point",
    ) == (20.8454332, 106.6690782)


@pytest.mark.asyncio
async def test_point_precision_falls_through_to_a_keyed_provider_that_can_do_better(geo_env):
    """A coarse first hop is a miss, not a verdict: Vietmap gets its turn, and a
    Vietmap answer is accepted because its payload exposes no coarse flag to
    read (see ``providers.GeocodeHop.rejects_coarse``)."""
    _cache, _settings = geo_env
    _register_google(_google_payload(20.8449115, 106.6880841, ["locality", "political"]))
    vietmap = _vietmap_hit(20.8453972, 106.6689312)

    result = await geocoding.geocode(
        "312 Nguyễn Công Hòa, An Biên, Hải Phòng",
        providers=GeoRuntimeConfig(vietmap_api_key="vk", google_maps_api_key="gk"),
        precision="point",
    )

    assert result == (20.8453972, 106.6689312)
    assert vietmap.calls


@pytest.mark.asyncio
async def test_area_precision_threads_through_the_repository_lookup(monkeypatch):
    """The area lookup threads all three quality guards into the client: the
    project bounding box (bias), the admin-configured credentials, and the
    precision that decides whether a coarse answer is acceptable."""
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, MagicMock

    from app.services.retrieval import repository as repository_module
    from app.services.retrieval.repository import RetrievalRepository

    captured: dict = {}

    async def fake_geocode(query, *, viewbox=None, providers=None, precision=None):
        captured["viewbox"] = viewbox
        captured["providers"] = providers
        captured["precision"] = precision
        return (20.9, 106.7)

    monkeypatch.setattr(repository_module, "geocode", fake_geocode)

    class _FakeSettingsService:
        def __init__(self, _db):
            pass

        async def resolve_geocoder(self):
            return GeoRuntimeConfig(google_maps_api_key="k")

    monkeypatch.setattr(
        "app.services.integration_settings.IntegrationSettingsService",
        _FakeSettingsService,
    )

    repo = RetrievalRepository(MagicMock())
    repo._catalog = SimpleNamespace(
        active_area_viewbox=AsyncMock(return_value="106.1,21.3,107.2,20.4")
    )

    assert await repo.geocode_area("Núi Đèo") == (20.9, 106.7)
    assert captured["viewbox"] == "106.1,21.3,107.2,20.4"
    assert captured["providers"].google_maps_api_key == "k"
    assert captured["precision"] == "area"


def test_viewbox_focus_ignores_absent_or_malformed_boxes():
    assert geocoding._viewbox_focus(None) is None
    assert geocoding._viewbox_focus("") is None
    assert geocoding._viewbox_focus("106.15,21.35") is None
    assert geocoding._viewbox_focus("a,b,c,d") is None


# --- the point-precision second opinion (2026-10-07 Cầu Bính incident) --------


_HP_VIEWBOX = "106.1500,21.3500,107.2500,20.4500"  # the active-project region
_WRONG_BINH = (20.8757959, 106.3235695)  # Gia Lộc, Hải Dương — Google's answer
_RIGHT_BINH = (20.8767415, 106.6688351)  # Cầu Bính, Thủy Nguyên, Hải Phòng


@pytest.mark.asyncio
async def test_point_precision_adopts_the_catchment_nearer_second_opinion(geo_env):
    """The incident replay: Google answers a same-named "Cầu Bính" in Hải
    Dương, 35 km west of every project. A point-precision lookup cross-checks
    with Vietmap (focused on the project region), the two disagree far past the
    tolerance, and the catchment-nearer answer is the one quoted."""
    cache, _settings = geo_env
    _register_google(_google_payload(*_WRONG_BINH))
    vietmap = _vietmap_hit(*_RIGHT_BINH)

    result = await geocoding.geocode(
        "cau binh, hai phong",
        viewbox=_HP_VIEWBOX,
        providers=GeoRuntimeConfig(vietmap_api_key="vk", google_maps_api_key="gk"),
        precision="point",
    )

    assert result == _RIGHT_BINH
    assert vietmap.calls
    # The adopted answer is the one cached and stored, under the adopting hop.
    assert cache.writes[-1][1] == {"lat": _RIGHT_BINH[0], "lng": _RIGHT_BINH[1]}


@pytest.mark.asyncio
async def test_point_precision_keeps_the_first_hit_when_the_hops_agree(geo_env):
    """Agreement inside the tolerance is the normal case: the second opinion
    changes nothing and costs nothing but the call."""
    _cache, _settings = geo_env
    _register_google(_google_payload(20.87, 106.66))
    _vietmap_hit(20.876, 106.668)

    result = await geocoding.geocode(
        "cau binh, hai phong",
        viewbox=_HP_VIEWBOX,
        providers=GeoRuntimeConfig(vietmap_api_key="vk", google_maps_api_key="gk"),
        precision="point",
    )

    assert result == (20.87, 106.66)


@pytest.mark.asyncio
async def test_point_precision_keeps_the_first_hit_when_it_is_the_catchment_nearer_one(
    geo_env,
):
    """Disagreement alone does not demote the first hop: when the second
    opinion lands FARTHER from the project region, the first answer stands."""
    _cache, _settings = geo_env
    _register_google(_google_payload(20.9, 106.7))
    _vietmap_hit(20.0, 106.0)

    result = await geocoding.geocode(
        "some place",
        viewbox=_HP_VIEWBOX,
        providers=GeoRuntimeConfig(vietmap_api_key="vk", google_maps_api_key="gk"),
        precision="point",
    )

    assert result == (20.9, 106.7)


@pytest.mark.asyncio
async def test_area_precision_skips_the_cross_check(geo_env):
    """Ranking callers only need a rough area: no second opinion, no extra
    provider call."""
    _cache, _settings = geo_env
    _register_google(_google_payload(*_WRONG_BINH))
    vietmap = _vietmap_hit(*_RIGHT_BINH)

    result = await geocoding.geocode(
        "cau binh, hai phong",
        viewbox=_HP_VIEWBOX,
        providers=GeoRuntimeConfig(vietmap_api_key="vk", google_maps_api_key="gk"),
        precision="area",
    )

    assert result == _WRONG_BINH
    assert vietmap.calls == []


@pytest.mark.asyncio
async def test_point_precision_without_a_focus_skips_the_cross_check(geo_env):
    """No focus, no tiebreaker: without a region to judge catchment-nearness
    the first answer stands rather than an arbitrary pick."""
    _cache, _settings = geo_env
    _register_google(_google_payload(*_WRONG_BINH))
    vietmap = _vietmap_hit(*_RIGHT_BINH)

    result = await geocoding.geocode(
        "cau binh, hai phong",
        providers=GeoRuntimeConfig(vietmap_api_key="vk", google_maps_api_key="gk"),
        precision="point",
    )

    assert result == _WRONG_BINH
    assert vietmap.calls == []
