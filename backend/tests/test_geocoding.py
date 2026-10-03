"""Unit tests for the free geocoding client and the haversine helper.

No network: the geocoder's httpx client comes from the process-scoped registry,
so a ``FakeHttpClient`` is injected under its name. The cache is an in-memory
dict so TTLs and hit/miss behavior are observable, and the throttle state is
reset per test.
"""

from __future__ import annotations

import time
from typing import Any

import pytest

from app.recruitment.domain.recommendation import haversine_km
from app.services.geo import geocoding
from app.services.integration_settings.providers.geo import GeoRuntimeConfig
from tests.helpers.http_fake import FakeHttpClient, register_fake_client


class _Settings:
    """The subset of Settings the geocoding client reads."""

    geocoder_enabled = True
    geocoder_base_url = "https://nominatim.example"
    geocoder_user_agent = "tingting-crm-test/1.0"
    geocoder_timeout_seconds = 3.0
    geocoder_cache_ttl_seconds = 2_592_000
    geocoder_negative_ttl_seconds = 21_600
    geocoder_min_interval_seconds = 0.0


class _Cache:
    def __init__(self) -> None:
        self.data: dict[str, Any] = {}
        self.writes: list[tuple[str, Any, int]] = []


@pytest.fixture
def geo_env(monkeypatch):
    """Fake settings + in-memory cache + fresh throttle state."""
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
    monkeypatch.setattr(geocoding, "_last_call_at", 0.0)

    async def _noop_lookup(_query):
        return None, False

    async def _noop_store(_query, _coords, _provider):
        return None

    monkeypatch.setattr(geocoding, "_db_lookup", _noop_lookup)
    monkeypatch.setattr(geocoding, "_db_store", _noop_store)
    return cache, settings


def _register(payload: Any = None, *, status: int = 200, side_effect: BaseException | None = None):
    return register_fake_client(
        "geocoder",
        FakeHttpClient(
            responses=[payload] if payload is not None else None,
            status_codes=[status],
            side_effect=side_effect,
        ),
    )


@pytest.mark.asyncio
async def test_geocode_parses_lat_lon_and_caches_the_hit(geo_env):
    cache, _settings = geo_env
    fake = _register([{"lat": "20.865", "lon": "106.683"}])

    assert await geocoding.geocode("KCN Tràng Duệ, An Dương") == (20.865, 106.683)

    assert fake.calls[0]["url"] == "/search"
    assert fake.calls[0]["params"]["countrycodes"] == "vn"
    assert fake.calls[0]["params"]["q"] == "KCN Tràng Duệ, An Dương"
    key, value, ttl = cache.writes[-1]
    assert key.startswith("geo:geocode:v6:")
    assert value == {"lat": 20.865, "lng": 106.683}
    assert ttl == 2_592_000


@pytest.mark.asyncio
async def test_geocode_warm_cache_skips_http(geo_env):
    cache, _settings = geo_env
    fake = _register([{"lat": "20.0", "lon": "106.0"}])
    await geocoding.geocode("Hải Phòng")
    await geocoding.geocode("Hải Phòng")

    assert len(fake.calls) == 1

    # Accent/whitespace-insensitive: the same place spelled differently is one
    # cache entry (the HTTP query still carries the raw text).
    await geocoding.geocode("  HAI   PHONG ")
    assert len(fake.calls) == 1


@pytest.mark.asyncio
async def test_geocode_non_200_is_a_cached_miss(geo_env):
    cache, _settings = geo_env
    fake = _register({"error": "nope"}, status=503)

    assert await geocoding.geocode("Không tồn tại") is None
    assert cache.writes[-1][1] == {"miss": True}
    assert cache.writes[-1][2] == 21_600

    assert await geocoding.geocode("Không tồn tại") is None
    assert len(fake.calls) == 1


@pytest.mark.asyncio
async def test_geocode_timeout_is_a_cached_miss(geo_env):
    cache, _settings = geo_env
    _register(side_effect=TimeoutError("geocoder slow"))

    assert await geocoding.geocode("Hải Phòng") is None
    assert cache.writes[-1][1] == {"miss": True}


@pytest.mark.asyncio
async def test_geocode_empty_result_is_a_miss(geo_env):
    cache, _settings = geo_env
    _register([])

    assert await geocoding.geocode("Địa chỉ không có") is None
    assert cache.writes[-1][1] == {"miss": True}


