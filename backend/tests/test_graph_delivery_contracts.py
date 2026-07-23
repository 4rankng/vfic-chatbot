"""Graph delivery depends only on provider-neutral structural contracts."""

from __future__ import annotations

import ast
from pathlib import Path

from app.graph.ports import SendOutcome
from app.graph.runner import _dispatch_claimed_message


class _Conversation:
    zalo_chat_id = "chat-1"


class _MissingCommandService:
    async def dispatch_outbound_message(self, *, message_id: int | None):
        assert message_id == 41
        return None


class _UnexpectedSender:
    async def send_message(self, *_args, **_kwargs):
        raise AssertionError("durable dispatch must not fall back to direct provider I/O")


async def test_missing_durable_command_returns_neutral_delivery_outcome() -> None:
    result = await _dispatch_claimed_message(
        _MissingCommandService(),
        _UnexpectedSender(),
        _Conversation(),
        message_id=41,
        text="reply",
        quote_message_id=None,
    )

    assert result == SendOutcome(
        ok=False,
        error="outbound command was not available for dispatch",
    )
    assert result.error_class is None
    assert result.suppressed is False
    assert result.telemetry is None


def test_graph_runner_has_no_concrete_provider_result_import() -> None:
    runner_path = Path(__file__).parents[1] / "app" / "graph" / "runner.py"
    tree = ast.parse(runner_path.read_text())
    imported_modules = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }
    imported_modules.update(
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    )

    assert "app.services.zalo_bot_service" not in imported_modules
