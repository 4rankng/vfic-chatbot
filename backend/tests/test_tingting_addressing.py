"""Gendered addressing on the TingTing support OA (lanes._tingting_addressing).

The Zalo display name lives on the contact record, never in the chat: the bot
must still address the employee by the right pronoun. These tests pin that the
inference reaches the prompt as a pronoun instruction (never the name itself)
and that every failure mode degrades to the neutral default instead of breaking
a turn.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from app.graph.lanes import _tingting_addressing
from app.shared.domain.vietnamese_gender import infer_gender_from_name


@dataclass
class _Contact:
    display_name: str = ""


@dataclass
class _Conv:
    contact: _Contact | None = None


class _ConversationPort:
    """Minimal ConversationPort double: one canned conversation."""

    def __init__(self, conv: _Conv | None) -> None:
        self._conv = conv
        self.calls: list[Any] = []

    async def get(self, conv_id: Any) -> _Conv | None:
        self.calls.append(conv_id)
        return self._conv

    def __getattr__(self, name):  # the helper touches nothing else
        raise AssertionError(f"unexpected port access: {name}")


@dataclass
class _Deps:
    conversation: Any = field(default_factory=lambda: _ConversationPort(None))


@dataclass
class _State:
    conversation_id: str = "conv-1"


def test_the_prod_name_carries_a_male_marker() -> None:
    # 2026-09-28: "Trần Quang Việt" was addressed with the neutral "anh/chị"
    # because the name lived only on the contact record.
    assert infer_gender_from_name("Trần Quang Việt") == "male"


async def test_male_name_becomes_an_anh_instruction_without_the_name() -> None:
    deps = _Deps(conversation=_ConversationPort(_Conv(contact=_Contact("Trần Quang Việt"))))

    text = await _tingting_addressing(_State(), deps)

    assert "XƯNG HÔ" in text
    assert '"anh"' in text
    assert "Trần Quang Việt" not in text  # the name never enters the prompt


async def test_female_name_becomes_a_chi_instruction() -> None:
    deps = _Deps(conversation=_ConversationPort(_Conv(contact=_Contact("Nguyễn Thị Hồng"))))

    text = await _tingting_addressing(_State(), deps)

    assert "XƯNG HÔ" in text
    assert '"chị"' in text


async def test_neutral_or_missing_names_keep_the_default_addressing() -> None:
    no_contact = _Deps(conversation=_ConversationPort(_Conv(contact=None)))
    no_name = _Deps(conversation=_ConversationPort(_Conv(contact=_Contact())))
    nameless_conv = _Deps(conversation=_ConversationPort(None))

    assert await _tingting_addressing(_State(), no_contact) == ""
    assert await _tingting_addressing(_State(), no_name) == ""
    assert await _tingting_addressing(_State(), nameless_conv) == ""


async def test_a_port_failure_degrades_to_the_neutral_default(monkeypatch) -> None:
    class _Broken:
        async def get(self, _conv_id):
            raise RuntimeError("db down")

    monkeypatch.setattr(
        "app.graph.lanes.logger.warning",
        lambda *_a, **_kw: None,
        raising=False,
    )
    deps = _Deps(conversation=_Broken())

    assert await _tingting_addressing(_State(), deps) == ""


@pytest.mark.parametrize(
    ("name", "pronoun"),
    [
        ("Nguyễn Văn An", "anh"),
        ("Lê Thị Bích", "chị"),
    ],
)
async def test_common_name_shapes_map_to_the_expected_pronoun(name: str, pronoun: str) -> None:
    deps = _Deps(conversation=_ConversationPort(_Conv(contact=_Contact(name))))

    text = await _tingting_addressing(_State(), deps)

    assert f'"{pronoun}"' in text