@pytest.mark.asyncio
async def test_geocode_empty_query_is_none_without_http(geo_env):
    cache, _settings = geo_env
    fake = _register([{"lat": "1", "lon": "2"}])

    assert await geocoding.geocode("   ") is None
    assert fake.calls == []
    assert cache.writes == []


@pytest.mark.asyncio
async def test_geocode_disabled_writes_miss_without_http(geo_env, monkeypatch):
    cache, settings = geo_env
    settings.geocoder_enabled = False
    fake = _register([{"lat": "1", "lon": "2"}])

    assert await geocoding.geocode("Hải Phòng") is None
    assert fake.calls == []
    assert cache.writes[-1][1] == {"miss": True}


@pytest.mark.asyncio
async def test_geocode_throttles_consecutive_calls(geo_env, monkeypatch):
    _cache, settings = geo_env
    settings.geocoder_min_interval_seconds = 0.2
    _register([{"lat": "1", "lon": "2"}])
    _register([{"lat": "3", "lon": "4"}])

    started = time.monotonic()
    await geocoding.geocode("Hải Phòng")
    await geocoding.geocode("Hà Nội")
    elapsed = time.monotonic() - started

    assert elapsed >= 0.2


def test_haversine_km_measures_a_known_province_pair():
    # Hà Nội → Hải Phòng (city centres) is ~100 km straight-line.
    distance = haversine_km((21.028, 105.834), (20.865, 106.683))
    assert 90 <= distance <= 110


def test_haversine_km_is_zero_for_the_same_point():
    assert haversine_km((20.86, 106.68), (20.86, 106.68)) == pytest.approx(0.0)


@pytest.mark.asyncio
async def test_geocode_relaxes_the_query_and_caches_under_the_original(geo_env):
    """Nominatim rejects a whole address when one component is unknown.

    The full work address misses; its own suffix resolves, and the hit is cached
    under the address the caller passed (so the walk happens once).
    """
    cache, _settings = geo_env
    address = "Tầng 2, Công ty LG Electronics, KCN Tràng Duệ, An Phong, An Dương, Hải Phòng"
    fake = register_fake_client(
        "geocoder",
        FakeHttpClient(
            responses=[[], [], [{"lat": "20.863", "lon": "106.612"}]],
            status_codes=[200, 200, 200],
        ),
    )

    assert await geocoding.geocode(address) == (20.863, 106.612)

    assert [call["params"]["q"] for call in fake.calls] == [
        address,
        "Công ty LG Electronics, KCN Tràng Duệ, An Phong, An Dương, Hải Phòng",
        "KCN Tràng Duệ, An Phong, An Dương, Hải Phòng",
    ]
    key, value, ttl = cache.writes[-1]
    assert key == geocoding._cache_key(address)
    assert value == {"lat": 20.863, "lng": 106.612}
    assert ttl == 2_592_000

    assert await geocoding.geocode(address) == (20.863, 106.612)
    assert len(fake.calls) == 3  # the second call is served from the cache


@pytest.mark.asyncio
async def test_geocode_bounds_the_relaxation_attempts(geo_env):
    cache, _settings = geo_env
    address = ", ".join(f"Phần {index}" for index in range(9))
    fake = register_fake_client(
        "geocoder", FakeHttpClient(responses=[[] for _ in range(9)])
    )

    assert await geocoding.geocode(address) is None

    assert len(fake.calls) == geocoding._MAX_QUERY_ATTEMPTS
    assert cache.writes[-1][1] == {"miss": True}


@pytest.mark.asyncio
async def test_geocode_tries_the_exact_text_first(geo_env):
    """A precise address must never be relaxed before it has been tried as-is."""
    _cache, _settings = geo_env
    fake = _register([{"lat": "20.5", "lon": "106.5"}])

    await geocoding.geocode("Số 8, Đường Lê Lợi, Hải Phòng")

    assert len(fake.calls) == 1
    assert fake.calls[0]["params"]["q"] == "Số 8, Đường Lê Lợi, Hải Phòng"


