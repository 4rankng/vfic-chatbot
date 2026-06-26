"""Tests for LLM-assisted persona generation (POST /knowledge/personas/generate).

The MiniMax expander is monkeypatched so no real LLM key is needed. The throttle
is stubbed to a no-op for the LLM-path tests so they stay isolated from Redis;
the throttle itself is exercised by a dedicated test that talks to Redis.
"""
import uuid

import pytest
from fastapi import HTTPException

from tests.conftest import ADMIN_EMAIL, PASSWORD, RECRUITER_EMAIL

pytestmark = pytest.mark.asyncio

GEN_URL = "/api/v1/knowledge/personas/generate"


async def _admin_tok(client) -> str:
    r = await client.post("/api/v1/auth/login", json={"email": ADMIN_EMAIL, "password": PASSWORD})
    return r.json()["access_token"]


async def _recruiter_tok(client) -> str:
    r = await client.post(
        "/api/v1/auth/login", json={"email": RECRUITER_EMAIL, "password": PASSWORD}
    )
    return r.json()["access_token"]


def _patch_llm(monkeypatch, *, return_value="### Vai trò của tôi là gì?\n(sinthetic body)", raises=None):
    """Stub build_persona_expander; capture the user message handed to the LLM."""
    captured: dict[str, str] = {}

    async def fake_expand(user: str) -> str:
        captured["user"] = user
        if raises is not None:
            raise raises
        return return_value

    def fake_builder():
        return fake_expand

    monkeypatch.setattr("app.graph.llm_real.build_persona_expander", fake_builder)
    return captured


async def _allow_rate_limit(monkeypatch):
    async def _noop(_admin_id):
        return None

    monkeypatch.setattr("app.api.personas._enforce_generate_rate_limit", _noop)


async def test_generate_requires_auth(client):
    r = await client.post(GEN_URL, json={"description": "trợ lý tuyển dụng"})
    assert r.status_code == 401


async def test_generate_requires_admin(client):
    tok = await _recruiter_tok(client)
    r = await client.post(
        GEN_URL, json={"description": "trợ lý tuyển dụng"}, headers={"Authorization": f"Bearer {tok}"}
    )
    assert r.status_code == 403


async def test_generate_rejects_empty_and_oversized(client, monkeypatch):
    await _allow_rate_limit(monkeypatch)
    tok = await _admin_tok(client)
    headers = {"Authorization": f"Bearer {tok}"}
    # empty description -> 422
    r = await client.post(GEN_URL, json={"description": ""}, headers=headers)
    assert r.status_code == 422
    # over max_length (2000) -> 422
    r = await client.post(GEN_URL, json={"description": "x" * 2001}, headers=headers)
    assert r.status_code == 422


async def test_generate_happy_path(client, monkeypatch):
    await _allow_rate_limit(monkeypatch)
    desc = "Trợ lý tuyển dụng LG Display, thân thiện, cho lao động phổ thông."
    captured = _patch_llm(monkeypatch, return_value="### Vai trò của tôi là gì?\nNội dung sinh.")
    tok = await _admin_tok(client)

    r = await client.post(
        GEN_URL, json={"description": desc}, headers={"Authorization": f"Bearer {tok}"}
    )

    assert r.status_code == 200
    body = r.json()
    assert body["body_md"] == "### Vai trò của tôi là gì?\nNội dung sinh."
    # The user message steers the LLM: 7-part heading + the description + no-NGUỒN directive.
    user_msg = captured["user"]
    assert "### Vai trò của tôi là gì?" in user_msg
    assert desc in user_msg
    assert "KHÔNG thêm mục 'NGUỒN'" in user_msg


async def test_generate_502_on_llm_failure(client, monkeypatch):
    await _allow_rate_limit(monkeypatch)
    _patch_llm(monkeypatch, raises=RuntimeError("minimax down"))
    tok = await _admin_tok(client)

    r = await client.post(
        GEN_URL, json={"description": "x"}, headers={"Authorization": f"Bearer {tok}"}
    )
    assert r.status_code == 502


async def test_generate_502_on_empty_output(client, monkeypatch):
    await _allow_rate_limit(monkeypatch)
    _patch_llm(monkeypatch, return_value="   ")
    tok = await _admin_tok(client)

    r = await client.post(
        GEN_URL, json={"description": "x"}, headers={"Authorization": f"Bearer {tok}"}
    )
    assert r.status_code == 502


async def test_generate_rate_limit_enforced(client, monkeypatch, _reset_redis):
    """6th call within the window is rejected with 429 (exercises the real throttle)."""
    from app.api.personas import _RATE_KEY, _enforce_generate_rate_limit
    from app.core.redis import get_redis

    admin_id = uuid.uuid4()
    key = _RATE_KEY.format(admin_id=admin_id)
    redis = get_redis()
    await redis.delete(key)
    try:
        for _ in range(5):
            await _enforce_generate_rate_limit(admin_id)
        with pytest.raises(HTTPException) as exc:
            await _enforce_generate_rate_limit(admin_id)
        assert exc.value.status_code == 429
    finally:
        await redis.delete(key)
