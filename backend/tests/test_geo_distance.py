"""Unit pins for the road-distance matrix providers and their durable cache.

Two layers, matching how the geocoder is tested:

* the providers parse real Vietmap Matrix v4 / Google Distance Matrix payload
  shapes (meters → km, per-cell misses, whole-call failures) — HTTP is faked
  through ``tests.helpers.http_fake``;
* the service reads the durable mapping first, ladders Vietmap → Google for
  the remaining pairs, and stores only successes — the DB helpers are
  monkeypatched so no database is touched.

No network, no DB: every failure path must degrade to ``None`` entries, which
the catalog tools turn back into straight-line numbers.
"""

from __future__ import annotations

import pytest

from app.services.geo import distance as distance_module
from app.services.geo import providers
from app.services.integration_settings.providers.geo import GeoRuntimeConfig
from tests.helpers.http_fake import FakeHttpClient, register_fake_client

_ORIGIN = (20.86, 106.68)
_DESTS = [(20.96, 106.70), (21.06, 106.72)]


def _register(payload=None, *, status: int = 200, side_effect: BaseException | None = None):
    return register_fake_client(
        "distance-matrix",
        FakeHttpClient(
            responses=[payload] if payload is not None else None,
            status_codes=[status],
            side_effect=side_effect,
        ),
    )


# ---------------------------------------------------------------------------
# Vietmap Matrix v4
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_vietmap_matrix_parses_meters_and_durations():
    fake = _register(
        {"code": "OK", "distances": [[1766.3, 5000.0]], "durations": [[230, 600]]}
    )

    out = await providers.vietmap_matrix(_ORIGIN, _DESTS, api_key="vk")

    assert out == [(1.7663, 230.0), (5.0, 600.0)]
    call = fake.calls[0]
    assert call["url"] == "/api/matrix/v4"
    pairs = call["params"]
    as_dict = dict(pairs)
    assert as_dict["apikey"] == "vk"
    assert as_dict["sources"] == "0"
    assert as_dict["destinations"] == "1;2"
    assert as_dict["vehicle"] == "car"
    points = [value for key, value in pairs if key == "point"]
    assert points == ["20.86,106.68", "20.96,106.7", "21.06,106.72"]


@pytest.mark.asyncio
async def test_vietmap_matrix_cell_without_route_is_a_none_entry():
    _register({"code": "OK", "distances": [[None, 2000.0]], "durations": [[None, 300]]})

    out = await providers.vietmap_matrix(_ORIGIN, _DESTS, api_key="vk")

    assert out == [None, (2.0, 300.0)]


@pytest.mark.asyncio
async def test_vietmap_matrix_non_ok_code_is_whole_call_failure():
    _register({"code": "MAX_POINTS_EXCEED", "distances": [[1.0]]})

    assert await providers.vietmap_matrix(_ORIGIN, _DESTS, api_key="vk") is None


@pytest.mark.asyncio
async def test_vietmap_matrix_row_length_mismatch_is_whole_call_failure():
    _register({"code": "OK", "distances": [[1000.0]], "durations": [[100]]})

    assert await providers.vietmap_matrix(_ORIGIN, _DESTS, api_key="vk") is None


@pytest.mark.asyncio
async def test_vietmap_matrix_transport_error_is_whole_call_failure():
    _register(side_effect=TimeoutError("boom"))

    assert await providers.vietmap_matrix(_ORIGIN, _DESTS, api_key="vk") is None


@pytest.mark.asyncio
async def test_vietmap_matrix_non_200_is_whole_call_failure():
    _register({"code": "OK"}, status=429)

    assert await providers.vietmap_matrix(_ORIGIN, _DESTS, api_key="vk") is None


# ---------------------------------------------------------------------------
# Google Distance Matrix
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_google_matrix_parses_ok_cells_and_skips_bad_ones():
    fake = _register(
        {
            "status": "OK",
            "rows": [
                {
                    "elements": [
                        {
                            "status": "OK",
                            "distance": {"value": 2500},
                            "duration": {"value": 400},
                        },
                        {"status": "ZERO_RESULTS"},
                    ]
                }
            ],
        }
    )

    out = await providers.google_distance_matrix(_ORIGIN, _DESTS, api_key="gk")

    assert out == [(2.5, 400.0), None]
    call = fake.calls[0]
    assert call["url"] == "/maps/api/distancematrix/json"
    params = dict(call["params"])
    assert params["origins"] == "20.86,106.68"
    assert params["destinations"] == "20.96,106.7|21.06,106.72"
    assert params["units"] == "metric"
    assert params["key"] == "gk"


@pytest.mark.asyncio
async def test_google_matrix_non_ok_status_is_whole_call_failure():
    _register({"status": "REQUEST_DENIED", "rows": []})

    assert await providers.google_distance_matrix(_ORIGIN, _DESTS, api_key="gk") is None


@pytest.mark.asyncio
async def test_google_matrix_row_length_mismatch_is_whole_call_failure():
    _register(
        {
            "status": "OK",
            "rows": [{"elements": [{"status": "OK", "distance": {"value": 1}}]}],
        }
    )

    assert await providers.google_distance_matrix(_ORIGIN, _DESTS, api_key="gk") is None


# ---------------------------------------------------------------------------
# The service: DB first, ladder second, store successes only
# ---------------------------------------------------------------------------