@pytest.mark.asyncio
async def test_geocode_rejects_a_street_level_match(geo_env):
    """A road fuzzy-match must not become the origin when a real place resolves."""
    _cache, _settings = geo_env
    road = {"lat": "20.949", "lon": "106.251", "addresstype": "road"}
    city = {"lat": "20.883", "lon": "106.679", "addresstype": "city"}
    address = "KCN Tràng Duệ, Huyện An Dương (xã An Phong), TP. Hải Phòng"
    fake = register_fake_client(
        "geocoder",
        FakeHttpClient(responses=[[road], [city]], status_codes=[200, 200]),
    )

    assert await geocoding.geocode(address) == (20.883, 106.679)

    assert [call["params"]["q"] for call in fake.calls] == [
        address,
        "Huyện An Dương (xã An Phong), TP. Hải Phòng",
    ]


@pytest.mark.asyncio
async def test_geocode_accepts_place_level_matches(geo_env):
    _cache, _settings = geo_env
    for kind in ("suburb", "city", "industrial", "administrative"):
        register_fake_client(
            "geocoder",
            FakeHttpClient(
                responses=[[{"lat": "20.8", "lon": "106.6", "addresstype": kind}]],
                status_codes=[200],
            ),
        )
        assert await geocoding.geocode(f"Địa điểm {kind}") == (20.8, 106.6)


@pytest.mark.asyncio
async def test_geocode_passes_the_viewbox_when_the_area_lookup_biases(geo_env):
    """The region bias must reach the provider: a bare landmark name otherwise
    resolves nationwide — the 2026-10-02 incident put "Núi Đèo" in Thái Nguyên,
    ~120 km from every project it was supposed to rank against."""
    _cache, _settings = geo_env
    fake = _register([{"lat": "20.9624", "lon": "106.7149", "addresstype": "peak"}])

    await geocoding.geocode("Núi Đèo", viewbox="106.1500,21.3500,107.2500,20.4500")

    assert fake.calls[0]["params"]["viewbox"] == "106.1500,21.3500,107.2500,20.4500"
    assert fake.calls[0]["params"]["q"] == "Núi Đèo"


@pytest.mark.asyncio
async def test_geocode_omits_the_viewbox_by_default(geo_env):
    """Project-address geocoding (ingest) passes no bias: the address carries
    its own hierarchy and grounding."""
    _cache, _settings = geo_env
    fake = _register([{"lat": "20.8", "lon": "106.6"}])

    await geocoding.geocode("An Dương, Hải Phòng")

    assert "viewbox" not in fake.calls[0]["params"]


@pytest.mark.asyncio
async def test_geocode_tries_google_first_when_a_key_is_configured(geo_env):
    """The regional hop resolves Vietnamese landmarks OSM lacks; a configured
    key must run BEFORE the Nominatim ladder and short-circuit it."""
    _cache, _settings = geo_env
    google = register_fake_client(
        "geocoder-google",
        FakeHttpClient(
            responses=[
                {
                    "status": "OK",
                    "results": [
                        {"geometry": {"location": {"lat": 20.9, "lng": 106.7}}}
                    ],
                }
            ],
            status_codes=[200],
        ),
    )
    nominatim = _register([{"lat": "20.8", "lon": "106.6"}])

    result = await geocoding.geocode(
        "Núi Đèo",
        providers=GeoRuntimeConfig(google_maps_api_key="k"),
    )

    assert result == (20.9, 106.7)
    assert google.calls[0]["params"]["address"] == "Núi Đèo"
    assert nominatim.calls == []


@pytest.mark.asyncio
async def test_geocode_falls_through_to_nominatim_when_google_misses(geo_env):
    _cache, _settings = geo_env
    google = register_fake_client(
        "geocoder-google",
        FakeHttpClient(
            responses=[{"status": "ZERO_RESULTS", "results": []}],
            status_codes=[200],
        ),
    )
    nominatim = _register([{"lat": "20.8", "lon": "106.6"}])

    result = await geocoding.geocode(
        "Núi Đèo",
        providers=GeoRuntimeConfig(google_maps_api_key="k"),
    )

    assert result == (20.8, 106.6)
    assert len(google.calls) == 1
    assert nominatim.calls[0]["params"]["q"] == "Núi Đèo"


@pytest.mark.asyncio
async def test_geocode_area_passes_the_viewbox_and_admin_providers(monkeypatch):
    """The area lookup threads both quality guards into the client: the
    project bounding box (bias) and the admin-configured regional credential."""
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


