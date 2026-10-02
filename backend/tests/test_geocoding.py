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
    assert key.startswith("geo:geocode:v3:")
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

    async def fake_geocode(query, *, viewbox=None, providers=None):
        captured["viewbox"] = viewbox
        captured["providers"] = providers
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
