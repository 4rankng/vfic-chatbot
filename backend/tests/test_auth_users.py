"""Integration tests for US-003: auth (JWT) + users admin CRUD + audit.

Covers the three acceptance criteria:
  1. POST /auth/login -> access+refresh; GET /auth/me; refresh works
  2. /users admin CRUD + disable/enable gated by require_admin; argon2; UserProvisioningService
  3. login + create_user + disable_user rows written to audit_events
"""
import uuid

import pytest
from sqlalchemy import select

from app.models.audit import AuditEvent
from tests.conftest import ADMIN_EMAIL, PASSWORD, RECRUITER_EMAIL, unique_email

pytestmark = pytest.mark.asyncio


def _bearer(tok: dict) -> dict:
    return {"Authorization": f"Bearer {tok['access_token']}"}


async def _admin_token(client) -> dict:
    r = await client.post(
        "/api/v1/auth/login", json={"email": ADMIN_EMAIL, "password": PASSWORD}
    )
    assert r.status_code == 200, r.text
    return r.json()


# --- AC 1: auth -----------------------------------------------------------


async def test_login_returns_access_and_refresh_tokens(client):
    r = await client.post(
        "/api/v1/auth/login", json={"email": ADMIN_EMAIL, "password": PASSWORD}
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]
    assert body["refresh_token"]
    assert body["expires_in"] > 0


async def test_me_returns_current_user(client):
    tok = await _admin_token(client)
    me = await client.get("/api/v1/auth/me", headers=_bearer(tok))
    assert me.status_code == 200, me.text
    body = me.json()
    assert body["email"] == ADMIN_EMAIL
    assert body["role"] == "admin"
    assert "password_hash" not in body  # secret never serialized


async def test_login_wrong_password_is_401(client):
    r = await client.post(
        "/api/v1/auth/login", json={"email": ADMIN_EMAIL, "password": "wrong"}
    )
    assert r.status_code == 401


async def test_refresh_rotates_tokens_and_rejects_access_token(client):
    tok = await _admin_token(client)

    good = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": tok["refresh_token"]}
    )
    assert good.status_code == 200, good.text
    new = good.json()
    assert new["access_token"] and new["refresh_token"]

    # an access token must not be usable as a refresh token
    bad = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": tok["access_token"]}
    )
    assert bad.status_code == 401


async def test_change_password_revokes_existing_tokens(client):
    """Bumping token_version on password change must invalidate every prior token."""
    tok = await _admin_token(client)
    access_before = tok["access_token"]
    refresh_before = tok["refresh_token"]

    r = await client.post(
        "/api/v1/auth/change-password",
        json={"current_password": PASSWORD, "new_password": "NewPassw0rd!2"},
        headers=_bearer(tok),
    )
    assert r.status_code == 204, r.text

    # the OLD access token is now rejected (ver mismatch) on a protected route
    stale_me = await client.get(
        "/api/v1/auth/me", headers=_bearer({"access_token": access_before})
    )
    assert stale_me.status_code == 401

    # the OLD refresh token can no longer mint new tokens
    stale_refresh = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": refresh_before}
    )
    assert stale_refresh.status_code == 401

    # login with the NEW password works and yields a fresh, working token
    new_tok = (
        await client.post(
            "/api/v1/auth/login",
            json={"email": ADMIN_EMAIL, "password": "NewPassw0rd!2"},
        )
    ).json()
    assert new_tok["access_token"]
    me = await client.get("/api/v1/auth/me", headers=_bearer(new_tok))
    assert me.status_code == 200


async def test_disabled_user_cannot_login_or_refresh(client):
    tok = await _admin_token(client)
    h = _bearer(tok)
    email = unique_email()

    created = await client.post(
        "/api/v1/users",
        json={"email": email, "password": "Abcd1234!", "role": "recruiter"},
        headers=h,
    )
    assert created.status_code == 201, created.text
    uid = created.json()["id"]

    # can log in while enabled
    ok = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": "Abcd1234!"}
    )
    assert ok.status_code == 200

    await client.post(f"/api/v1/users/{uid}/disable", headers=h)

    bad_login = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": "Abcd1234!"}
    )
    assert bad_login.status_code == 401

    # a refresh token minted before disable must now be rejected
    stale = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": ok.json()["refresh_token"]}
    )
    assert stale.status_code == 401