@pytest.mark.asyncio
async def test_geocode_answers_from_the_durable_mapping_before_any_call(geo_env, monkeypatch):
    """The DB mapping must answer before any provider HTTP call (owner rule)."""
    _cache, _settings = geo_env

    async def db_hit(_query):
        return (20.9, 106.7), True

    monkeypatch.setattr(geocoding, "_db_lookup", db_hit)
    google = register_fake_client(
        "geocoder-google",
        FakeHttpClient(
            responses=[{"status": "OK", "results": []}], status_codes=[200]
        ),
    )
    nominatim = _register([{"lat": "20.8", "lon": "106.6"}])

    result = await geocoding.geocode(
        "Núi Đèo", providers=GeoRuntimeConfig(google_maps_api_key="k")
    )

    assert result == (20.9, 106.7)
    assert google.calls == []
    assert nominatim.calls == []


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
    register_fake_client(
        "geocoder-google",
        FakeHttpClient(
            responses=[{"status": "ZERO_RESULTS", "results": []}], status_codes=[200]
        ),
    )
    _register([{"lat": "20.8", "lon": "106.6"}])

    assert await geocoding.geocode(
        "Núi Đèo", providers=GeoRuntimeConfig(google_maps_api_key="k")
    ) == (20.8, 106.6)
    assert stored == [((20.8, 106.6), "nominatim")]

    # A full ladder miss is recorded as a miss row too.
    register_fake_client(
        "geocoder",
        FakeHttpClient(side_effect=RuntimeError("network down")),
    )

    assert await geocoding.geocode("Chẳng có đâu") is None
    assert stored[-1] == (None, None)


# --- Vietmap: the primary hop -------------------------------------------------


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


def _google_miss():
    return register_fake_client(
        "geocoder-google",
        FakeHttpClient(responses=[{"status": "ZERO_RESULTS", "results": []}], status_codes=[200]),
    )


@pytest.mark.asyncio
async def test_vietmap_resolves_through_search_then_place(geo_env):
    """Text→coordinates is two calls; the ref_id passes through verbatim."""
    _cache, _settings = geo_env
    vietmap = _register_vietmap(
        search_payload=[{"ref_id": "geocode:RAkPci", "display": "Núi Đèo"}],
        place_payload={"lat": 20.9624, "lng": 106.7149},
    )
    nominatim = _register([{"lat": "0", "lon": "0"}])

    result = await geocoding.geocode(
        "Núi Đèo", providers=GeoRuntimeConfig(vietmap_api_key="vk")
    )

    assert result == (20.9624, 106.7149)
    assert vietmap.calls[0]["url"] == "/api/search/v4"
    assert vietmap.calls[0]["params"]["text"] == "Núi Đèo"
    assert vietmap.calls[0]["params"]["display_type"] == "5"
    assert vietmap.calls[1]["url"] == "/api/place/v4"
    assert vietmap.calls[1]["params"]["refid"] == "geocode:RAkPci"
    assert nominatim.calls == []


@pytest.mark.asyncio
async def test_google_first_returns_before_vietmap(geo_env):
    """Google is the primary hop and Vietmap the fallback — the order came out of
    the 12-case study against OSM ground truth (median positional error 0.92 km
    against 2.74 km; the decisive case, a work address carrying a company name,
    was 6.81 km off on Vietmap and 1.13 km on Google). With both keys configured
    Google must therefore answer and Vietmap must not be called at all."""
    _cache, _settings = geo_env
    google = register_fake_client(
        "geocoder-google",
        FakeHttpClient(
            responses=[
                {
                    "status": "OK",
                    "results": [
                        {"geometry": {"location": {"lat": 10.8, "lng": 106.7}}}
                    ],
                }
            ],
            status_codes=[200],
        ),
    )
    vietmap = _register_vietmap(
        search_payload=[{"ref_id": "geocode:x"}], place_payload={"lat": 1.0, "lng": 2.0}
    )

    result = await geocoding.geocode(
        "An Dương, Hải Phòng",
        providers=GeoRuntimeConfig(vietmap_api_key="vk", google_maps_api_key="gk"),
    )

    assert result == (10.8, 106.7)
    assert google.calls
    assert vietmap.calls == []


