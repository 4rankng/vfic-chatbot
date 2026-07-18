from argparse import Namespace

import pytest

from scripts import backfill_project_categories as script


@pytest.mark.asyncio
async def test_main_disposes_engine_on_the_same_event_loop(monkeypatch) -> None:
    events: list[str] = []

    async def run(_args: Namespace) -> int:
        events.append("run")
        return 0

    class Engine:
        async def dispose(self) -> None:
            events.append("dispose")

    monkeypatch.setattr(script, "_run", run)
    monkeypatch.setattr(script, "engine", Engine())

    assert await script._main(Namespace()) == 0
    assert events == ["run", "dispose"]
