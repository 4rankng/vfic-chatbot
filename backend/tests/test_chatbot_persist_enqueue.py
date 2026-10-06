"""A lost candidate-extraction enqueue must be visible, never silent.

The turn deliberately survives a Redis hiccup (`_enqueue_persist` is
best-effort), but a dropped enqueue used to cost a candidate's lead details
with nothing in the logs. P1 of the extraction-reliability work pins both
sides: failure logs at ERROR with the chat id, success stays quiet.
"""

from __future__ import annotations

import logging
from unittest.mock import patch

from app.workers import chatbot_worker


def test_failed_extraction_enqueue_is_logged_with_the_chat_id(caplog) -> None:
    with (
        caplog.at_level(logging.ERROR, logger="app.workers.chatbot_worker"),
        patch(
            "app.workers.persistence_worker.enqueue_persist_candidate",
            return_value=False,
        ),
    ):
        chatbot_worker._enqueue_persist({"chat_id": "candidate-chat"})

    messages = [record.message for record in caplog.records]
    assert any(
        "candidate extraction enqueue failed" in message and "candidate-chat" in message
        for message in messages
    )


def test_successful_extraction_enqueue_stays_quiet(caplog) -> None:
    with (
        caplog.at_level(logging.ERROR, logger="app.workers.chatbot_worker"),
        patch(
            "app.workers.persistence_worker.enqueue_persist_candidate",
            return_value=True,
        ),
    ):
        chatbot_worker._enqueue_persist({"chat_id": "candidate-chat"})

    assert not [
        record
        for record in caplog.records
        if "candidate extraction enqueue failed" in record.message
    ]