@pytest.fixture
def db(monkeypatch):
    """In-memory stand-ins for the durable mapping; records every store."""
    state: dict[str, tuple[float, float | None]] = {}
    stored: list[tuple[str, dict[str, tuple[float, float | None, str]]]] = []

    async def _lookup(origin_key: str, destination_keys: list[str]):
        return {key: state[key] for key in destination_keys if key in state}

    async def _store(origin_key: str, entries):
        if not entries:  # mirrors the production helper's early return
            return
        stored.append((origin_key, dict(entries)))
        for key, (km, seconds, _provider) in entries.items():
            state[key] = (km, seconds)

    monkeypatch.setattr(distance_module, "_db_lookup", _lookup)
    monkeypatch.setattr(distance_module, "_db_store", _store)
    return type("Db", (), {"state": state, "stored": stored})()


def _provider_spy(monkeypatch, *, vietmap=None, google=None):
    """Patch both ladder hops with scripted results; record call destinations."""
    calls: dict[str, list] = {"vietmap": [], "google": []}

    async def _vietmap(origin, destinations, *, api_key):
        calls["vietmap"].append(list(destinations))
        if isinstance(vietmap, Exception):
            raise vietmap
        return vietmap

    async def _google(origin, destinations, *, api_key):
        calls["google"].append(list(destinations))
        if isinstance(google, Exception):
            raise google
        return google

    monkeypatch.setattr(distance_module, "vietmap_matrix", _vietmap)
    monkeypatch.setattr(distance_module, "google_distance_matrix", _google)
    return calls


@pytest.mark.asyncio
async def test_warm_pair_is_served_from_db_without_reasking_the_provider(monkeypatch, db):
    calls = _provider_spy(monkeypatch, vietmap=[(1.0, 60.0)], google=[(99.0, 99.0)])
    db.state[distance_module._pair_key(_DESTS[0])] = (7.5, 600.0)

    out = await distance_module.estimate_distances(
        _ORIGIN, _DESTS, providers=GeoRuntimeConfig(vietmap_api_key="vk")
    )

    # The cached pair answers straight from the DB; only the cold pair is
    # asked of the provider, and it gets exactly that one destination.
    assert out[0] == (7.5, 600.0)
    assert out[1] == (1.0, 60.0)
    assert calls["vietmap"] == [[_DESTS[1]]]
    assert calls["google"] == []
    assert {p for _km, _s, p in db.stored[0][1].values()} == {"vietmap"}


@pytest.mark.asyncio
async def test_cache_miss_ladders_vietmap_then_google_and_stores(monkeypatch, db):
    calls = _provider_spy(monkeypatch, vietmap=None, google=[(3.0, 420.0), (9.5, 900.0)])

    out = await distance_module.estimate_distances(
        _ORIGIN,
        _DESTS,
        providers=GeoRuntimeConfig(vietmap_api_key="vk", google_maps_api_key="gk"),
    )

    assert out == [(3.0, 420.0), (9.5, 900.0)]
    assert calls["vietmap"] == [_DESTS]  # first hop asked first
    assert calls["google"] == [_DESTS]  # whole-call miss → second hop
    assert len(db.stored) == 1
    _origin_key, entries = db.stored[0]
    assert {provider for _km, _s, provider in entries.values()} == {"google"}


@pytest.mark.asyncio
async def test_vietmap_success_short_circuits_google(monkeypatch, db):
    calls = _provider_spy(monkeypatch, vietmap=[(12.0, 900.0), (4.0, 300.0)])

    out = await distance_module.estimate_distances(
        _ORIGIN,
        _DESTS,
        providers=GeoRuntimeConfig(vietmap_api_key="vk", google_maps_api_key="gk"),
    )

    assert out == [(12.0, 900.0), (4.0, 300.0)]
    assert calls["google"] == []
    assert {p for _km, _s, p in db.stored[0][1].values()} == {"vietmap"}


@pytest.mark.asyncio
async def test_vietmap_partial_cells_are_filled_by_google(monkeypatch, db):
    calls = _provider_spy(monkeypatch, vietmap=[None, (6.0, 500.0)], google=[(15.0, 1200.0)])

    out = await distance_module.estimate_distances(
        _ORIGIN,
        _DESTS,
        providers=GeoRuntimeConfig(vietmap_api_key="vk", google_maps_api_key="gk"),
    )

    assert out == [(15.0, 1200.0), (6.0, 500.0)]
    assert calls["google"] == [[_DESTS[0]]]  # only the hole was asked about
    assert len(db.stored) == 2  # one store per hop that produced something


@pytest.mark.asyncio
async def test_no_configured_keys_returns_none_and_stores_nothing(monkeypatch, db):
    calls = _provider_spy(monkeypatch, vietmap=[(1.0, 1.0)], google=[(1.0, 1.0)])

    out = await distance_module.estimate_distances(
        _ORIGIN, _DESTS, providers=GeoRuntimeConfig()
    )

    assert out == [None, None]
    assert calls["vietmap"] == [] and calls["google"] == []
    assert db.stored == []


@pytest.mark.asyncio
async def test_failed_provider_attempts_are_never_stored(monkeypatch, db):
    _provider_spy(monkeypatch, vietmap=RuntimeError("outage"), google=RuntimeError("outage"))

    out = await distance_module.estimate_distances(
        _ORIGIN,
        _DESTS,
        providers=GeoRuntimeConfig(vietmap_api_key="vk", google_maps_api_key="gk"),
    )

    assert out == [None, None]
    assert db.stored == []  # the next turn retries instead of caching a hole
