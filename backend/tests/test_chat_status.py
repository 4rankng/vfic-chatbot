"""Native status is bounded, regular, and gone before the answer is sent."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from app.core.config import Settings
from app.graph import chat_status
from app.graph.chat_status import chat_status_interval
from app.graph.dispatch import _cancel_status_task, _status_heartbeat


@pytest.mark.parametrize("old_interval", [3.5, 4.0, 60.0, float("inf"), float("nan"), 0, -1])
def test_legacy_configuration_keeps_a_three_second_maximum(old_interval):
    assert chat_status_interval(old_interval) == 3.0


def test_default_native_status_interval_is_three_seconds():
    assert Settings(_env_file=None).typing_heartbeat_seconds == 3.0


@pytest.fixture
def controlled_clock(monkeypatch):
    now = [0.0]
    real_sleep = asyncio.sleep

    async def sleep(seconds):
        now[0] += seconds
        await real_sleep(0)

    monkeypatch.setattr(chat_status, "monotonic", lambda: now[0])
    monkeypatch.setattr(chat_status, "sleep", sleep)
    return now


async def test_native_status_starts_immediately_and_repeats_every_three_seconds(controlled_clock):
    starts = []
    third_pulse = asyncio.Event()

    class Sender:
        async def send_chat_action(self, chat_id, action):
            starts.append(controlled_clock[0])
            if len(starts) == 3:
                third_pulse.set()

    task = asyncio.create_task(_status_heartbeat(
        Sender(), "candidate", settings=SimpleNamespace(typing_heartbeat_seconds=3.5),
    ))
    try:
        await asyncio.wait_for(third_pulse.wait(), timeout=2)
    finally:
        await _cancel_status_task(task)
    assert starts[:3] == [0.0, 3.0, 6.0]
    assert all(b - a == 3 for a, b in zip(starts, starts[1:]))


async def test_status_schedule_does_not_add_provider_latency_to_the_interval(controlled_clock):
    starts: list[float] = []
    fourth_pulse = asyncio.Event()

    class Sender:
        async def send_chat_action(self, chat_id, action):
            starts.append(controlled_clock[0])
            controlled_clock[0] += 0.75
            if len(starts) == 4:
                fourth_pulse.set()

    task = asyncio.create_task(_status_heartbeat(
        Sender(), "candidate", settings=SimpleNamespace(typing_heartbeat_seconds=3),
    ))
    try:
        await asyncio.wait_for(fourth_pulse.wait(), timeout=2)
    finally:
        await _cancel_status_task(task)
    assert starts[:4] == [0.0, 3.0, 6.0, 9.0]
    assert all(b - a == 3 for a, b in zip(starts, starts[1:]))


async def test_unresponsive_status_request_is_cancelled_and_retried_without_overlap():
    starts = 0
    fourth_pulse = asyncio.Event()
    active = 0
    maximum_active = 0
    cancelled = 0

    class Sender:
        async def send_chat_action(self, chat_id, action):
            nonlocal active, maximum_active, cancelled, starts
            starts += 1
            if starts == 4:
                fourth_pulse.set()
            active += 1
            maximum_active = max(maximum_active, active)
            try:
                await asyncio.Event().wait()
            finally:
                active -= 1
                cancelled += 1

    task = asyncio.create_task(_status_heartbeat(
        Sender(), "candidate", settings=SimpleNamespace(typing_heartbeat_seconds=0.04),
    ))
    try:
        await asyncio.wait_for(fourth_pulse.wait(), timeout=2)
    finally:
        await _cancel_status_task(task)
    assert starts >= 4
    assert maximum_active == 1
    assert active == 0
    assert cancelled == starts


async def test_transient_status_failure_does_not_stop_following_pulses():
    calls = []
    fourth_pulse = asyncio.Event()

    class Sender:
        async def send_chat_action(self, chat_id, action):
            calls.append((chat_id, action))
            if len(calls) == 4:
                fourth_pulse.set()
            raise RuntimeError("provider unavailable")

    task = asyncio.create_task(_status_heartbeat(
        Sender(), "candidate", settings=SimpleNamespace(typing_heartbeat_seconds=0.04),
    ))
    try:
        await asyncio.wait_for(fourth_pulse.wait(), timeout=2)
    finally:
        await _cancel_status_task(task)
    assert len(calls) >= 4
    assert set(calls) == {("candidate", "typing")}