@pytest.mark.asyncio
async def test_vietmap_answers_when_google_misses(geo_env):
    """The fallback is the reason Vietmap is still in the chain: a chain whose
    only hop is over quota or down has no answer left."""
    _cache, _settings = geo_env
    google = _google_miss()
    vietmap = _register_vietmap(
        search_payload=[{"ref_id": "geocode:x"}], place_payload={"lat": 10.8, "lng": 106.7}
    )

    result = await geocoding.geocode(
        "An Dương, Hải Phòng",
        providers=GeoRuntimeConfig(vietmap_api_key="vk", google_maps_api_key="gk"),
    )

    assert result == (10.8, 106.7)
    assert google.calls
    assert vietmap.calls


@pytest.mark.asyncio
async def test_vietmap_converts_the_viewbox_into_a_focus_centre(geo_env):
    """Vietmap has no viewbox, only a single ranking point: the project box is
    handed over as its centre so the same region signal serves both hops."""
    _cache, _settings = geo_env
    vietmap = _register_vietmap(
        search_payload=[{"ref_id": "geocode:x"}], place_payload={"lat": 10.8, "lng": 106.7}
    )

    await geocoding.geocode(
        "Núi Đèo",
        viewbox="106.1500,21.3500,107.2500,20.4500",
        providers=GeoRuntimeConfig(vietmap_api_key="vk"),
    )

    lat, lng = vietmap.calls[0]["params"]["focus"].split(",")
    assert float(lat) == pytest.approx(20.9)
    assert float(lng) == pytest.approx(106.7)


@pytest.mark.asyncio
async def test_vietmap_omits_focus_when_there_is_no_viewbox(geo_env):
    _cache, _settings = geo_env
    vietmap = _register_vietmap(
        search_payload=[{"ref_id": "geocode:x"}], place_payload={"lat": 10.8, "lng": 106.7}
    )

    await geocoding.geocode("An Dương, Hải Phòng", providers=GeoRuntimeConfig(vietmap_api_key="vk"))

    assert "focus" not in vietmap.calls[0]["params"]


@pytest.mark.asyncio
async def test_vietmap_receives_only_the_exact_text(geo_env):
    """The relaxation ladder must never reach Vietmap: it answers a partial
    query with a confident WRONG match ("tran phu" → Phường Trần Phú, Hà
    Tĩnh) rather than nothing."""
    _cache, _settings = geo_env
    query = "Tầng 2, Công ty LG, KCN Tràng Duệ, An Phong, An Dương, Hải Phòng"
    vietmap = register_fake_client("geocoder-vietmap", FakeHttpClient(responses=[[]]))
    # Every Nominatim attempt fails, so the ladder walks every relaxed variant.
    nominatim = _register(side_effect=RuntimeError("nominatim down"))

    await geocoding.geocode(query, providers=GeoRuntimeConfig(vietmap_api_key="vk"))

    assert len(vietmap.calls) == 1
    assert vietmap.calls[0]["params"]["text"] == query
    # The ladder still relaxes for Nominatim — the rescue is not lost, it is
    # simply confined to the provider that needs it.
    relaxed = [call["params"]["q"] for call in nominatim.calls]
    assert len(relaxed) == geocoding._MAX_QUERY_ATTEMPTS
    assert relaxed[0] == query
    assert len(set(relaxed)) == len(relaxed)


@pytest.mark.asyncio
async def test_vietmap_error_falls_through_to_google_then_nominatim(geo_env):
    """Every hop is fail-open and the chain never raises."""
    _cache, _settings = geo_env
    register_fake_client(
        "geocoder-vietmap", FakeHttpClient(side_effect=RuntimeError("vietmap down"))
    )
    google = _google_miss()
    nominatim = _register([{"lat": "20.8", "lon": "106.6"}])

    result = await geocoding.geocode(
        "Núi Đèo",
        providers=GeoRuntimeConfig(vietmap_api_key="vk", google_maps_api_key="gk"),
    )

    assert result == (20.8, 106.6)
    assert len(google.calls) == 1
    assert nominatim.calls[0]["params"]["q"] == "Núi Đèo"


