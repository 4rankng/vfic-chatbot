"""Integration tests for the Phase 4 Facebook Page lifecycle state machine.

Drives :class:`FacebookPageLifecycle` and :class:`FacebookAccountResolver`
against the disposable integration database. Exercises the recoverable
state-machine transitions: activate, reactivate (same-Page reuse + generation
advance), replacement (prior Page archived), and disconnect (inactive, history
preserved). No external HTTP — OAuth/Graph calls are not invoked here.
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.user import User

pytestmark = pytest.mark.integration


@pytest.fixture
def sessions(integration_database):
    engine = create_async_engine(integration_database.async_url, pool_pre_ping=True)
    return async_sessionmaker(engine, expire_on_commit=False)


async def test_resolver_returns_none_for_unknown_page(integration_database):
    from app.channels.providers.facebook_account import FacebookAccountResolver
    from app.core.db import async_session

    async with async_session() as db:
        resolver = FacebookAccountResolver(db)
        assert await resolver.resolve_active(
            provider="facebook_messenger", account_key="page-unknown"
        ) is None
        assert await resolver.resolve_any(
            provider="facebook_messenger", account_key="page-unknown"
        ) is None
        assert await resolver.active_facebook_page() is None


async def test_lifecycle_activate_then_resolve_active(integration_database):
    from app.channels.providers.facebook_account import (
        FacebookAccountResolver,
        FacebookPageLifecycle,
    )
    from app.core.db import async_session

    async with async_session() as db:
        admin = User(
            email="fb-admin@vfic.test",
            password_hash="x",
            full_name="FB Admin",
            role="admin",
        )
        db.add(admin)
        await db.flush()
        admin_id = admin.id

        lifecycle = FacebookPageLifecycle(db)
        account = await lifecycle.activate_or_reactivate(
            page_id="page-111",
            page_name="Công ty ABC",
            page_access_token="EAAB-page-111-token",
            admin_id=admin_id,
        )
        assert account.status == "ACTIVE"
        assert account.account_key == "page-111"
        assert account.generation == 1

    async with async_session() as db:
        resolver = FacebookAccountResolver(db)
        active = await resolver.active_facebook_page()
        assert active is not None
        assert active.is_active
        assert active.account_key == "page-111"
        assert active.generation == 1


async def test_lifecycle_reactivate_same_page_reuses_account_and_advances_generation(
    integration_database,
):
    """Same-Page reactivation reuses the existing account and rotates the token;
    generation advances so stale queued commands are suppressed."""
    from app.channels.providers.facebook_account import FacebookPageLifecycle
    from app.core.db import async_session

    async with async_session() as db:
        admin = User(
            email="fb-admin2@vfic.test",
            password_hash="x",
            full_name="FB Admin 2",
            role="admin",
        )
        db.add(admin)
        await db.flush()
        admin_id = admin.id

        lifecycle = FacebookPageLifecycle(db)
        first = await lifecycle.activate_or_reactivate(
            page_id="page-222", page_name="P", page_access_token="t1", admin_id=admin_id
        )
        first_generation = first.generation  # capture before second activation
        second = await lifecycle.activate_or_reactivate(
            page_id="page-222", page_name="P", page_access_token="t2", admin_id=admin_id
        )
        assert first.id == second.id  # same account reused
        # NOTE: first and second are the same ORM object (row reused), so
        # first.generation now reads the post-second value. Compare against the
        # captured pre-second generation.
        assert second.generation > first_generation  # generation advanced


async def test_lifecycle_replacement_archives_prior_active_page(integration_database):
    """Selecting a different Page archives the prior active Page as INACTIVE
    (distinct read-only history scope). V1 enforces at most one active."""
    from app.channels.providers.facebook_account import (
        FacebookAccountResolver,
        FacebookPageLifecycle,
    )
    from app.core.db import async_session

    async with async_session() as db:
        admin = User(
            email="fb-admin3@vfic.test",
            password_hash="x",
            full_name="FB Admin 3",
            role="admin",
        )
        db.add(admin)
        await db.flush()
        admin_id = admin.id

        lifecycle = FacebookPageLifecycle(db)
        await lifecycle.activate_or_reactivate(
            page_id="page-A", page_name="A", page_access_token="tA", admin_id=admin_id
        )
        await lifecycle.activate_or_reactivate(
            page_id="page-B", page_name="B", page_access_token="tB", admin_id=admin_id
        )

    async with async_session() as db:
        resolver = FacebookAccountResolver(db)
        accounts = await resolver.list_facebook_accounts()
        active = [a for a in accounts if a.is_active]
        inactive = [a for a in accounts if not a.is_active]
        assert len(active) == 1
        assert active[0].account_key == "page-B"
        assert len(inactive) == 1
        assert inactive[0].account_key == "page-A"


async def test_lifecycle_disconnect_marks_inactive_keeps_history(integration_database):
    from app.channels.providers.facebook_account import (
        FacebookAccountResolver,
        FacebookPageLifecycle,
    )
    from app.core.db import async_session

    async with async_session() as db:
        admin = User(
            email="fb-admin4@vfic.test",
            password_hash="x",
            full_name="FB Admin 4",
            role="admin",
        )
        db.add(admin)
        await db.flush()
        admin_id = admin.id

        lifecycle = FacebookPageLifecycle(db)
        await lifecycle.activate_or_reactivate(
            page_id="page-D", page_name="D", page_access_token="tD", admin_id=admin_id
        )
        account = await lifecycle.disconnect(page_id="page-D", admin_id=admin_id)
        assert account is not None
        assert account.status == "INACTIVE"

    async with async_session() as db:
        resolver = FacebookAccountResolver(db)
        # resolve_active returns None (disconnected); resolve_any returns it.
        assert await resolver.resolve_active(
            provider="facebook_messenger", account_key="page-D"
        ) is None
        archived = await resolver.resolve_any(
            provider="facebook_messenger", account_key="page-D"
        )
        assert archived is not None
        assert not archived.is_active
