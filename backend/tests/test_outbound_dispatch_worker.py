from __future__ import annotations

import inspect

from app.workers import outbound_dispatch_worker


async def test_async_worker_adapter_delegates_to_composition(monkeypatch) -> None:
    calls: list[str] = []

    async def fake_run() -> None:
        calls.append("run")

    monkeypatch.setattr(
        "app.composition.conversation_messaging.run_outbound_recovery",
        fake_run,
    )

    await outbound_dispatch_worker._dispatch_pending()

    assert calls == ["run"]


def test_worker_keeps_stable_entrypoint_without_recovery_rules() -> None:
    source = inspect.getsource(outbound_dispatch_worker)

    assert "def run_outbound_dispatch_tick" in source
    assert "run_async(_dispatch_pending())" in source
    assert "app.models" not in source
    assert "app.services" not in source
    assert "dispatch_outbox" not in source
    assert "claim_stale_sending_unknown" not in source
