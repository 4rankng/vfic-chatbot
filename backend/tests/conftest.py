"""Shared pytest fixtures for VFIC backend integration tests.

Two things matter for async-pg + pytest-asyncio to be stable:

1. **Event-loop isolation.** pytest-asyncio gives each test its own event loop,
   but asyncpg connections bind to the loop they were opened on. A pooled engine
   reusing a connection across loops blows up with "Future attached to a different
   loop". We swap in a NullPool engine (fresh connection per checkout, never reused
   across loops). The production pool is untouched — this swap lives in tests only.

2. **Email domains.** email-validator rejects reserved TLDs (.test/.example/.invalid),
   so test users use the reserved *domain* example.com (real .com TLD, accepted).
"""
import app.core.db as db_module
from app.core.config import get_settings
from app.core.security import hash_password
from app.main import app  # noqa: F401  (import for side effects / collection)
from app.models.audit import AuditEvent
from app.models.user import Role, User
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

# --- test engine (NullPool) swapped in for app.core.db globals -------------
_settings = get_settings()
_test_engine = create_async_engine(
    _settings.database_url, poolclass=NullPool, pool_pre_ping=False, future=True
)
_test_sessionmaker = async_sessionmaker(
    _test_engine, class_=AsyncSession, expire_on_commit=False
)
db_module.engine = _test_engine
db_module.async_session = _test_sessionmaker

ADMIN_EMAIL = "selftest.admin@example.com"
RECRUITER_EMAIL = "selftest.recruiter@example.com"
PASSWORD = "TestPassw0rd!"
TEST_DOMAIN = "@example.com"


async def _seed_users() -> None:
    async with _test_sessionmaker() as db:
        for email, role in ((ADMIN_EMAIL, Role.admin), (RECRUITER_EMAIL, Role.recruiter)):
            existing = (
                await db.scalars(select(User).where(User.email == email))
            ).first()
            if existing is None:
                db.add(
                    User(
                        email=email,
                        password_hash=await hash_password(PASSWORD),
                        full_name=email.split("@")[0],
                        role=role,
                    )
                )
        await db.commit()


async def _purge_test_data() -> None:
    """Delete every test-domain user and any audit rows referencing them."""
    async with _test_sessionmaker() as db:
        ids = [
            row[0]
            for row in (
                await db.execute(select(User.id).where(User.email.endswith(TEST_DOMAIN)))
            ).all()
        ]
        if ids:
            id_strs = [str(i) for i in ids]
            await db.execute(delete(AuditEvent).where(AuditEvent.actor_id.in_(ids)))
            await db.execute(
                delete(AuditEvent).where(
                    AuditEvent.target_type == "user",
                    AuditEvent.target_id.in_(id_strs),
                )
            )
        await db.execute(delete(User).where(User.email.endswith(TEST_DOMAIN)))
        await db.commit()


import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy import text as _sa_text  # noqa: E402


@pytest_asyncio.fixture
async def clean_kb(db_session):
    """Shared knowledge-table cleanup (drive_file_id uniqueness + reconcile counts
    are stateful and the DB persists across runs)."""
    await db_session.execute(_sa_text("TRUNCATE knowledge_documents CASCADE"))
    await db_session.commit()
    yield
    await db_session.execute(_sa_text("TRUNCATE knowledge_documents CASCADE"))
    await db_session.commit()


# Per-turn business tables wiped before every test. This dev Postgres persists
# across runs, and many tests seed rows with hardcoded ids or assert on mutex
# state (bot_locked_until / version), so residue from a prior run or test
# collides (UniqueViolation / stale state) and the suite looks flaky. Reference
# + seed tables (users, jobs, projects, companies, personas, bus_*,
# system_settings) are deliberately preserved; KB tables stay owned by clean_kb.
_TRANSIENT_TABLES = (
    "audit_events",
    "message_dedup",
    "outbound_messages",
    "messages",
    "bot_runs",
    "follow_up_tasks",
    "lead_events",
    "leads",
    "memories",
    "conversations",
)
_TRUNCATE_TRANSIENT = _sa_text(
    "TRUNCATE TABLE " + ", ".join(_TRANSIENT_TABLES) + " RESTART IDENTITY CASCADE"
)


@pytest_asyncio.fixture(autouse=True)
async def _isolate_transient_tables():
    async with _test_sessionmaker() as db:
        await db.execute(_TRUNCATE_TRANSIENT)
        await db.commit()
    yield


@pytest_asyncio.fixture
async def seed():
    await _seed_users()
    yield
    await _purge_test_data()


@pytest_asyncio.fixture
async def client(seed):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture
async def db_session():
    async with _test_sessionmaker() as db:
        yield db


@pytest_asyncio.fixture
async def _reset_redis():
    """Force a fresh async Redis client per test (bound to THIS test's event loop).

    Like the asyncpg pool, the redis singleton would otherwise reuse a connection
    tied to a previous test's (now-closed) loop -> "Event loop is closed" on close.
    """
    import app.core.redis as redis_module

    prev = redis_module._async
    redis_module._async = None
    if prev is not None:
        try:
            await prev.aclose()
        except Exception:  # noqa: BLE001
            pass
    yield
    cur = redis_module._async
    redis_module._async = None
    if cur is not None:
        try:
            await cur.aclose()
        except Exception:  # noqa: BLE001
            pass


def unique_email() -> str:
    import uuid

    return f"u{uuid.uuid4().hex[:8]}{TEST_DOMAIN}"
