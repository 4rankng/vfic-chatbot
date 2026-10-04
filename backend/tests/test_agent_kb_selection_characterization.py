"""The persona no longer varies by channel.

Persona selection used to be provider-scoped: each adapter resolved an effective
persona from its own override, falling back to the active global row. Persona
storage was removed on 2026-10-04, so there is one persona by construction and no
channel can be given a different voice. Project selection remains an independent
knowledge concern and is unaffected.
"""

from __future__ import annotations

import pytest

from app.graph.context import resolve_effective_persona
from app.graph.prompts import AGENT_SYSTEM_PROMPT


@pytest.mark.parametrize("provider", ["zalo_bot", "zalo_oa", "facebook_messenger"])
def test_every_channel_speaks_the_same_persona(provider: str) -> None:
    # The provider is deliberately not passed to the resolver: the point of the
    # test is that the call site no longer has anywhere to pass it.
    assert resolve_effective_persona() == AGENT_SYSTEM_PROMPT


def test_persona_selection_takes_no_provider() -> None:
    """The resolver has no retrieval port and no provider argument at all.

    This is the load-bearing part: if a future change re-adds either, a channel
    could again diverge, and nothing else in the suite would notice.
    """
    import inspect

    params = inspect.signature(resolve_effective_persona).parameters

    assert list(params) == []
