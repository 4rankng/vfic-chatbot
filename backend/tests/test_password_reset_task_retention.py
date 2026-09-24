"""REL-04: the password-reset OTP send must be a retained, observable task.

The defect: ``request_reset`` did ``asyncio.create_task(self._send_reset_email(...))``
and dropped the handle, so the task could be garbage-collected mid-flight — the
API answered "check your email" while the mail never sent and no
``password_reset_email_sent`` / ``_failed`` audit row was ever written.

These tests drive the real scheduling path with a recording session double and a
faked mail provider: the task is retained while pending, removed when it settles,
and both the success and failure paths write their audit row.
"""

from __future__ import annotations

import asyncio
import uuid
from contextlib import asynccontextmanager

import pytest

from app.identity.domain.role import Role
from app.models.user import User
from app.services import password_reset_service as prs


class _RecordingSession:
    def __init__(self) -> None:
        self.audit_actions: list[str] = []
        self.commits = 0

    def add(self, instance) -> None:  # noqa: ANN001
        action = getattr(instance, "action", None)
        if isinstance(action, str):
            self.audit_actions.append(action)

    async def flush(self) -> None:
        return None

    async def commit(self) -> None:
        self.commits += 1


class _ScalarsResult:
    def __init__(self, value: object | None) -> None:
        self._value = value

    def first(self) -> object | None:
        return self._value


class _RequestSession(_RecordingSession):
    """Session double for the ``request_reset`` read/update/insert path."""

    def __init__(self, user: User | None) -> None:
        super().__init__()
        self.user = user

    async def scalars(self, _statement):  # noqa: ANN001
        return _ScalarsResult(self.user)

    async def execute(self, _statement):  # noqa: ANN001
        return None


@pytest.fixture(autouse=True)
def _drain_retained_tasks():
    prs._send_tasks.clear()
    yield
    prs._send_tasks.clear()


@pytest.fixture
def _isolated_sessions(monkeypatch):
    """Route the task's own ``async_session()`` to a recording double."""
    sessions: list[_RecordingSession] = []

    @asynccontextmanager
    async def _session_factory():
        session = _RecordingSession()
        sessions.append(session)
        yield session

    monkeypatch.setattr("app.core.db.async_session", _session_factory)
    return sessions


def _user() -> User:
    return User(
        id=uuid.uuid4(),
        email="candidate@example.com",
        password_hash="x",
        role=Role.recruiter,
        disabled=False,
        token_version=0,
    )


@pytest.mark.asyncio
async def test_request_reset_retains_the_send_task_and_records_the_send(
    monkeypatch, _isolated_sessions
) -> None:
    sent: list[dict[str, str]] = []

    async def _fake_send(*, to_email: str, otp: str) -> str:
        sent.append({"to_email": to_email, "otp": otp})
        return "provider-1"

    monkeypatch.setattr(prs, "send_password_reset_otp", _fake_send)
    user = _user()
    service = prs.PasswordResetService(_RequestSession(user))

    await service.request_reset(" Candidate@Example.COM ")

    # The handle is held: a GC pass cannot collect the in-flight task.
    assert len(prs._send_tasks) == 1
    task = next(iter(prs._send_tasks))

    await task
    await asyncio.sleep(0)  # let the done callback run

    assert prs._send_tasks == set()
    assert len(sent) == 1
    assert sent[0]["to_email"] == "candidate@example.com"
    assert len(sent[0]["otp"]) == 6 and sent[0]["otp"].isdigit()
    assert _isolated_sessions[0].audit_actions == ["password_reset_email_sent"]
    assert _isolated_sessions[0].commits == 1


@pytest.mark.asyncio
async def test_a_failed_send_still_writes_the_failed_audit_row(
    monkeypatch, _isolated_sessions
) -> None:
    async def _failing_send(*, to_email: str, otp: str) -> str:
        raise RuntimeError("provider down")

    monkeypatch.setattr(prs, "send_password_reset_otp", _failing_send)

    await prs.PasswordResetService(_RequestSession(None))._send_reset_email(
        user_id=uuid.uuid4(), email="candidate@example.com", otp="123456"
    )

    assert _isolated_sessions[0].audit_actions == ["password_reset_email_failed"]


@pytest.mark.asyncio
async def test_a_spawned_send_is_retained_until_it_settles() -> None:
    started = asyncio.Event()
    release = asyncio.Event()

    async def _work() -> None:
        started.set()
        await release.wait()

    task = prs._spawn_send_task(_work())
    await started.wait()

    assert prs._send_tasks == {task}

    release.set()
    await task
    await asyncio.sleep(0)

    assert prs._send_tasks == set()


@pytest.mark.asyncio
async def test_a_failing_send_task_is_logged_not_swallowed(caplog) -> None:
    async def _boom() -> None:
        raise RuntimeError("boom")

    with caplog.at_level("ERROR", logger=prs.__name__):
        task = prs._spawn_send_task(_boom())
        await asyncio.gather(task, return_exceptions=True)
        await asyncio.sleep(0)

    assert "password reset email task failed" in caplog.text
    assert "boom" not in caplog.text  # message text is not logged, only the type


@pytest.mark.asyncio
async def test_a_cancelled_send_task_is_logged(caplog) -> None:
    async def _hang() -> None:
        await asyncio.Event().wait()

    with caplog.at_level("WARNING", logger=prs.__name__):
        task = prs._spawn_send_task(_hang())
        await asyncio.sleep(0)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await asyncio.sleep(0)

    assert "password reset email task cancelled" in caplog.text
    assert prs._send_tasks == set()
