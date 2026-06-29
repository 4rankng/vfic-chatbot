"""Integration tests for US-003: auth (JWT) + users admin CRUD + audit.

Covers the three acceptance criteria:
  1. POST /auth/login -> access+refresh; GET /auth/me; refresh works
  2. /users admin CRUD + disable/enable gated by require_admin; argon2; UserProvisioningService
  3. login + create_user + disable_user rows written to audit_events
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.models.audit import AuditEvent
from app.models.password_reset import PasswordResetOtp
from app.models.user import User
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


async def test_login_rate_limited_in_production(client, _reset_redis, monkeypatch):
    """Production caps login attempts per IP (dev/test skips the limiter, so the
    rest of the suite's repeated logins are unaffected)."""
    from app.core.config import get_settings
    from app.core.redis import get_redis

    monkeypatch.setattr(get_settings(), "app_env", "production")
    # Unique forwarded-IP bucket (flushed) so leftover state never collides.
    bucket = "203.0.113.7"
    await get_redis().delete(f"rl:auth-login:{bucket}")
    headers = {"X-Forwarded-For": bucket}
    body = {"email": ADMIN_EMAIL, "password": "wrong"}

    # limit=10: the first 10 attempts pass the limiter (and 401 on bad password).
    for _ in range(10):
        r = await client.post("/api/v1/auth/login", json=body, headers=headers)
        assert r.status_code == 401, r.text
    # The 11th from the same IP is throttled.
    r = await client.post("/api/v1/auth/login", json=body, headers=headers)
    assert r.status_code == 429, r.text


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


async def test_forgot_password_generic_response_and_email_only_for_active_user(
    client, monkeypatch
):
    sent: list[tuple[str, str]] = []

    async def fake_send(*, to_email: str, otp: str) -> str:
        sent.append((to_email, otp))
        return "email_123"

    monkeypatch.setattr(
        "app.services.password_reset_service.send_password_reset_otp", fake_send
    )

    active = await client.post(
        "/api/v1/auth/forgot-password", json={"email": ADMIN_EMAIL}
    )
    unknown = await client.post(
        "/api/v1/auth/forgot-password", json={"email": unique_email()}
    )

    tok = await _admin_token(client)
    email = unique_email()
    created = await client.post(
        "/api/v1/users",
        json={"email": email, "password": "Abcd1234!", "role": "recruiter"},
        headers=_bearer(tok),
    )
    await client.post(f"/api/v1/users/{created.json()['id']}/disable", headers=_bearer(tok))
    disabled = await client.post(
        "/api/v1/auth/forgot-password", json={"email": email}
    )

    assert active.status_code == 204
    assert unknown.status_code == 204
    assert disabled.status_code == 204
    assert len(sent) == 1
    assert sent[0][0] == ADMIN_EMAIL
    assert sent[0][1].isdigit() and len(sent[0][1]) == 6


async def test_reset_password_with_otp_revokes_existing_tokens(
    client, db_session, monkeypatch
):
    sent: list[str] = []

    async def fake_send(*, to_email: str, otp: str) -> str:
        sent.append(otp)
        return "email_123"

    monkeypatch.setattr(
        "app.services.password_reset_service.send_password_reset_otp", fake_send
    )
    tok = await _admin_token(client)
    old_access = tok["access_token"]
    old_refresh = tok["refresh_token"]

    forgot = await client.post(
        "/api/v1/auth/forgot-password", json={"email": ADMIN_EMAIL}
    )
    assert forgot.status_code == 204
    assert len(sent) == 1

    reset = await client.post(
        "/api/v1/auth/reset-password",
        json={
            "email": ADMIN_EMAIL,
            "otp": sent[0],
            "new_password": "ResetPassw0rd!2",
        },
    )
    assert reset.status_code == 204, reset.text

    stale_me = await client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {old_access}"}
    )
    stale_refresh = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": old_refresh}
    )
    assert stale_me.status_code == 401
    assert stale_refresh.status_code == 401

    new_login = await client.post(
        "/api/v1/auth/login",
        json={"email": ADMIN_EMAIL, "password": "ResetPassw0rd!2"},
    )
    assert new_login.status_code == 200, new_login.text

    row = (
        await db_session.scalars(
            select(PasswordResetOtp).where(PasswordResetOtp.email == ADMIN_EMAIL)
        )
    ).first()
    assert row is not None
    assert row.consumed_at is not None


async def test_reset_password_rejects_wrong_expired_and_consumed_otps(
    client, db_session, monkeypatch
):
    sent: list[str] = []

    async def fake_send(*, to_email: str, otp: str) -> str:
        sent.append(otp)
        return "email_123"

    monkeypatch.setattr(
        "app.services.password_reset_service.send_password_reset_otp", fake_send
    )
    await client.post("/api/v1/auth/forgot-password", json={"email": ADMIN_EMAIL})

    bad = await client.post(
        "/api/v1/auth/reset-password",
        json={"email": ADMIN_EMAIL, "otp": "000000", "new_password": "NopePassw0rd!"},
    )
    assert bad.status_code == 400

    row = (
        await db_session.scalars(
            select(PasswordResetOtp).where(PasswordResetOtp.email == ADMIN_EMAIL)
        )
    ).first()
    assert row is not None
    assert row.attempt_count == 1

    row.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    await db_session.commit()
    expired = await client.post(
        "/api/v1/auth/reset-password",
        json={
            "email": ADMIN_EMAIL,
            "otp": sent[0],
            "new_password": "ExpiredPassw0rd!",
        },
    )
    assert expired.status_code == 400

    await client.post("/api/v1/auth/forgot-password", json={"email": ADMIN_EMAIL})
    current_otp = sent[-1]
    ok = await client.post(
        "/api/v1/auth/reset-password",
        json={
            "email": ADMIN_EMAIL,
            "otp": current_otp,
            "new_password": "ConsumedPassw0rd!",
        },
    )
    assert ok.status_code == 204
    consumed_again = await client.post(
        "/api/v1/auth/reset-password",
        json={
            "email": ADMIN_EMAIL,
            "otp": current_otp,
            "new_password": "ConsumedAgainPassw0rd!",
        },
    )
    assert consumed_again.status_code == 400