@pytest.mark.asyncio
async def test_vietmap_skipped_when_no_key_is_configured(geo_env):
    """An unset key must cost no request and no quota."""
    _cache, _settings = geo_env
    vietmap = _register_vietmap(
        search_payload=[{"ref_id": "geocode:x"}], place_payload={"lat": 1.0, "lng": 2.0}
    )
    nominatim = _register([{"lat": "20.8", "lon": "106.6"}])

    result = await geocoding.geocode("Núi Đèo", providers=GeoRuntimeConfig())

    assert result == (20.8, 106.6)
    assert vietmap.calls == []
    # The chain degrades to the keyless fallback exactly as before the change.
    assert nominatim.calls[0]["params"]["q"] == "Núi Đèo"


@pytest.mark.asyncio
async def test_vietmap_hit_is_recorded_under_its_provider(geo_env, monkeypatch):
    """The durable mapping must remember WHICH hop won, so the reordering can
    be measured later."""
    _cache, _settings = geo_env
    stored: list = []

    async def capture_store(_query, coords, provider):
        stored.append((coords, provider))

    monkeypatch.setattr(geocoding, "_db_store", capture_store)
    _register_vietmap(
        search_payload=[{"ref_id": "geocode:x"}], place_payload={"lat": 10.8, "lng": 106.7}
    )

    await geocoding.geocode("An Dương, Hải Phòng", providers=GeoRuntimeConfig(vietmap_api_key="vk"))

    assert stored == [((10.8, 106.7), "vietmap")]


@pytest.mark.asyncio
async def test_vietmap_warm_cache_skips_http(geo_env):
    _cache, _settings = geo_env
    vietmap = _register_vietmap(
        search_payload=[{"ref_id": "geocode:x"}], place_payload={"lat": 10.8, "lng": 106.7}
    )

    first = await geocoding.geocode("An Dương, Hải Phòng", providers=GeoRuntimeConfig(vietmap_api_key="vk"))
    calls_after_first = len(vietmap.calls)
    second = await geocoding.geocode("An Dương, Hải Phòng", providers=GeoRuntimeConfig(vietmap_api_key="vk"))

    assert first == second == (10.8, 106.7)
    assert calls_after_first == 2
    assert len(vietmap.calls) == calls_after_first


def test_cache_prefix_retired_the_previous_chain_entries():
    """Every semantic change to the chain retires what it produced.

    v3→v4 was the Vietmap reorder, v4→v5 the ``precision="point"`` gate, and
    v5→v6 the measured reorder that put Google ahead of Vietmap. A coordinate is
    only as good as the chain that produced it, so an entry from the old order
    must not be served for another 30 days.
    """
    assert geocoding._CACHE_PREFIX == "geo:geocode:v6:"


def test_the_durable_mapping_is_versioned_too():
    """The Redis prefix bump alone is not enough: ``geocode_cache`` is keyed by
    raw query text with no version, so a coordinate admitted by the old chain
    would survive every prefix bump and keep answering. The durable key carries
    the same version."""
    assert geocoding._DB_KEY_VERSION == "v6:"


@pytest.mark.asyncio
async def test_geocode_point_precision_refuses_a_city_centroid_fallback(geo_env):
    """The 2026-10-03 incident, end to end.

    A real project address matched nothing until the ladder had dropped every
    leading component and asked for the bare city, which Nominatim answered with
    the Hải Phòng centroid. Stored as a factory gate, that put KCN Tràng Duệ
    (13.6 km by road) "1.5 km" from a candidate in Phường An Biên. A ``point``
    lookup must report the miss instead of the centroid.
    """
    cache, _settings = geo_env
    address = "Tầng 2, Công ty LG Electronics (LGE), KCN Tràng Duệ, An Phong, An Dương, Hải Phòng"
    # Every relaxed attempt lands on an area label; the last one is the city.
    city = {"lat": "20.8830967", "lon": "106.6790381", "addresstype": "city"}
    fake = register_fake_client(
        "geocoder",
        FakeHttpClient(
            responses=[[], [city], [city], [city], [city]],
            status_codes=[200] * 5,
        ),
    )

    assert await geocoding.geocode(address, precision="point") is None

    # The ladder walked every variant it is allowed and refused them all; the
    # last one it reached is the coarsest suffix the cap permits.
    assert [call["params"]["q"] for call in fake.calls][-1] == "An Dương, Hải Phòng"
    assert len(fake.calls) == geocoding._MAX_QUERY_ATTEMPTS
    # The miss is recorded, so a repeat is free and the lie is never cached.
    assert cache.writes[-1][1] == {"miss": True}
    assert cache.writes[-1][2] == 21_600