# --- AC 2: users admin CRUD + require_admin ------------------------------


async def test_users_list_requires_admin(client):
    recruiter_tok = (
        await client.post(
            "/api/v1/auth/login",
            json={"email": RECRUITER_EMAIL, "password": PASSWORD},
        )
    ).json()
    recruiter_h = _bearer(recruiter_tok)

    assert (
        await client.get("/api/v1/users", headers=recruiter_h)
    ).status_code == 403  # recruiter blocked
    assert (await client.get("/api/v1/users")).status_code == 401  # no token blocked

    admin_tok = await _admin_token(client)
    r = await client.get("/api/v1/users?per_page=200", headers=_bearer(admin_tok))
    assert r.status_code == 200
    body = r.json()
    assert {"data", "total"} <= set(body)
    assert any(u["email"] == ADMIN_EMAIL for u in body["data"])


async def test_admin_can_crud_users(client):
    tok = await _admin_token(client)
    h = _bearer(tok)

    # create
    email = unique_email()
    created = await client.post(
        "/api/v1/users",
        json={
            "email": email,
            "password": "Abcd1234!",
            "role": "recruiter",
            "full_name": "Test Recruiter",
        },
        headers=h,
    )
    assert created.status_code == 201, created.text
    uid = created.json()["id"]
    assert created.json()["role"] == "recruiter"
    assert created.json()["disabled"] is False

    # duplicate -> 409
    dup = await client.post(
        "/api/v1/users",
        json={"email": email, "password": "Abcd1234!", "role": "recruiter"},
        headers=h,
    )
    assert dup.status_code == 409

    # get + patch
    assert (await client.get(f"/api/v1/users/{uid}", headers=h)).status_code == 200
    patched = await client.patch(
        f"/api/v1/users/{uid}",
        json={"full_name": "Renamed", "role": "admin"},
        headers=h,
    )
    assert patched.status_code == 200
    assert patched.json()["full_name"] == "Renamed"
    assert patched.json()["role"] == "admin"

    # disable -> enable
    disabled = await client.post(f"/api/v1/users/{uid}/disable", headers=h)
    assert disabled.status_code == 200 and disabled.json()["disabled"] is True
    enabled = await client.post(f"/api/v1/users/{uid}/enable", headers=h)
    assert enabled.status_code == 200 and enabled.json()["disabled"] is False

    # unknown id -> 404
    assert (
        await client.get(f"/api/v1/users/{uuid.uuid4()}", headers=h)
    ).status_code == 404


async def test_admin_cannot_disable_self(client):
    tok = await _admin_token(client)
    h = _bearer(tok)
    me = (await client.get("/api/v1/auth/me", headers=h)).json()
    r = await client.post(f"/api/v1/users/{me['id']}/disable", headers=h)
    assert r.status_code == 400


# --- AC 3: audit ----------------------------------------------------------


async def test_audited_actions_recorded(client, db_session):
    tok = await _admin_token(client)
    h = _bearer(tok)
    me = (await client.get("/api/v1/auth/me", headers=h)).json()
    admin_id = uuid.UUID(me["id"])

    email = unique_email()
    created = await client.post(
        "/api/v1/users",
        json={"email": email, "password": "Abcd1234!", "role": "recruiter"},
        headers=h,
    )
    uid = created.json()["id"]
    await client.post(f"/api/v1/users/{uid}/disable", headers=h)

    rows = (
        await db_session.scalars(
            select(AuditEvent)
            .where(
                AuditEvent.actor_id == admin_id,
                AuditEvent.action.in_(
                    ["login", "create_user", "disable_user", "enable_user"]
                ),
            )
            .order_by(AuditEvent.id)
        )
    ).all()
    actions = {r.action for r in rows}

    assert "login" in actions
    assert "create_user" in actions
    assert "disable_user" in actions

    # the create_user row carries the expected payload + target
    create_rows = [r for r in rows if r.action == "create_user"]
    assert len(create_rows) == 1
    assert create_rows[0].target_type == "user"
    assert create_rows[0].target_id == str(uid)
    assert create_rows[0].payload["email"] == email
    assert create_rows[0].payload["role"] == "recruiter"