async def test_reset_password_attempt_cap_consumes_otp(client, db_session, monkeypatch):
    sent: list[str] = []

    async def fake_send(*, to_email: str, otp: str) -> str:
        sent.append(otp)
        return "email_123"

    monkeypatch.setattr(
        "app.services.password_reset_service.send_password_reset_otp", fake_send
    )
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "password_reset_otp_attempt_limit", 2)
    await client.post("/api/v1/auth/forgot-password", json={"email": ADMIN_EMAIL})
    for _ in range(2):
        r = await client.post(
            "/api/v1/auth/reset-password",
            json={
                "email": ADMIN_EMAIL,
                "otp": "000000",
                "new_password": "AttemptPassw0rd!",
            },
        )
        assert r.status_code == 400

    row = (
        await db_session.scalars(
            select(PasswordResetOtp).where(PasswordResetOtp.email == ADMIN_EMAIL)
        )
    ).first()
    assert row is not None
    assert row.attempt_count == 2
    assert row.consumed_at is not None

    correct_after_cap = await client.post(
        "/api/v1/auth/reset-password",
        json={
            "email": ADMIN_EMAIL,
            "otp": sent[0],
            "new_password": "AfterCapPassw0rd!",
        },
    )
    assert correct_after_cap.status_code == 400


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


async def test_admin_can_create_admin_and_recruiter_roles(client):
    tok = await _admin_token(client)
    h = _bearer(tok)
    for role in ("admin", "recruiter"):
        email = unique_email()
        r = await client.post(
            "/api/v1/users",
            json={"email": email, "password": "Abcd1234!", "role": role},
            headers=h,
        )
        assert r.status_code == 201, r.text
        assert r.json()["role"] == role


async def test_role_or_disabled_change_revokes_existing_tokens(client):
    tok = await _admin_token(client)
    h = _bearer(tok)
    email = unique_email()
    created = await client.post(
        "/api/v1/users",
        json={"email": email, "password": "Abcd1234!", "role": "recruiter"},
        headers=h,
    )
    uid = created.json()["id"]
    user_tok = (
        await client.post(
            "/api/v1/auth/login", json={"email": email, "password": "Abcd1234!"}
        )
    ).json()

    promoted = await client.patch(f"/api/v1/users/{uid}", json={"role": "admin"}, headers=h)
    assert promoted.status_code == 200
    stale_after_role = await client.get("/api/v1/auth/me", headers=_bearer(user_tok))
    assert stale_after_role.status_code == 401

    fresh = (
        await client.post(
            "/api/v1/auth/login", json={"email": email, "password": "Abcd1234!"}
        )
    ).json()
    disabled = await client.post(f"/api/v1/users/{uid}/disable", headers=h)
    assert disabled.status_code == 200
    stale_after_disable = await client.get("/api/v1/auth/me", headers=_bearer(fresh))
    assert stale_after_disable.status_code == 401


async def test_admin_cannot_disable_self(client):
    tok = await _admin_token(client)
    h = _bearer(tok)
    me = (await client.get("/api/v1/auth/me", headers=h)).json()
    r = await client.post(f"/api/v1/users/{me['id']}/disable", headers=h)
    assert r.status_code == 400


async def test_admin_cannot_self_demote(client):
    tok = await _admin_token(client)
    h = _bearer(tok)
    me = (await client.get("/api/v1/auth/me", headers=h)).json()
    r = await client.patch(f"/api/v1/users/{me['id']}", json={"role": "recruiter"}, headers=h)
    assert r.status_code == 409


async def test_cannot_remove_last_enabled_admin_via_service(db_session, seed):
    from app.models.user import Role
    from app.schemas.user import UserUpdate
    from app.services.user_service import UserProvisioningService

    admin = (
        await db_session.scalars(select(User).where(User.email == ADMIN_EMAIL))
    ).first()
    recruiter = (
        await db_session.scalars(select(User).where(User.email == RECRUITER_EMAIL))
    ).first()
    assert admin is not None
    assert recruiter is not None
    svc = UserProvisioningService(db_session)
    admins = (await db_session.scalars(select(User).where(User.role == Role.admin))).all()
    previous_disabled = {row.id: row.disabled for row in admins}

    try:
        for row in admins:
            row.disabled = row.id != admin.id
        await db_session.commit()

        with pytest.raises(ValueError):
            await svc.update(
                admin.id,
                UserUpdate(role=Role.recruiter),
                actor_id=recruiter.id,
            )
    finally:
        for row in admins:
            row.disabled = previous_disabled[row.id]
        await db_session.commit()


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