@pytest.mark.asyncio
async def test_geocode_area_precision_keeps_the_ward_fallback(geo_env):
    """The gate is scoped, not global: a candidate's own area only has to RANK
    projects, so a ward hit stays acceptable there."""
    _cache, _settings = geo_env
    city = {"lat": "20.8830967", "lon": "106.6790381", "addresstype": "city"}
    register_fake_client(
        "geocoder",
        FakeHttpClient(responses=[[], [city]], status_codes=[200, 200]),
    )

    assert await geocoding.geocode(
        "KCN Tràng Duệ, Huyện An Dương (xã An Phong), TP. Hải Phòng", precision="area"
    ) == (20.8830967, 106.6790381)


@pytest.mark.asyncio
async def test_geocode_point_precision_still_accepts_a_relaxed_industrial(geo_env):
    """Coarseness is the discriminator, not "relaxed". OSM tags KCN Đình Vũ
    ``industrial``, so a relaxed attempt that reaches a real facility must pass —
    otherwise the gate would silently delete every precise answer it guards."""
    _cache, _settings = geo_env
    industrial = {"lat": "20.8267968", "lon": "106.7744652", "addresstype": "industrial"}
    register_fake_client(
        "geocoder",
        FakeHttpClient(responses=[[], [industrial]], status_codes=[200, 200]),
    )

    assert await geocoding.geocode(
        "Công ty Cổ phần liên hợp kho bãi UWG, KCN Đình Vũ, TP. Hải Phòng",
        precision="point",
    ) == (20.8267968, 106.7744652)


@pytest.mark.asyncio
async def test_geocode_point_precision_keeps_the_exact_text_city_hit(geo_env):
    """Nothing was dropped, so the answer still describes the query. A candidate
    who genuinely says "Hải Phòng" must resolve, precision or not."""
    _cache, _settings = geo_env
    _register([{"lat": "20.883", "lon": "106.679", "addresstype": "city"}])

    assert await geocoding.geocode("Hải Phòng", precision="point") == (20.883, 106.679)


@pytest.mark.asyncio
async def test_geocode_ward_centroid_is_refused_by_precision_but_kept_by_area(geo_env):
    """The refusal is about the RESULT's type, not about Nominatim: the same
    ``suburb`` payload is a miss for a factory and a usable answer for an area."""
    # A distinct query per precision: the same string twice would let the first
    # iteration's cached miss answer the second.
    for precision, expected in (("point", None), ("area", (20.9, 106.7))):
        ward = {"lat": "20.9", "lon": "106.7", "addresstype": "suburb"}
        # The exact text misses, so the ward hit arrives RELAXED — the case the
        # gate is about. One canned response per variant the walk can reach.
        register_fake_client(
            "geocoder",
            FakeHttpClient(responses=[[], [ward], [ward]], status_codes=[200] * 3),
        )
        assert (
            await geocoding.geocode(
                f"KCN Tràng Duệ, An Dương, Hải Phòng ({precision})", precision=precision
            )
            == expected
        )


@pytest.mark.asyncio
async def test_geocode_point_precision_still_honours_a_keyed_provider_hit(geo_env):
    """The gate lives on the Nominatim ladder only. Vietmap is Vietnam-native and
    indexes KCN names, so its answer must pass untouched — that hop is how a
    project address gets placed at all now."""
    _cache, _settings = geo_env
    vietmap = _register_vietmap(
        search_payload=[{"ref_id": "geocode:x"}], place_payload={"lat": 20.8555, "lng": 106.5638}
    )

    result = await geocoding.geocode(
        "Công ty 4P Electronics, KCN Tràng Duệ, An Phong, An Dương, Hải Phòng",
        providers=GeoRuntimeConfig(vietmap_api_key="vk"),
        precision="point",
    )

    assert result == (20.8555, 106.5638)
    assert vietmap.calls


def test_viewbox_focus_ignores_absent_or_malformed_boxes():
    assert geocoding._viewbox_focus(None) is None
    assert geocoding._viewbox_focus("") is None
    assert geocoding._viewbox_focus("106.15,21.35") is None
    assert geocoding._viewbox_focus("a,b,c,d") is None
